"""Smoothing levers: priced, measured ways to shrink a cash gap (WP-04 milestone 5; FEATURES Q1).

Each lever is a `Scenario` replayed on the gap's own Monte Carlo draws, so its effect is exact
for those paths: gap reduction = expected shortfall over the gap's days without the lever minus
with it. Only levers that reduce the gap are offered. Each becomes an ActionCard with the tier
WP-11 requires (EXECUTE for anything that leaves DecisionGuard: a message, a payment, a discount;
DRAFT for a netting proposal or a loan application that stays inside it), and the list is
ranked cheapest first, then by the larger reduction.

  retime_payable      pay a supplier bill on its due date instead of early, as the business
                      usually pays that supplier (within terms: never after the due date). Cost 0.
  stagger_purchase    split the buying week whose bills fall due on the way into the gap
                      (at the usual days-to-pay): half of it is bought a week later, as two
                      smaller lots. Cost 0 in cash; the card notes a bulk discount may be lost.
  request_advance     ask a customer for half of an open invoice in 2 days, the rest as usual.
                      Cost 0. Offered for the 3 invoices with the most cash expected after the
                      breach.
  early_pay_discount  offer 2% off an open invoice paid in full in 2 days instead of when the
                      customer usually pays (their median delay); only when its annual cost
                      (WP-06 `early_pay_discount_cost`) is below the cheapest eligible loan in
                      the catalogue, or no loan is eligible. Cost = the discount.
  netting             clear the business's circular debts through the liquidity mesh (WP-08
                      min-cost flow): the netted bills and invoices go, the round's settlements
                      are paid in 2 days. Cost 0: netting never changes a net position.
  standby_facility    arrange the best-ranked eligible loan (WP-06 ranking) that can pay out
                      before the breach (else the best-ranked one), drawn the day before the
                      breach (or as soon as it pays out), for the shortfall that covers the gap
                      in 19 of 20 paths (rounded up to Tk 1,000), 90 days. Cost = WP-06 total
                      cost (interest and fees).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from app.contracts import (
    ActionCard,
    ActionType,
    EligibilityStatus,
    Figure,
    FinancingNeed,
    FinancingProduct,
    LenderProfile,
    LeverKind,
    MeshObligation,
    Money,
    SmoothingLever,
    Tier,
    Unit,
)
from app.engines.cash.figures import NO_EVIDENCE, Evidence, make_figure
from app.engines.cash.gaps import Gap, shortfall
from app.engines.cash.simulate import (
    PAISA,
    Draws,
    InvoiceChange,
    Scenario,
    Simulation,
    rank,
    run,
    to_paisa,
)
from app.engines.financing.cost import early_pay_discount_cost, true_cost
from app.engines.financing.eligibility import evaluate
from app.engines.financing.ranking import SPEED_DAYS, match
from app.engines.mesh.graph import build_graph
from app.engines.mesh.netting import propose_rounds

DHAKA = ZoneInfo("Asia/Dhaka")
ADVANCE_SHARE = Decimal("0.5")
SOON_DAYS = 2  # an advance, an early payment or a netting settlement arrives in 2 days
DISCOUNT_PERCENT = Decimal(2)
STAGGER_PERCENT = Decimal(50)
STAGGER_DAYS = 7
STANDBY_TENOR_DAYS = 90
STANDBY_COVER_PERCENT = 95  # the shortfall covered in 19 of 20 paths
ROUND_TO = Decimal(1000)
CANDIDATE_INVOICES = 3
ZERO = Decimal(0)
_KIND_ORDER = {kind: n for n, kind in enumerate(LeverKind)}


@dataclass(frozen=True)
class LeverContext:
    """A gap's simulation and everything a lever may consult (all supplied by the caller)."""

    sim: Simulation  # built as run(sim.baseline, draws, sim.scenario)
    draws: Draws
    now: datetime = field(default_factory=lambda: datetime.now(UTC))
    evidence: Evidence = NO_EVIDENCE
    products: Sequence[FinancingProduct] = ()  # WP-06 catalogue
    facts: Mapping[str, Decimal | None] = field(default_factory=dict)  # eligibility facts
    lenders: Mapping[str, LenderProfile] = field(default_factory=dict)
    mesh: Sequence[MeshObligation] = ()  # open obligations between opted-in tenants

    @property
    def soon(self) -> date:
        return self.sim.baseline.as_of + timedelta(days=SOON_DAYS)


