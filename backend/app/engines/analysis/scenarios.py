"""Scenarios: candidate decisions compared under uncertainty (WP-07 milestone 4; FEATURES N12).

The world: WP-04's Monte Carlo paths (the shop's own sales noise, customer lateness, spending
and billing replayed from its history) are split into `STATES` (40) equal groups, and each
group lives in one macro state, drawn by seeded Latin hypercube sampling:

  sales            a level shift for the whole horizon, normal with sd `sales_sd_pct` (8%)
  input prices     purchases and running costs, normal with sd `input_price_sd_pct` (5%)
  collection delay every customer pays 0, 7 or 14 days later (70% / 20% / 10% of states)
  interest rates   up 0 to `rate_pp_max` (2) points: reprices the loan a decision takes
  shock            in `shock_probability_pct` (10%) of states a one-off bill of
                   `shock_share_pct` (50%) of a month of fixed obligations (10% of a month of
                   outflows without any), on a random day

Every decision is replayed on the same paths in the same states (common random numbers): the
difference between two decisions is the decision, never luck. A path's outcome is its balance
at the end of the horizon plus what the decision still pays or receives after it (a loan's
remaining instalments). Per decision:

  expected outcome    mean outcome
  worst 5% outcome    mean of the worst 5% of outcomes (so never above the expected one)
  P(buffer breach)    share of paths below the buffer on at least one day

Recommendation, risk-adjusted: among the decisions whose P(breach) is within 5 points of the
lowest, the one with the highest (expected + worst 5%) / 2; ties go to the cheaper decision,
then to menu order.

The menu (`decision.<name>` on screen):
  do_nothing
  take_loan        the best-ranked eligible WP-06 loan for the shortfall that keeps the buffer
                   in 19 of 20 plain paths (rounded up to Tk 1,000), 90 days, drawn as soon as
                   it can pay out. Skipped when there is no shortfall
  offer_discount   2% off the open invoice with the most cash expected after 2 days, paid in 2
  retime_supplier  every open bill the business usually pays early is paid on its due date
  delay_purchase   half of the purchases of the next 14 days (cash and credit) a week later
  net_via_mesh     the WP-08 netting round the business is in, settled in 2 days (the same
                   ledger check as WP-04's netting lever: never net a debt the ledger lacks)

A decision that does not apply is skipped with a reason key ('scenario.skip.<reason>').
`Shift` adds a change to every state; the stability score (N16) uses it for stress tests.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from itertools import accumulate
from statistics import NormalDist

import numpy as np

from app.contracts import (
    Direction,
    EligibilityStatus,
    Figure,
    FinancingNeed,
    FinancingProduct,
    Granularity,
    LenderProfile,
    MeshObligation,
    Money,
    Period,
    RateType,
    Scenario,
    Unit,
)
from app.engines.analysis.figures import make_figure
from app.engines.analysis.ledger import Ledger, NotEnoughData
from app.engines.cash.baseline import Baseline, FlowKind, forecast_baseline
from app.engines.cash.calendar import Festival
from app.engines.cash.levers import combine
from app.engines.cash.simulate import PATHS, SEED, Draws, InvoiceChange, draw, rank, run, to_paisa
from app.engines.cash.simulate import Scenario as CashScenario
from app.engines.financing.cost import build_flows
from app.engines.financing.ranking import SPEED_DAYS, match
from app.engines.mesh.graph import build_graph
from app.engines.mesh.netting import propose_rounds

ZERO, HUNDRED = Decimal(0), Decimal(100)
CENT, BP = Decimal("0.01"), Decimal("0.0001")
STATES = 40
SOON_DAYS = 2
DISCOUNT_PERCENT = Decimal(2)
LOAN_TENOR_DAYS = 90
COVER_PERCENT = 95
ROUND_TO = Decimal(1000)
DEFER_WINDOW_DAYS, DEFER_DAYS, DEFER_PERCENT = 14, 7, Decimal(50)
WORST_PERCENT = 5
BREACH_TOLERANCE = Decimal("0.05")
NO_OBLIGATION_SHOCK_SHARE = Decimal("0.10")
MENU = ("do_nothing", "take_loan", "offer_discount", "retime_supplier", "delay_purchase",
        "net_via_mesh")
_MONTHLY = {"weekly": Decimal(52) / 12, "monthly": Decimal(1), "quarterly": Decimal(1) / 3,
            "yearly": Decimal(1) / 12}


@dataclass(frozen=True)
class Assumptions:
    """How uncertain the world is. Percent are percent (Decimal(8) = 8%)."""

    sales_sd_pct: Decimal = Decimal(8)
    input_price_sd_pct: Decimal = Decimal(5)
    delay_days: tuple[int, ...] = (0, 7, 14)
    delay_weights_pct: tuple[int, ...] = (70, 20, 10)
    rate_pp_max: Decimal = Decimal(2)
    shock_probability_pct: Decimal = Decimal(10)
    shock_share_pct: Decimal = Decimal(50)

    def __post_init__(self) -> None:
        if not (ZERO <= self.sales_sd_pct <= 40 and ZERO <= self.input_price_sd_pct <= 40):
            raise ValueError("standard deviations must be between 0 and 40 percent")
        if len(self.delay_days) != len(self.delay_weights_pct) or not self.delay_days or \
                sum(self.delay_weights_pct) != 100 or min(self.delay_weights_pct) < 0 or \
                not all(0 <= d <= 120 for d in self.delay_days):
            raise ValueError("delay_days need weights summing to 100, delays 0-120 days")
        if not ZERO <= self.rate_pp_max <= 10:
            raise ValueError("rate_pp_max must be between 0 and 10 points")
        if not (ZERO <= self.shock_probability_pct <= 100 and
                ZERO <= self.shock_share_pct <= 500):
            raise ValueError("shock probability 0-100 percent, size 0-500 percent")

    def as_dict(self) -> dict[str, Decimal]:
        out = {"sales_sd_pct": self.sales_sd_pct,
               "input_price_sd_pct": self.input_price_sd_pct, "rate_pp_max": self.rate_pp_max,
               "shock_probability_pct": self.shock_probability_pct,
               "shock_share_pct": self.shock_share_pct}
        for days, weight in zip(self.delay_days, self.delay_weights_pct, strict=True):
            out[f"delay_{days}_days_pct"] = Decimal(weight)
        return out


@dataclass(frozen=True)
class Shift:
    """One change applied in every state (a stress test)."""

    name: str = "none"
    sales_change_pct: Decimal = ZERO
    cost_change_pct: Decimal = ZERO
    rate_pp: Decimal = ZERO
    flows: tuple[tuple[date, Decimal], ...] = ()
    invoice_changes: Mapping[str, InvoiceChange] = field(default_factory=dict)


NO_SHIFT = Shift()


@dataclass(frozen=True)
class MacroState:
    sales_change_pct: Decimal
    cost_change_pct: Decimal
    delay_days: int
    rate_pp: Decimal
    shock_day: date | None
    shock_amount: Decimal


@dataclass(frozen=True)
class ScenarioInputs:
    """One tenant's forecast and everything a decision may consult (all from the caller)."""

    ledger: Ledger
    baseline: Baseline
    draws: Draws
    buffer: Decimal
    now: datetime
    products: Sequence[FinancingProduct] = ()
    facts: Mapping[str, Decimal | None] = field(default_factory=dict)
    lenders: Mapping[str, LenderProfile] = field(default_factory=dict)
    mesh: Sequence[MeshObligation] = ()

    @property
    def as_of(self) -> date:
        return self.baseline.as_of

    @property
    def soon(self) -> date:
        return self.as_of + timedelta(days=SOON_DAYS)

    @property
    def horizon(self) -> Period:
        days = self.baseline.days
        return Period(start=days[0], end=days[-1], granularity=Granularity.day)


