"""Rank every option for one financing need (WP-06 milestone 5; FEATURES P1).

score (0-100) = 45% cost + 25% fit + 15% approval likelihood + 10% speed + 5% lender record
  cost      100 - 2.5 x EAR%      (4% a year scores 90, 13% scores 67.5, 27% scores 32.5;
                                   anything at 40% a year or more scores 0)
  fit       100 x (1 - P(balance < buffer)) from the cash forecast
  approval  heuristic per product kind, reduced for missing facts or collateral
  speed     100 - 3 x days to cash
  lender    lender score from track record (N20); 60 when there is no record
Options that fail eligibility are kept, with their reasons, but always rank below every
option that might work. Ties break on lower cost, then product id (deterministic).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.contracts import (
    DataMode,
    EligibilityStatus,
    FinancingNeed,
    FinancingOption,
    FinancingProduct,
    ForecastBand,
    LenderProfile,
    ProductKind,
)
from app.contracts.facts import Figure, Provenance, Unit
from app.engines.financing import cost as cost_mod
from app.engines.financing import fit as fit_mod
from app.engines.financing.eligibility import evaluate
from app.engines.financing.lenders import COLD_START_SCORE, lender_score

WEIGHTS = {"cost": Decimal("0.45"), "fit": Decimal("0.25"), "approval": Decimal("0.15"),
           "speed": Decimal("0.10"), "lender": Decimal("0.05")}

# Typical days from application to cash, by kind (documented assumptions, shown to users).
SPEED_DAYS: dict[ProductKind, int] = {
    ProductKind.nano_loan: 0, ProductKind.owner_topup: 0, ProductKind.mesh_netting: 2,
    ProductKind.supplier_term_extension: 2, ProductKind.buyer_early_pay: 3,
    ProductKind.factoring: 5, ProductKind.invoice_discounting: 5, ProductKind.mfi_loan: 7,
    ProductKind.leasing: 14, ProductKind.working_capital: 21, ProductKind.term_loan: 30,
    ProductKind.refinance_scheme: 30, ProductKind.digital_credit_modelled: 1,
    ProductKind.grant: 60,
}
BASE_APPROVAL: dict[ProductKind, Decimal] = {
    ProductKind.owner_topup: Decimal("1.0"), ProductKind.supplier_term_extension: Decimal("0.6"),
    ProductKind.buyer_early_pay: Decimal("0.5"), ProductKind.mesh_netting: Decimal("0.7"),
    ProductKind.nano_loan: Decimal("0.8"), ProductKind.mfi_loan: Decimal("0.85"),
    ProductKind.factoring: Decimal("0.6"), ProductKind.invoice_discounting: Decimal("0.6"),
    ProductKind.leasing: Decimal("0.5"), ProductKind.working_capital: Decimal("0.45"),
    ProductKind.term_loan: Decimal("0.4"), ProductKind.refinance_scheme: Decimal("0.35"),
    ProductKind.digital_credit_modelled: Decimal("0.7"), ProductKind.grant: Decimal("0.1"),
}
TWO = Decimal("0.01")


def _q(value: Decimal) -> Decimal:
    return value.quantize(TWO, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Candidate:
    option: FinancingOption
    cost: cost_mod.CostResult


def approval_likelihood(product: FinancingProduct, status: EligibilityStatus,
                        facts: Mapping[str, Decimal | None]) -> tuple[Decimal, list[str]]:
    reasons = []
    p = BASE_APPROVAL[product.kind]
    if status is EligibilityStatus.fail:
        return Decimal(0), ["approval.ineligible"]
    if status is EligibilityStatus.not_on_record:
        p *= Decimal("0.6")
        reasons.append("approval.facts_missing")
    if product.collateral_required and not facts.get("collateral_available"):
        p *= Decimal("0.5")
        reasons.append("approval.collateral_needed")
    return _q(p), reasons


def score_option(ear_percent: Decimal, p_breach: Decimal, approval: Decimal, speed_days: int,
                 lender: Decimal) -> Decimal:
    parts = {
        "cost": max(Decimal(0), Decimal(100) - Decimal("2.5") * ear_percent),
        "fit": Decimal(100) * (1 - p_breach),
        "approval": Decimal(100) * approval,
        "speed": max(Decimal(0), Decimal(100) - 3 * speed_days),
        "lender": lender,
    }
    return _q(sum((WEIGHTS[k] * v for k, v in parts.items()), Decimal(0)))


def _figure(fig_id: str, label: str, value: Decimal, unit: Unit, formula: str,
            params: dict[str, str], data_mode: DataMode) -> Figure:
    return Figure(id=fig_id, label_key=label, value=value, unit=unit, data_mode=data_mode,
                  provenance=Provenance(formula_id=formula, formula_version=1,
                                        parameters=params))


def match(
    need: FinancingNeed,
    products: Sequence[FinancingProduct],
    facts: Mapping[str, Decimal | None],
    *,
    start: date,
    band: ForecastBand | None = None,
    lenders: Mapping[str, LenderProfile] | None = None,
) -> list[Candidate]:
    lenders = lenders or {}
    scored: list[tuple[tuple, Candidate]] = []
    for product in products:
        eligibility = evaluate(product, facts, need.amount, need.tenor_days, need.purpose_key)
        result = cost_mod.true_cost(product, need.amount, need.tenor_days)
        reasons: list[str] = []
        if band is not None:
            p_breach = fit_mod.breach_probability(result, start, band)
        else:
            p_breach = Decimal(0)
            reasons.append("fit.no_forecast")
        approval, approval_reasons = approval_likelihood(product, eligibility.status, facts)
        reasons += approval_reasons
        profile = lenders.get(product.provider)
        lscore = lender_score(profile) if profile else COLD_START_SCORE
        if profile is None:
            reasons.append("lender.no_track_record")
        speed = SPEED_DAYS[product.kind]
        score = score_option(result.effective_annual_rate, p_breach, approval, speed, lscore)
        if eligibility.status is EligibilityStatus.fail:
            score = Decimal(0)
        params = {"product_id": product.id, "principal": str(need.amount.amount),
                  "tenor_days": str(need.tenor_days)}
        figures = (
            _figure(f"{product.id}:ear", "financing.effective_annual_rate",
                    result.effective_annual_rate, Unit.percent, cost_mod.FORMULA_ID, params,
                    product.data_mode),
            _figure(f"{product.id}:total_cost", "financing.total_cost", result.total_cost.amount,
                    Unit.BDT, cost_mod.FORMULA_ID, params, product.data_mode),
            _figure(f"{product.id}:breach", "financing.p_buffer_breach", p_breach,
                    Unit.probability, fit_mod.FORMULA_ID, params, product.data_mode),
        )
        option = FinancingOption(
            product=product,
            eligibility=eligibility,
            effective_apr=result.effective_annual_rate,
            total_cost=result.total_cost,
            p_buffer_breach=p_breach,
            speed_days=speed,
            approval_likelihood=approval,
            score=score,
            rank=1,
            figures=figures,
            reason_keys=tuple(reasons),
        )
        failed = eligibility.status is EligibilityStatus.fail
        key = (failed, -score, result.effective_annual_rate, product.id)
        scored.append((key, Candidate(option, result)))
    scored.sort(key=lambda item: item[0])
    return [
        Candidate(c.option.model_copy(update={"rank": i}), c.cost)
        for i, (_, c) in enumerate(scored, start=1)
    ]