@dataclass(frozen=True)
class Lever:
    lever: SmoothingLever
    scenario: Scenario  # the change replayed on the draws (for audit and what-ifs)
    shortfall_after: Decimal
    probability_after: Decimal


def combine(base: Scenario, change: Scenario) -> Scenario:
    """`change` applied on top of `base` (a what-if keeps its own changes)."""
    return Scenario(
        name=change.name if base.name == "baseline" else f"{base.name}+{change.name}",
        sales_change_pct=base.sales_change_pct, cost_change_pct=base.cost_change_pct,
        collection_delay_days=base.collection_delay_days, flows=base.flows + change.flows,
        bill_payments={**base.bill_payments, **change.bill_payments},
        invoice_changes={**base.invoice_changes, **change.invoice_changes},
        defer_purchases=base.defer_purchases + change.defer_purchases)


def _q(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _jsonable(payload: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, Decimal | date):
            out[key] = str(value)
        elif isinstance(value, tuple | list):
            out[key] = [str(v) if isinstance(v, Decimal | date) else v for v in value]
        else:
            out[key] = value
    return out


@dataclass(frozen=True)
class _Offer:
    kind: LeverKind
    name: str  # unique per gap, e.g. "retime:sme_x:B-17"
    change: Scenario
    cost: Decimal
    title_key: str
    action: ActionType
    tier: Tier
    payload: Mapping[str, Any]
    rows: tuple[str, ...] = ()
    cost_params: Mapping[str, object] = field(default_factory=dict)
    figures: tuple[Figure, ...] = ()


def _measure(ctx: LeverContext, gap: Gap, offer: _Offer) -> Lever | None:
    scenario = combine(ctx.sim.scenario, offer.change)
    after = run(ctx.sim.baseline, ctx.draws, scenario)
    probability, left = shortfall(after, gap.buffer, gap.first, gap.last)
    reduction = gap.gap.expected_shortfall.amount - left
    if reduction <= 0:
        return None
    base = ctx.sim.baseline
    params = {"lever": offer.name, "buffer": gap.buffer,
              "first_day": base.as_of + timedelta(days=gap.first),
              "last_day": base.as_of + timedelta(days=gap.last),
              "shortfall_before": gap.gap.expected_shortfall.amount, "shortfall_after": left}
    impact = make_figure(ctx.sim, "cash.lever_gap_reduction", "action.gap_reduced", reduction,
                         Unit.BDT, ctx.evidence, offer.rows, params)
    cost = make_figure(ctx.sim, "cash.lever_cost", "action.cost", offer.cost, Unit.BDT,
                       ctx.evidence, offer.rows, {"lever": offer.name, **offer.cost_params})
    after_p = make_figure(ctx.sim, "cash.lever_probability_after",
                          "action.breach_probability_after", probability, Unit.probability,
                          ctx.evidence, offer.rows, params)
    key = f"{base.tenant_id}|{base.as_of}|{gap.gap.first_breach_day}|{offer.name}"
    card = ActionCard(
        id="act_" + hashlib.sha256(key.encode()).hexdigest()[:20], title_key=offer.title_key,
        action_type=offer.action, tier=offer.tier, payload=_jsonable(offer.payload),
        figures=(after_p, *offer.figures), impact=impact, cost=cost,
        expires_at=datetime.combine(gap.gap.first_breach_day, time(0), DHAKA))
    lever = SmoothingLever(kind=offer.kind, gap_reduction=Money.of(reduction),
                           cost=Money.of(offer.cost), action=card)
    return Lever(lever=lever, scenario=offer.change, shortfall_after=left,
                 probability_after=probability)


# ---------------------------------------------------------------- the levers


def _retime(ctx: LeverContext, gap: Gap) -> list[_Offer]:
    base = ctx.sim.baseline
    offers = []
    for ob in sorted(base.open_bills, key=lambda o: o.bill.id):
        day = (ob.pay_day - base.as_of).days
        if ob.pay_day >= ob.bill.due_date or not gap.peak < day <= gap.last:
            continue
        offers.append(_Offer(
            LeverKind.retime_payable, f"retime:{ob.bill.id}",
            Scenario(name=f"retime:{ob.bill.id}",
                     bill_payments={ob.bill.id: ((ob.bill.due_date, ob.owed),)}),
            ZERO, "action.retime_payable", ActionType.retime_payable, Tier.EXECUTE,
            {"bill_id": ob.bill.id, "counterparty_token": ob.bill.counterparty_token,
             "amount": ob.owed, "usual_pay_date": ob.pay_day, "new_date": ob.bill.due_date,
             "due_date": ob.bill.due_date},
            (f"bill:{ob.bill.id}",), {"rule": "within terms: pay on the due date"}))
    return offers


def _stagger(ctx: LeverContext, gap: Gap) -> list[_Offer]:
    """Split the one buying week whose bills fall due as cash falls into the gap: half of
    it is bought a week later (cash purchases in that week move too)."""
    base = ctx.sim.baseline
    delays = base.bill_delays.issue_to_paid
    usual = delays[(len(delays) - 1) // 2] if delays else 0
    last = gap.worst - usual  # bought on this day, paid on the worst day
    if last < 1:
        return []  # those purchases are already made: re-time or extend the bill instead
    first = max(1, last - 6)
    start, end = (base.as_of + timedelta(days=n) for n in (first, last))
    suppliers: dict[str, Decimal] = {}
    first: dict[str, str] = {}  # equal amounts break on the first bill id, never the name
    for ob in base.open_bills:
        token = ob.bill.counterparty_token
        suppliers[token] = suppliers.get(token, ZERO) + ob.bill.amount.amount
        first[token] = min(first.get(token, ob.bill.id), ob.bill.id)
    supplier = min(suppliers, key=lambda t: (-suppliers[t], first[t])) if suppliers else None
    return [_Offer(
        LeverKind.stagger_purchase, "stagger",
        Scenario(name="stagger", defer_purchases=((start, end, STAGGER_PERCENT, STAGGER_DAYS),)),
        ZERO, "action.stagger_purchase", ActionType.send_message, Tier.EXECUTE,
        {"lever": "stagger_purchase", "from_date": start, "to_date": end,
         "share_percent": STAGGER_PERCENT, "days_later": STAGGER_DAYS,
         "usual_days_to_pay": usual, "counterparty_token": supplier,
         "note_key": "lever.stagger.bulk_discount_may_be_lost"},
        (), {"rule": "purchases moved, not cut"})]


def _late_invoices(ctx: LeverContext, gap: Gap) -> list[tuple[Any, Decimal, list[date]]]:
    """Open invoices with cash expected after the breach day, most such cash first."""
    base, scenario = ctx.sim.baseline, ctx.sim.scenario
    breach = gap.gap.first_breach_day
    found = []
    for inv, owed in base.open_invoices:
        if inv.id in scenario.invoice_changes:
            continue
        days = [d + timedelta(days=scenario.collection_delay_days)
                for d in base.invoice_delays.possible_days(inv, base.as_of)]
        share = Decimal(sum(1 for d in days if d >= breach)) / len(days) if days else Decimal(1)
        if owed * share > 0:
            found.append((inv, owed * share, days))
    found.sort(key=lambda item: (-item[1], item[0].id))
    return [(inv, late, days) for inv, late, days in found[:CANDIDATE_INVOICES]]


def _advance(ctx: LeverContext, gap: Gap) -> list[_Offer]:
    base = ctx.sim.baseline
    owed_of = dict((inv.id, owed) for inv, owed in base.open_invoices)
    offers = []
    for inv, _late, _days in _late_invoices(ctx, gap):
        owed = owed_of[inv.id]
        half = _q(owed * ADVANCE_SHARE)
        offers.append(_Offer(
            LeverKind.request_advance, f"advance:{inv.id}",
            Scenario(name=f"advance:{inv.id}", invoice_changes={
                inv.id: InvoiceChange(receipts=((ctx.soon, half),), remainder=owed - half)}),
            ZERO, "action.request_advance", ActionType.request_advance, Tier.EXECUTE,
            {"invoice_id": inv.id, "counterparty_token": inv.counterparty_token,
             "amount": half, "by_date": ctx.soon, "invoice_outstanding": owed},
            (f"inv:{inv.id}",), {"rule": "half now, the rest as usual"}))
    return offers


def _loan_below(ctx: LeverContext, amount: Decimal, tenor_days: int, ceiling: Decimal
                ) -> tuple[bool, Decimal | None]:
    """(an eligible loan costs less than `ceiling` % a year?, the cheapest such rate seen).
    Loans are priced in order of nominal rate and the search stops at the first one below
    the ceiling: a loan's effective rate is never below its nominal rate, so the answer is
    exact without pricing the whole catalogue."""
    money = Money.of(amount)
    loans = sorted((p for p in ctx.products if p.kind.is_loan
                    and evaluate(p, ctx.facts, money, tenor_days).status
                    is not EligibilityStatus.fail), key=lambda p: (p.nominal_rate_pa, p.id))
    cheapest = None
    for product in loans:
        if cheapest is not None and product.nominal_rate_pa >= cheapest:
            break
        rate = true_cost(product, money, tenor_days).effective_annual_rate
        cheapest = rate if cheapest is None else min(cheapest, rate)
        if rate < ceiling:
            return True, rate
    return False, cheapest


def _early_pay(ctx: LeverContext, gap: Gap) -> list[_Offer]:
    if not ctx.products:
        return []  # without a catalogue we cannot show the discount is cheaper than borrowing
    base = ctx.sim.baseline
    owed_of = dict((inv.id, owed) for inv, owed in base.open_invoices)
    offers = []
    for inv, _late, days in _late_invoices(ctx, gap):
        if not days:
            continue  # later than ever: no usual payment day to bring forward
        usual = sorted(days)[(len(days) - 1) // 2]
        days_early = (usual - ctx.soon).days
        if days_early <= 0:
            continue
        owed = owed_of[inv.id]
        discount = _q(owed * DISCOUNT_PERCENT / 100)
        ear = early_pay_discount_cost(DISCOUNT_PERCENT, days_early)
        cheaper_loan, loan = _loan_below(ctx, owed - discount, days_early, ear)
        if cheaper_loan:
            continue
        reason = "lever.early_pay.cheaper_than_borrowing" if loan is not None \
            else "lever.early_pay.no_eligible_loan"
        offers.append(_Offer(
            LeverKind.early_pay_discount, f"early_pay:{inv.id}",
            Scenario(name=f"early_pay:{inv.id}", invoice_changes={
                inv.id: InvoiceChange(receipts=((ctx.soon, owed - discount),))}),
            discount, "action.offer_early_pay_discount", ActionType.offer_early_pay_discount,
            Tier.EXECUTE,
            {"invoice_id": inv.id, "counterparty_token": inv.counterparty_token,
             "discount_percent": DISCOUNT_PERCENT, "discount": discount,
             "pay_by": ctx.soon, "usual_pay_date": usual, "days_early": days_early,
             "effective_annual_cost_percent": ear,
             "cheapest_loan_percent": loan if loan is not None else "none",
             "reason_key": reason},
            (f"inv:{inv.id}",),
            {"discount_percent": DISCOUNT_PERCENT, "invoice_outstanding": owed,
             "effective_annual_cost_percent": ear}))
    return offers


def _netting(ctx: LeverContext, gap: Gap) -> list[_Offer]:
    base = ctx.sim.baseline
    tenant = base.tenant_id
    if not ctx.mesh:
        return []
    graph = build_graph(ctx.mesh)
    rounds = [r for r in propose_rounds(graph, now=ctx.now, data_mode=base.data_mode)
              if tenant in r.participants]
    if not rounds:
        return []
    round_ = rounds[0]
    bills = {ob.bill.id: ob.owed for ob in base.open_bills}
    invoices = dict((inv.id, owed) for inv, owed in base.open_invoices)
    bill_payments: dict[str, tuple] = {}
    invoice_changes: dict[str, InvoiceChange] = {}
    for oid in round_.obligation_ids:
        ob = graph.obligations[oid]
        doc = f"{tenant}:{ob.invoice_ref or ob.id}"
        if ob.debtor_tenant == tenant:
            if bills.get(doc) != ob.amount.amount:
                return []  # the ledger does not show this debt as open: never net blind
            bill_payments[doc] = ()
        elif ob.creditor_tenant == tenant:
            if invoices.get(doc) != ob.amount.amount:
                return []
            invoice_changes[doc] = InvoiceChange()
    flows = tuple((ctx.soon, s.amount.amount if s.payee_tenant == tenant else -s.amount.amount)
                  for s in round_.settlements if tenant in (s.payer_tenant, s.payee_tenant))
    pays = sum((-a for _d, a in flows if a < 0), ZERO)
    gets = sum((a for _d, a in flows if a > 0), ZERO)
    return [_Offer(
        LeverKind.netting, f"netting:{round_.id}",
        Scenario(name=f"netting:{round_.id}", flows=flows, bill_payments=bill_payments,
                 invoice_changes=invoice_changes),
        ZERO, "action.propose_netting_round", ActionType.propose_netting_round, Tier.DRAFT,
        {"round_id": round_.id, "participants": list(round_.participants),
         "obligation_ids": list(round_.obligation_ids), "gross_total": round_.gross_total.amount,
         "net_total": round_.net_total.amount, "you_pay": pays, "you_receive": gets,
         "settle_by": ctx.soon},
        tuple([*(f"bill:{d}" for d in bill_payments), *(f"inv:{d}" for d in invoice_changes)]),
        {"rule": "net positions unchanged (WP-08)"})]


def cover_amount(sim: Simulation, gap: Gap) -> Decimal:
    """Shortfall covered in 19 of 20 paths, rounded up to Tk 1,000 (0 when none)."""
    lows = sim.balances[:, gap.first - 1:gap.last].min(axis=1)
    short = np.sort(np.maximum(to_paisa(gap.buffer) - lows, 0))
    paisa = int(short[rank(sim.paths, STANDBY_COVER_PERCENT) - 1])
    taka = Decimal(paisa) / PAISA
    return (taka / ROUND_TO).to_integral_value(rounding=ROUND_CEILING) * ROUND_TO


def _standby(ctx: LeverContext, gap: Gap) -> list[_Offer]:
    if not ctx.products:
        return []
    base = ctx.sim.baseline
    amount = cover_amount(ctx.sim, gap)
    if amount <= 0:
        return []
    need = FinancingNeed(tenant_id=base.tenant_id, amount=Money.of(amount),
                         needed_by=gap.gap.first_breach_day, tenor_days=STANDBY_TENOR_DAYS)
    loans = [p for p in ctx.products if p.kind.is_loan]
    ranked = [c for c in match(need, loans, ctx.facts, start=ctx.soon, lenders=ctx.lenders)
              if c.option.eligibility.status is not EligibilityStatus.fail]
    if not ranked:
        return []

    def ready(candidate: Any) -> date:
        return base.as_of + timedelta(days=max(SPEED_DAYS[candidate.option.product.kind], 1))

    eve = gap.gap.first_breach_day - timedelta(days=1)
    best = next((c for c in ranked if ready(c) <= eve), ranked[0])  # in time, if any can be
    product = best.option.product
    draw = max(ready(best), eve)
    amounts = [_q(f.amount) for f in best.cost.flows]
    amounts[-1] += -best.cost.total_cost.amount - sum(amounts, ZERO)  # whole paisa, same total
    flows = tuple((draw + timedelta(days=int(f.day.to_integral_value(rounding=ROUND_HALF_UP))),
                   amount) for f, amount in zip(best.cost.flows, amounts, strict=True))
    return [_Offer(
        LeverKind.standby_facility, f"standby:{product.id}",
        Scenario(name=f"standby:{product.id}", flows=flows), best.cost.total_cost.amount,
        "action.standby_facility", ActionType.draft_loan_application, Tier.DRAFT,
        {"product_id": product.id, "provider": product.provider, "product_name": product.name,
         "amount": amount, "tenor_days": STANDBY_TENOR_DAYS, "draw_on": draw,
         "needed_by": gap.gap.first_breach_day,
         "effective_annual_rate_percent": best.option.effective_apr,
         "eligibility": best.option.eligibility.status.value},
        (), {"product_id": product.id, "principal": amount, "tenor_days": STANDBY_TENOR_DAYS,
             "effective_annual_rate_percent": best.option.effective_apr},
        best.option.figures)]


BUILDERS = (_retime, _stagger, _advance, _early_pay, _netting, _standby)


def smoothing_levers(ctx: LeverContext, gap: Gap) -> tuple[Lever, ...]:
    """Every lever that reduces `gap`, cheapest first, then the larger reduction first."""
    found = [lever for build in BUILDERS for offer in build(ctx, gap)
             if (lever := _measure(ctx, gap, offer)) is not None]
    found.sort(key=lambda lv: (lv.lever.cost.amount, -lv.lever.gap_reduction.amount,
                               _KIND_ORDER[lv.lever.kind], lv.lever.action.id))
    return tuple(found)