def prepare(ledger: Ledger, festivals: Sequence[Festival], buffer: Decimal, now: datetime,
            seed: int = SEED, paths: int = PATHS, *,
            products: Sequence[FinancingProduct] = (),
            facts: Mapping[str, Decimal | None] | None = None,
            lenders: Mapping[str, LenderProfile] | None = None,
            mesh: Sequence[MeshObligation] = ()) -> ScenarioInputs:
    """WP-04's baseline and draws from the day after the ledger's last transaction. Party
    names and row order never change a draw (WP-04 breaks ties on record ids), which the
    stability score's noise variations check on every recommendation."""
    as_of = ledger.as_of
    opening, _rows = ledger.cash_at_start(as_of + timedelta(days=1))
    baseline = forecast_baseline(ledger.tenant_id, as_of, opening, ledger.transactions,
                                 ledger.invoices, ledger.bills, ledger.obligations, festivals)
    return ScenarioInputs(ledger=ledger, baseline=baseline, draws=draw(baseline, seed, paths),
                          buffer=buffer, now=now, products=tuple(products),
                          facts=dict(facts or {}), lenders=dict(lenders or {}),
                          mesh=tuple(mesh))


# ---------------------------------------------------------------- the world


def shock_size(inputs: ScenarioInputs, assumptions: Assumptions) -> Decimal:
    """A share of a month of fixed obligations (or of a month of outflows without any)."""
    base = inputs.baseline
    monthly = sum((o.amount.amount * _MONTHLY[o.frequency.value] for o in base.obligations),
                  ZERO)
    if monthly > 0:
        size = monthly * assumptions.shock_share_pct / HUNDRED
    else:
        spent = sum((f.amount for f in base.flows if f.direction is Direction.outflow), ZERO)
        size = spent / Decimal(base.horizon) * 30 * NO_OBLIGATION_SHOCK_SHARE
    return size.quantize(CENT, ROUND_HALF_UP)


