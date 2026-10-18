"""Residual gaps after netting, routed to the cheapest eligible financing (WP-08 milestone 4).

A netting round clears circular debt, but a participant may still have to pay cash it does not
have on the day. That shortfall is the residual gap. It is routed through WP-06: every product is
priced with the true-cost engine for exactly the gap and the bridge tenor, ineligible products
are dropped, and the cheapest by total taka cost wins (ties: lower effective annual rate, then
WP-06 rank). With no eligible product the router abstains instead of guessing, and the round
cannot settle for that participant until the owner decides.

Pure function over contracts: the caller supplies cash on hand per tenant (from the fact ledger,
with the fact ids for provenance), each tenant's eligibility facts and the product catalogue.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.contracts import (
    DataMode,
    EligibilityStatus,
    FinancingNeed,
    FinancingOption,
    FinancingProduct,
    ForecastBand,
    LenderProfile,
    Money,
    NettingRound,
)
from app.contracts.facts import Figure, Provenance, Unit
from app.engines.financing.ranking import match

FORMULA_GAP = "mesh.residual_gap"
FORMULA_ROUTE = "mesh.residual_route"
NO_ELIGIBLE = "mesh.residual.no_eligible_option"


@dataclass(frozen=True)
class ResidualGap:
    round_id: str
    tenant: str
    cash_out: Money  # what the round asks this tenant to pay
    available: Money  # cash on hand for it
    gap: Money  # max(0, cash_out - available)
    figure: Figure


@dataclass(frozen=True)
class RoutedGap:
    gap: ResidualGap
    option: FinancingOption | None  # None = abstain: nothing eligible
    total_cost: Money | None  # taka cost of bridging the gap with `option`
    alternatives: int  # eligible options considered
    reason_keys: tuple[str, ...]
    figures: tuple[Figure, ...]


def cash_out_by_tenant(round_: NettingRound) -> dict[str, Money]:
    out = {t: Money.zero() for t in round_.participants}
    for s in round_.settlements:
        out[s.payer_tenant] = out[s.payer_tenant] + s.amount
    return out


def residual_gaps(
    round_: NettingRound,
    available: Mapping[str, Money],
    *,
    fact_ids: Mapping[str, str] | None = None,
) -> tuple[ResidualGap, ...]:
    """One entry per participant that must pay more than it has. A tenant missing from
    `available` is treated as having nothing (fail closed: never assume cash)."""
    fact_ids = fact_ids or {}
    gaps = []
    for tenant, cash_out in sorted(cash_out_by_tenant(round_).items()):
        have = available.get(tenant, Money.zero())
        short = cash_out - have
        if short.amount <= 0:
            continue
        figure = Figure(
            id=f"{round_.id}:{tenant}:residual_gap",
            label_key="mesh.residual_gap",
            value=short.amount,
            unit=Unit.BDT,
            provenance=Provenance(
                formula_id=FORMULA_GAP, formula_version=1,
                input_fact_ids=tuple(x for x in (fact_ids.get(tenant),) if x),
                parameters={"round_id": round_.id, "tenant": tenant,
                            "cash_out": str(cash_out.amount), "available": str(have.amount)},
            ),
            data_mode=round_.data_mode,
        )
        gaps.append(ResidualGap(round_.id, tenant, cash_out, have, short, figure))
    return tuple(gaps)


def route_gap(
    gap: ResidualGap,
    products: Sequence[FinancingProduct],
    facts: Mapping[str, Decimal | None],
    *,
    start: date,
    needed_by: date,
    tenor_days: int,
    band: ForecastBand | None = None,
    lenders: Mapping[str, LenderProfile] | None = None,
) -> RoutedGap:
    """Cheapest eligible way to bridge `gap` for `tenor_days` (until the tenant's next inflow)."""
    need = FinancingNeed(tenant_id=gap.tenant, amount=gap.gap, needed_by=needed_by,
                         tenor_days=tenor_days)
    ranked = match(need, products, facts, start=start, band=band, lenders=lenders)
    eligible = [c for c in ranked if c.option.eligibility.status is not EligibilityStatus.fail]
    if not eligible:
        return RoutedGap(gap, None, None, 0, (NO_ELIGIBLE,), (gap.figure,))
    best = min(eligible, key=lambda c: (c.cost.total_cost.amount, c.option.effective_apr,
                                        c.option.rank))
    params = {"round_id": gap.round_id, "tenant": gap.tenant, "gap": str(gap.gap.amount),
              "tenor_days": str(tenor_days), "product_id": best.option.product.id,
              "rule": "min total_cost over eligible; ties: EAR, then WP-06 rank"}
    cost_figure = Figure(
        id=f"{gap.round_id}:{gap.tenant}:residual_cost",
        label_key="mesh.residual_cost",
        value=best.cost.total_cost.amount,
        unit=Unit.BDT,
        provenance=Provenance(formula_id=FORMULA_ROUTE, formula_version=1,
                              input_fact_ids=gap.figure.provenance.input_fact_ids,
                              parameters=params),
        data_mode=_mode(gap, best.option.product),
    )
    reasons = ("mesh.residual.cheapest_eligible",)
    if best.option.rank != 1:
        reasons += ("mesh.residual.cheaper_than_top_ranked",)
    return RoutedGap(gap, best.option, best.cost.total_cost, len(eligible), reasons,
                     (gap.figure, cost_figure, *best.option.figures))


def route_round(
    round_: NettingRound,
    available: Mapping[str, Money],
    products: Sequence[FinancingProduct],
    facts_by_tenant: Mapping[str, Mapping[str, Decimal | None]],
    *,
    start: date,
    tenor_days: int,
    fact_ids: Mapping[str, str] | None = None,
    lenders: Mapping[str, LenderProfile] | None = None,
) -> tuple[RoutedGap, ...]:
    """Every residual gap of a round, routed. Cash must be in hand before the round expires."""
    needed_by = round_.expires_at.date()
    return tuple(
        route_gap(g, products, facts_by_tenant.get(g.tenant, {}), start=start,
                  needed_by=needed_by, tenor_days=tenor_days, lenders=lenders)
        for g in residual_gaps(round_, available, fact_ids=fact_ids)
    )


def _mode(gap: ResidualGap, product: FinancingProduct) -> DataMode:
    """Synthetic if either input is; otherwise the tenant data's mode (the catalogue is only the
    price list)."""
    if DataMode.synthetic in (gap.figure.data_mode, product.data_mode):
        return DataMode.synthetic
    return gap.figure.data_mode