def macro_states(inputs: ScenarioInputs, assumptions: Assumptions, count: int = STATES
                 ) -> tuple[MacroState, ...]:
    """`count` states from the draws' seed by Latin hypercube sampling (integers only)."""
    rng = np.random.Generator(np.random.PCG64(
        np.random.SeedSequence(inputs.draws.seed, spawn_key=(7001,))))
    perms = [rng.permutation(count) for _ in range(5)]
    shock_days = rng.integers(1, inputs.baseline.horizon + 1, size=count)
    amount = shock_size(inputs, assumptions)
    normal = NormalDist()

    def z(k: int, factor: int) -> Decimal:
        u = (2 * int(perms[factor][k]) + 1) / (2 * count)
        return Decimal(str(round(normal.inv_cdf(u), 4)))

    def pct(k: int, factor: int) -> Decimal:  # the state's stratum midpoint, in percent
        return Decimal(2 * int(perms[factor][k]) + 1) * HUNDRED / Decimal(2 * count)

    cumulative = list(accumulate(assumptions.delay_weights_pct))
    states = []
    for k in range(count):
        delay_at = pct(k, 2)
        delay = next(d for d, top in zip(assumptions.delay_days, cumulative, strict=True)
                     if delay_at < top)
        shocked = pct(k, 4) < assumptions.shock_probability_pct
        states.append(MacroState(
            sales_change_pct=max(Decimal(-90), (assumptions.sales_sd_pct * z(k, 0))
                                 .quantize(CENT, ROUND_HALF_UP)),
            cost_change_pct=max(Decimal(-90), (assumptions.input_price_sd_pct * z(k, 1))
                                .quantize(CENT, ROUND_HALF_UP)),
            delay_days=delay,
            rate_pp=(assumptions.rate_pp_max * pct(k, 3) / HUNDRED).quantize(CENT,
                                                                             ROUND_HALF_UP),
            shock_day=inputs.as_of + timedelta(days=int(shock_days[k])) if shocked else None,
            shock_amount=amount if shocked else ZERO))
    return tuple(states)


# ---------------------------------------------------------------- decisions


@dataclass(frozen=True)
class Decision:
    name: str
    cost: Decimal  # at today's rates
    change: Callable[[Decimal], CashScenario]  # rate change (points) -> the decision's changes
    after_horizon: Callable[[Decimal], Decimal]  # rate change -> signed amount due after it
    params: Mapping[str, Decimal] = field(default_factory=dict)
    details: Mapping[str, str] = field(default_factory=dict)
    rows: tuple[str, ...] = ()


class Skip(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason_key = f"scenario.skip.{reason}"


def _fixed(name: str, change: CashScenario, cost: Decimal = ZERO,
           params: Mapping[str, Decimal] | None = None, details: Mapping[str, str] | None = None,
           rows: Sequence[str] = ()) -> Decision:
    return Decision(name=name, cost=cost, change=lambda _rate: change,
                    after_horizon=lambda _rate: ZERO, params=params or {},
                    details=details or {}, rows=tuple(rows))


def _do_nothing(_inputs: ScenarioInputs) -> Decision:
    return _fixed("do_nothing", CashScenario(name="do_nothing"))


def cover_amount(inputs: ScenarioInputs) -> Decimal:
    """The shortfall below the buffer in 19 of 20 plain paths, rounded up to Tk 1,000."""
    plain = run(inputs.baseline, inputs.draws)
    lows = plain.balances.min(axis=1)
    short = np.sort(np.maximum(to_paisa(inputs.buffer) - lows, 0))
    taka = Decimal(int(short[rank(plain.paths, COVER_PERCENT) - 1])) / HUNDRED
    return (taka / ROUND_TO).to_integral_value(rounding=ROUND_CEILING) * ROUND_TO


def _take_loan(inputs: ScenarioInputs) -> Decision:
    amount = cover_amount(inputs)
    if amount <= 0:
        raise Skip("no_shortfall")
    loans = [p for p in inputs.products if p.kind.is_loan]
    if not loans:
        raise Skip("no_catalogue")
    need = FinancingNeed(tenant_id=inputs.ledger.tenant_id, amount=Money.of(amount),
                         needed_by=inputs.soon, tenor_days=LOAN_TENOR_DAYS)
    ranked = [c for c in match(need, loans, inputs.facts, start=inputs.soon,
                               lenders=inputs.lenders)
              if c.option.eligibility.status is not EligibilityStatus.fail]
    if not ranked:
        raise Skip("no_eligible_loan")
    best = ranked[0]
    product = best.option.product
    paid_out = inputs.as_of + timedelta(days=max(SPEED_DAYS[product.kind], 1))
    end = inputs.horizon.end

    def flows(rate_pp: Decimal) -> tuple[tuple[date, Decimal], ...]:
        priced = product if rate_pp == 0 or product.rate_type is RateType.none else \
            product.model_copy(update={"nominal_rate_pa": product.nominal_rate_pa + rate_pp})
        raw = build_flows(priced, amount, LOAN_TENOR_DAYS)
        return tuple((paid_out + timedelta(days=int(f.day.to_integral_value(ROUND_HALF_UP))),
                      f.amount.quantize(CENT, ROUND_HALF_UP)) for f in raw)

    cost = -sum((a for _d, a in flows(ZERO)), ZERO)
    return Decision(
        name="take_loan", cost=cost,
        change=lambda rate: CashScenario(name="take_loan", flows=flows(rate)),
        after_horizon=lambda rate: sum((a for d, a in flows(rate) if d > end), ZERO),
        params={"loan_amount": amount, "tenor_days": Decimal(LOAN_TENOR_DAYS),
                "nominal_rate_pa": product.nominal_rate_pa,
                "effective_annual_rate_pct": best.option.effective_apr},
        details={"product_id": product.id, "provider": product.provider,
                 "paid_out_on": paid_out.isoformat()})


def _offer_discount(inputs: ScenarioInputs) -> Decision:
    base, soon = inputs.baseline, inputs.soon
    found = []
    for inv, owed in base.open_invoices:
        days = base.invoice_delays.possible_days(inv, base.as_of)
        if not days:
            continue  # later than ever before: no usual day to bring forward
        late = owed * Decimal(sum(1 for d in days if d > soon)) / Decimal(len(days))
        if late > 0:
            found.append((late, inv, owed))
    if not found:
        raise Skip("no_open_invoice")
    _late, inv, owed = min(found, key=lambda item: (-item[0], item[1].id))
    discount = (owed * DISCOUNT_PERCENT / HUNDRED).quantize(CENT, ROUND_HALF_UP)
    return _fixed("offer_discount", CashScenario(name="offer_discount", invoice_changes={
        inv.id: InvoiceChange(receipts=((soon, owed - discount),))}), discount,
        {"discount_pct": DISCOUNT_PERCENT, "invoice_outstanding": owed},
        {"invoice_id": inv.id, "counterparty_token": inv.counterparty_token,
         "pay_by": soon.isoformat()}, (f"inv:{inv.id}",))


def _retime_supplier(inputs: ScenarioInputs) -> Decision:
    early = sorted((ob for ob in inputs.baseline.open_bills if ob.pay_day < ob.bill.due_date),
                   key=lambda ob: ob.bill.id)
    if not early:
        raise Skip("no_early_bills")
    return _fixed("retime_supplier", CashScenario(name="retime_supplier", bill_payments={
        ob.bill.id: ((ob.bill.due_date, ob.owed),) for ob in early}), ZERO,
        {"bills": Decimal(len(early)), "amount": sum((ob.owed for ob in early), ZERO)},
        {"bill_ids": ",".join(ob.bill.id for ob in early)},
        tuple(f"bill:{ob.bill.id}" for ob in early))


def _delay_purchase(inputs: ScenarioInputs) -> Decision:
    base = inputs.baseline
    if not any(base.history(FlowKind.purchases)) and not any(base.history(FlowKind.new_bills)):
        raise Skip("no_purchases")
    first = base.as_of + timedelta(days=1)
    last = base.as_of + timedelta(days=DEFER_WINDOW_DAYS)
    return _fixed("delay_purchase", CashScenario(
        name="delay_purchase", defer_purchases=((first, last, DEFER_PERCENT, DEFER_DAYS),)),
        ZERO, {"share_pct": DEFER_PERCENT, "days_later": Decimal(DEFER_DAYS),
               "window_days": Decimal(DEFER_WINDOW_DAYS)})


def _net_via_mesh(inputs: ScenarioInputs) -> Decision:
    tenant = inputs.ledger.tenant_id
    if not inputs.mesh:
        raise Skip("no_mesh")
    graph = build_graph(inputs.mesh)
    rounds = [r for r in propose_rounds(graph, now=inputs.now,
                                        data_mode=inputs.baseline.data_mode)
              if tenant in r.participants]
    if not rounds:
        raise Skip("no_netting_round")
    round_ = rounds[0]
    bills = {ob.bill.id: ob.owed for ob in inputs.baseline.open_bills}
    invoices = dict((inv.id, owed) for inv, owed in inputs.baseline.open_invoices)
    bill_payments: dict[str, tuple] = {}
    invoice_changes: dict[str, InvoiceChange] = {}
    for oid in round_.obligation_ids:
        ob = graph.obligations[oid]
        doc = f"{tenant}:{ob.invoice_ref or ob.id}"
        if ob.debtor_tenant == tenant:
            if bills.get(doc) != ob.amount.amount:
                raise Skip("netting_not_on_ledger")
            bill_payments[doc] = ()
        elif ob.creditor_tenant == tenant:
            if invoices.get(doc) != ob.amount.amount:
                raise Skip("netting_not_on_ledger")
            invoice_changes[doc] = InvoiceChange()
    flows = tuple((inputs.soon, s.amount.amount if s.payee_tenant == tenant
                   else -s.amount.amount)
                  for s in round_.settlements if tenant in (s.payer_tenant, s.payee_tenant))
    return _fixed("net_via_mesh", CashScenario(name="net_via_mesh", flows=flows,
                                               bill_payments=bill_payments,
                                               invoice_changes=invoice_changes), ZERO,
                  {"gross_total": round_.gross_total.amount,
                   "net_total": round_.net_total.amount},
                  {"round_id": round_.id},
                  tuple([*(f"bill:{d}" for d in bill_payments),
                         *(f"inv:{d}" for d in invoice_changes)]))


BUILDERS: dict[str, Callable[[ScenarioInputs], Decision]] = {
    "do_nothing": _do_nothing, "take_loan": _take_loan, "offer_discount": _offer_discount,
    "retime_supplier": _retime_supplier, "delay_purchase": _delay_purchase,
    "net_via_mesh": _net_via_mesh,
}


def build_decisions(inputs: ScenarioInputs, names: Sequence[str]
                    ) -> tuple[list[Decision], list[tuple[str, str]]]:
    """(decisions that apply, (name, reason key) for those that do not), in menu order."""
    unknown = sorted(set(names) - set(MENU))
    if unknown:
        raise ValueError(f"unknown decisions {unknown}; choose from {list(MENU)}")
    built, skipped = [], []
    for name in MENU:
        if name not in names:
            continue
        try:
            built.append(BUILDERS[name](inputs))
        except Skip as exc:
            skipped.append((name, exc.reason_key))
    return built, skipped


# ---------------------------------------------------------------- simulation


def slices(draws: Draws, count: int) -> list[Draws]:
    """The draws cut into `count` equal groups of paths, one per macro state."""
    if draws.paths % count:
        raise ValueError(f"{draws.paths} paths do not split into {count} equal groups")
    size = draws.paths // count
    arrays = ("sales_ratio", "invoice_day", "new_invoice", "new_invoice_delay", "new_bill",
              "new_bill_delay", "purchase", "running")
    return [replace(draws, paths=size, **{a: getattr(draws, a)[k * size:(k + 1) * size]
                                          for a in arrays}) for k in range(count)]


def _world(state: MacroState, shift: Shift) -> CashScenario:
    flows = ((state.shock_day, -state.shock_amount),) if state.shock_day else ()
    return CashScenario(
        name="world",
        sales_change_pct=max(Decimal(-95), state.sales_change_pct + shift.sales_change_pct),
        cost_change_pct=max(Decimal(-95), state.cost_change_pct + shift.cost_change_pct),
        collection_delay_days=state.delay_days, flows=flows + shift.flows,
        invoice_changes=dict(shift.invoice_changes))


@dataclass(frozen=True)
class Outcome:
    decision: Decision
    scenario: Scenario
    risk_adjusted: Decimal
    figures: tuple[Figure, ...]  # expected, worst 5%, P(breach), risk-adjusted, cost


@dataclass(frozen=True)
class Comparison:
    outcomes: tuple[Outcome, ...]
    recommended_id: str
    reason_keys: tuple[str, ...]
    skipped: tuple[tuple[str, str], ...]
    states: tuple[MacroState, ...]
    buffer: Decimal
    shift: Shift

    @property
    def scenarios(self) -> tuple[Scenario, ...]:
        return tuple(o.scenario for o in self.outcomes)

    @property
    def choice(self) -> str:
        """The recommended decision's name."""
        return next(o.decision.name for o in self.outcomes
                    if o.scenario.id == self.recommended_id)

    def outcome(self, name: str) -> Outcome:
        return next(o for o in self.outcomes if o.decision.name == name)


def _money(paisa: int | np.integer, count: int) -> Decimal:
    return (Decimal(int(paisa)) / Decimal(count) / HUNDRED).quantize(CENT, ROUND_HALF_UP)


def _simulate(inputs: ScenarioInputs, groups: Sequence[Draws], states: Sequence[MacroState],
              decision: Decision, shift: Shift) -> tuple[np.ndarray, np.ndarray]:
    """(outcome, lowest balance) per path, in paisa."""
    ends, lows = [], []
    for group, state in zip(groups, states, strict=True):
        rate = state.rate_pp + shift.rate_pp
        sim = run(inputs.baseline, group, combine(_world(state, shift), decision.change(rate)))
        ends.append(sim.balances[:, -1] + to_paisa(decision.after_horizon(rate)))
        lows.append(sim.balances.min(axis=1))
    return np.concatenate(ends), np.concatenate(lows)


def compare_decisions(inputs: ScenarioInputs, names: Sequence[str] = MENU,
                      assumptions: Assumptions = Assumptions(), shift: Shift = NO_SHIFT,
                      states: int = STATES) -> Comparison:
    """Every applicable decision in `names` simulated and the risk-adjusted best named."""
    decisions, skipped = build_decisions(inputs, names)
    if not decisions:
        raise NotEnoughData("a decision that applies to this business: "
                            + ", ".join(f"{n} ({r})" for n, r in skipped))
    world = macro_states(inputs, assumptions, states)
    groups = slices(inputs.draws, states)
    paths = inputs.draws.paths
    worst_n = rank(paths, WORST_PERCENT)
    buffer_paisa = to_paisa(inputs.buffer)
    ledger, horizon = inputs.ledger, inputs.horizon
    measured = []
    for order, decision in enumerate(decisions):
        ends, lows = _simulate(inputs, groups, world, decision, shift)
        expected = _money(ends.sum(), paths)
        worst = _money(np.sort(ends)[:worst_n].sum(), worst_n)
        breach = (Decimal(int((lows < buffer_paisa).sum())) / Decimal(paths)).quantize(BP)
        measured.append((order, decision, expected, worst, breach))

    outcomes = []
    for order, decision, expected, worst, breach in measured:
        assumptions_used = {**assumptions.as_dict(), **decision.params, "buffer": inputs.buffer,
                            "horizon_days": Decimal(inputs.baseline.horizon),
                            "states": Decimal(states)}
        if shift is not NO_SHIFT:
            assumptions_used.update({"shift_sales_pct": shift.sales_change_pct,
                                     "shift_cost_pct": shift.cost_change_pct,
                                     "shift_rate_pp": shift.rate_pp})
        scenario = Scenario(
            id=f"sc_{decision.name}", name_key=f"decision.{decision.name}",
            assumptions=assumptions_used, expected_outcome=Money.of(expected),
            worst_5pct_outcome=Money.of(worst), p_buffer_breach=breach, paths=paths,
            seed=inputs.draws.seed)
        risk = ((expected + worst) / 2).quantize(CENT, ROUND_HALF_UP)
        params = {"decision": decision.name, "seed": inputs.draws.seed, "paths": paths,
                  "states": states, "buffer": inputs.buffer, "shift": shift.name,
                  "assumptions": _digest(assumptions_used),
                  **{f"detail.{k}": v for k, v in decision.details.items()}}

        def fig(formula: str, label: str, value: Decimal, unit: Unit = Unit.BDT,
                *, _d: Decision = decision, _p: Mapping[str, object] = params) -> Figure:
            return make_figure(ledger.tenant_id, inputs.baseline.data_mode,
                               f"analysis.scenario.{formula}", label, value, unit, horizon,
                               inputs=(ledger.anchor,), rows=_d.rows, params=_p)

        figures = (fig("expected_outcome", "analysis.expected_outcome", expected),
                   fig("worst_5pct_outcome", "analysis.worst_5pct_outcome", worst),
                   fig("p_buffer_breach", "analysis.p_buffer_breach", breach, Unit.probability),
                   fig("risk_adjusted", "analysis.risk_adjusted_outcome", risk),
                   fig("cost", "analysis.decision_cost", decision.cost))
        outcomes.append((order, Outcome(decision=decision, scenario=scenario,
                                        risk_adjusted=risk, figures=figures)))

    best, reasons = choose([(o.scenario.p_buffer_breach, o.risk_adjusted, o.decision.cost)
                            for _n, o in outcomes])
    return Comparison(outcomes=tuple(o for _n, o in outcomes),
                      recommended_id=outcomes[best][1].scenario.id, reason_keys=reasons,
                      skipped=tuple(skipped), states=world, buffer=inputs.buffer, shift=shift)


def choose(rows: Sequence[tuple[Decimal, Decimal, Decimal]]) -> tuple[int, tuple[str, ...]]:
    """The risk-adjusted best of (P(breach), risk-adjusted outcome, cost) rows, in menu order:
    the highest risk-adjusted outcome among rows within `BREACH_TOLERANCE` of the lowest
    P(breach); ties go to the cheaper row, then the earlier one. Returns (index, reasons)."""
    floor = min(p for p, _r, _c in rows)
    safe = [n for n, (p, _r, _c) in enumerate(rows) if p <= floor + BREACH_TOLERANCE]
    best = min(safe, key=lambda n: (-rows[n][1], rows[n][2], n))
    return best, ("scenario.reason.lowest_breach_risk" if rows[best][0] == floor
                  else "scenario.reason.breach_risk_within_tolerance",
                  "scenario.reason.best_risk_adjusted_outcome")


def _digest(values: Mapping[str, Decimal]) -> str:
    text = json.dumps({k: str(v) for k, v in sorted(values.items())})
    return hashlib.sha256(text.encode()).hexdigest()[:16]
