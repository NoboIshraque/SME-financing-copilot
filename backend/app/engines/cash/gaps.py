"""Cash gaps and leading indicators (WP-04 milestone 3; FEATURES Q3).

Gaps come from the Monte Carlo paths (`simulate.py`):
  risk day      a day on which more than 1 path in 20 ends below the buffer
  gap           a run of consecutive risk days in which more than 20% of paths dip below the
                buffer (20% is the lowest alert trigger, FEATURES Q1)
  first breach  the first day of the run by which more than 20% of paths have dipped
  worst day     the lowest likely (P50) balance from the first breach to the end of the run
  probability   share of paths below the buffer on at least one day of the run
  shortfall     expected shortfall: mean over all paths of max(0, buffer - lowest balance in
                the run), in Tk (a path that never dips counts as 0)
  lead time     first breach - as_of, in days
  drivers       the three largest reasons, in Tk: obligations and supplier bills paid between
                the last high point before the gap (highest P50 balance from as_of to the
                breach) and the worst day; customers whose invoices are due by the worst day but
                whose own history says they pay after it (or not at all: later than ever
                before), and disputed invoices; sales below their normal weekday level in that
                stretch; for a what-if, its sales drop and one-off costs.

Leading indicators fire from the ledger before the forecast crosses anything. Each reads only
rows dated on or before as_of, and each threshold is a named constant:
  dso_rising               30-day DSO up by at least 20% and 5 days on the 30 days before
  top_customer_slowing     one of the 3 biggest credit customers (last 90 days) pays 5+ days
                           later than they used to (median, last 60 days vs before), or has an
                           invoice overdue longer than they have ever paid late
  stock_building           purchases / sales over 30 days at least 1.25 x the 150 days before
  sales_below_seasonal_norm  sales over the last 14 days below 85% of what the seasonal model,
                           fitted on the days before them, expected
  payroll_or_emi_at_risk   a salary or EMI day whose likely (P50) end-of-day balance is below 0
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

import numpy as np

from app.contracts import (
    Bill,
    CashGap,
    Direction,
    DocumentStatus,
    DriverKind,
    Figure,
    GapDriver,
    Invoice,
    LeadingIndicator,
    Money,
    ObligationKind,
    Transaction,
    TxCategory,
    Unit,
)
from app.engines.cash.baseline import FlowKind
from app.engines.cash.calendar import Festival
from app.engines.cash.delays import outstanding_on, settled_by
from app.engines.cash.figures import NO_EVIDENCE, Evidence, make_figure
from app.engines.cash.sales import daily_sales, fit_sales
from app.engines.cash.simulate import CENT, PAISA, Simulation, to_paisa

RISK_P = Decimal("0.05")
GAP_P = Decimal("0.20")
MAX_DRIVERS = 3
DSO_DAYS = 30
DSO_RISE = Decimal("1.2")
DSO_MIN_RISE_DAYS = Decimal(5)
TOP_CUSTOMERS = 3
TOP_WINDOW_DAYS = 90
RECENT_SETTLED_DAYS = 60
SLOWING_DAYS = 5
MIN_RECENT, MIN_EARLIER = 2, 3
STOCK_RECENT_DAYS, STOCK_PRIOR_DAYS = 30, 150
STOCK_RISE = Decimal("1.25")
NORM_DAYS = 14
NORM_SHARE = Decimal("0.85")
ZERO = Decimal(0)
_KIND_ORDER = {kind: n for n, kind in enumerate(DriverKind)}


def exceeds(count: int, paths: int, threshold: Decimal) -> bool:
    """count / paths > threshold, exactly (no rounding of the share)."""
    num, den = threshold.as_integer_ratio()
    return count * den > paths * num


def _share(count: int, paths: int) -> Decimal:
    return (Decimal(count) / Decimal(paths)).quantize(Decimal("0.0001"), ROUND_HALF_UP)


def shortfall(sim: Simulation, buffer: Decimal, first: int, last: int) -> tuple[Decimal, Decimal]:
    """(share of paths below `buffer` on a day in [first, last], expected shortfall in Tk)."""
    lows = sim.balances[:, first - 1:last].min(axis=1)
    short = np.maximum(to_paisa(buffer) - lows, 0)
    expected = (Decimal(int(short.sum())) / Decimal(sim.paths) / PAISA).quantize(CENT,
                                                                               ROUND_HALF_UP)
    return _share(int((short > 0).sum()), sim.paths), expected


@dataclass(frozen=True)
class Gap:
    gap: CashGap
    first: int  # first risk day of the run (1 = the day after as_of)
    last: int  # last risk day of the run
    peak: int  # last high point before the breach (0 = as_of, the opening balance)
    worst: int  # day of the worst day
    buffer: Decimal


def _runs(flags: Sequence[bool]) -> list[tuple[int, int]]:
    """Maximal runs of True as 1-based inclusive (first, last) day pairs."""
    runs, start = [], None
    for n, flag in enumerate(flags, start=1):
        if flag and start is None:
            start = n
        if not flag and start is not None:
            runs.append((start, n - 1))
            start = None
    if start is not None:
        runs.append((start, len(flags)))
    return runs


def find_gaps(sim: Simulation, buffer: Decimal, evidence: Evidence = NO_EVIDENCE
              ) -> tuple[Gap, ...]:
    """Every gap in the horizon, soonest first."""
    floor = to_paisa(buffer)
    counts = (sim.balances < floor).sum(axis=0)
    p50 = sim.percentile(50)
    opening = to_paisa(sim.baseline.opening_balance)
    gaps = []
    for first, last in _runs([exceeds(int(c), sim.paths, RISK_P) for c in counts]):
        dipped = (np.minimum.accumulate(sim.balances[:, first - 1:last], axis=1) < floor).sum(
            axis=0)
        over = [n for n, c in enumerate(dipped) if exceeds(int(c), sim.paths, GAP_P)]
        if not over:
            continue
        probability, expected = shortfall(sim, buffer, first, last)
        if expected <= 0:
            continue  # less than a paisa short on average: nothing to fix
        breach = first + over[0]
        worst = breach + int(np.argmin(p50[breach - 1:last]))
        likely = np.concatenate([[opening], p50[:breach - 1]])
        peak = int(len(likely) - 1 - np.argmax(likely[::-1]))  # the latest of equal highs
        gaps.append(_gap(sim, buffer, first, last, breach, worst, peak, probability, expected,
                         evidence))
    return tuple(gaps)


def _gap(sim: Simulation, buffer: Decimal, first: int, last: int, breach: int, worst: int,
         peak: int, probability: Decimal, expected: Decimal, evidence: Evidence) -> Gap:
    as_of = sim.baseline.as_of
    found = drivers(sim, peak, worst)
    rows = [_cite(d) for d in found if d.reference_id]
    params = {"buffer": buffer, "first_day": as_of + timedelta(days=first),
              "last_day": as_of + timedelta(days=last)}
    figures = (
        make_figure(sim, "cash.expected_shortfall", "cash.expected_shortfall", expected,
                    Unit.BDT, evidence, rows, params),
        make_figure(sim, "cash.gap_probability", "cash.breach_probability", probability,
                    Unit.probability, evidence, rows, params),
        make_figure(sim, "cash.lead_time_days", "cash.lead_time_days", Decimal(breach),
                    Unit.days, evidence, rows, params),
    )
    gap = CashGap(first_breach_day=as_of + timedelta(days=breach), lead_time_days=breach,
                  probability=probability, expected_shortfall=Money.of(expected),
                  worst_day=as_of + timedelta(days=worst), drivers=found, figures=figures)
    return Gap(gap=gap, first=first, last=last, peak=peak, worst=worst, buffer=buffer)


def _cite(driver: GapDriver) -> str:
    prefix = {DriverKind.obligation: "obl", DriverKind.bill_due: "bill"}.get(driver.kind, "inv")
    return f"{prefix}:{driver.reference_id}"


# ---------------------------------------------------------------- drivers


def drivers(sim: Simulation, peak: int, worst: int) -> tuple[GapDriver, ...]:
    """The largest reasons for the fall from day `peak` to day `worst` (see module doc)."""
    base, scenario = sim.baseline, sim.scenario
    start, end = base.as_of + timedelta(days=peak), base.as_of + timedelta(days=worst)
    found: list[GapDriver] = []

    def add(kind: DriverKind, label: str, amount: Decimal, reference: str | None = None,
            token: str | None = None) -> None:
        if Money.of(amount).amount > 0:
            found.append(GapDriver(kind=kind, label_key=label, amount=Money.of(amount),
                                   reference_id=reference, counterparty_token=token))

    owed_on: dict[str, Decimal] = {}
    for flow in base.flows:
        if flow.kind is FlowKind.obligation and start < flow.day <= end:
            owed_on[flow.reference_id] = owed_on.get(flow.reference_id, ZERO) + flow.amount
    for ob in base.obligations:
        if ob.id in owed_on:
            add(DriverKind.obligation, f"driver.{ob.kind.value}", owed_on[ob.id], ob.id,
                ob.counterparty_token)

    for ob in base.open_bills:
        payments = scenario.bill_payments.get(ob.bill.id, ((ob.pay_day, ob.owed),))
        add(DriverKind.bill_due, "driver.supplier_bill",
            sum((a for d, a in payments if start < d <= end), ZERO), ob.bill.id,
            ob.bill.counterparty_token)

    late: dict[str, tuple[Decimal, Decimal, str]] = {}  # token -> (total, largest, its id)
    for inv, owed in base.open_invoices:
        if inv.due_date > end:
            continue
        change = scenario.invoice_changes.get(inv.id)
        remaining = change.remainder if change else owed
        possible = [d + timedelta(days=scenario.collection_delay_days)
                    for d in base.invoice_delays.possible_days(inv, base.as_of)]
        after = Decimal(sum(1 for d in possible if d > end)) / len(possible) if possible else 1
        amount = remaining * after
        if amount > 0:
            total, largest, ref = late.get(inv.counterparty_token, (ZERO, ZERO, inv.id))
            if amount > largest or (amount == largest and inv.id < ref):
                largest, ref = amount, inv.id
            late[inv.counterparty_token] = (total + amount, largest, ref)
    for token, (total, _largest, ref) in late.items():
        add(DriverKind.late_customer, "driver.late_customer", total, ref, token)
    for inv, owed in base.disputed_invoices:
        if inv.due_date <= end:
            add(DriverKind.late_customer, "driver.disputed_invoice", owed, inv.id,
                inv.counterparty_token)

    model = base.sales
    window = [d for d in base.days if start < d <= end]
    add(DriverKind.seasonal_dip, "driver.seasonal_dip",
        sum((max(ZERO, model.level * model.weekday[d.weekday()] - model.expected(d))
             for d in window), ZERO))
    if scenario.sales_change_pct < 0:
        expected = sum((f.amount for f in base.flows
                        if f.kind is FlowKind.sales and start < f.day <= end), ZERO)
        add(DriverKind.seasonal_dip, "driver.sales_drop",
            expected * -scenario.sales_change_pct / 100)
    add(DriverKind.cost_shock, "driver.one_off_cost",
        sum((-a for d, a in scenario.flows if a < 0 and start < d <= end), ZERO))

    found.sort(key=lambda d: (-d.amount.amount, _KIND_ORDER[d.kind], d.reference_id or ""))
    return tuple(found[:MAX_DRIVERS])


# ---------------------------------------------------------------- leading indicators


@dataclass(frozen=True)
class Signal:
    indicator: LeadingIndicator
    figures: tuple[Figure, ...]
    reference_id: str | None = None
    counterparty_token: str | None = None
    day: date | None = None  # the day it is about (a salary or EMI due day)


def _median(values: Sequence[int]) -> int:
    ordered = sorted(values)
    return ordered[(len(ordered) - 1) // 2]


def _dso(invoices: Sequence[Invoice], end: date) -> Decimal | None:
    start = end - timedelta(days=DSO_DAYS - 1)
    issued = sum((i.amount.amount for i in invoices if start <= i.issue_date <= end), ZERO)
    if issued <= 0:
        return None
    owed = sum((outstanding_on(i, end) for i in invoices if i.issue_date <= end), ZERO)
    return owed / issued * DSO_DAYS


def _dso_rising(sim: Simulation, invoices: Sequence[Invoice], evidence: Evidence
                ) -> list[Signal]:
    as_of = sim.baseline.as_of
    now, before = _dso(invoices, as_of), _dso(invoices, as_of - timedelta(days=DSO_DAYS))
    if now is None or before is None:
        return []
    if now < before * DSO_RISE or now - before < DSO_MIN_RISE_DAYS:
        return []
    figures = tuple(
        make_figure(sim, "cash.dso_30d", label, value, Unit.days, evidence,
                    params={"period_end": end})
        for label, value, end in (("cash.dso_now", now, as_of),
                                  ("cash.dso_before", before, as_of - timedelta(days=DSO_DAYS))))
    return [Signal(LeadingIndicator.dso_rising, figures)]


def _top_customers(invoices: Sequence[Invoice], as_of: date) -> list[str]:
    since = as_of - timedelta(days=TOP_WINDOW_DAYS - 1)
    volume: dict[str, Decimal] = {}
    first: dict[str, str] = {}  # equal volumes break on the first invoice id, never the name
    for inv in invoices:
        if since <= inv.issue_date <= as_of:
            token = inv.counterparty_token
            volume[token] = volume.get(token, ZERO) + inv.amount.amount
            first[token] = min(first.get(token, inv.id), inv.id)
    return sorted(volume, key=lambda t: (-volume[t], first[t]))[:TOP_CUSTOMERS]


def _slowing(sim: Simulation, invoices: Sequence[Invoice], evidence: Evidence) -> list[Signal]:
    as_of = sim.baseline.as_of
    cut = as_of - timedelta(days=RECENT_SETTLED_DAYS)
    signals = []
    for token in _top_customers(invoices, as_of):
        own = [i for i in invoices if i.counterparty_token == token and i.issue_date <= as_of]
        settled = [(i.paid_date, (i.paid_date - i.due_date).days) for i in own
                   if settled_by(i, as_of) and i.paid_date is not None]
        recent = [d for paid, d in settled if paid > cut]
        earlier = [d for paid, d in settled if paid <= cut]
        rows = [f"inv:{i.id}" for i in own]
        if len(recent) >= MIN_RECENT and len(earlier) >= MIN_EARLIER and \
                _median(recent) - _median(earlier) >= SLOWING_DAYS:
            figures = (
                make_figure(sim, "cash.customer_delay_median", "cash.delay_recent",
                            Decimal(_median(recent)), Unit.days, evidence, rows,
                            {"customer": token, "settled_after": cut}),
                make_figure(sim, "cash.customer_delay_median", "cash.delay_before",
                            Decimal(_median(earlier)), Unit.days, evidence, rows,
                            {"customer": token, "settled_by": cut}))
            signals.append(Signal(LeadingIndicator.top_customer_slowing, figures,
                                  counterparty_token=token))
            continue
        history = recent + earlier
        overdue = [i for i in own if i.due_date < as_of and not settled_by(i, as_of)
                   and outstanding_on(i, as_of) > 0 and i.status is not DocumentStatus.disputed]
        if len(history) >= MIN_EARLIER and overdue:
            oldest = min(overdue, key=lambda i: (i.due_date, i.id))
            days = (as_of - oldest.due_date).days
            if days > max(history):
                figure = make_figure(sim, "cash.days_overdue", "cash.days_overdue",
                                     Decimal(days), Unit.days, evidence, [f"inv:{oldest.id}"],
                                     {"customer": token, "latest_ever": max(history)})
                signals.append(Signal(LeadingIndicator.top_customer_slowing, (figure,),
                                      oldest.id, token))
    return signals


def _purchase_ratio(transactions: Sequence[Transaction], invoices: Sequence[Invoice],
                    bills: Sequence[Bill], start: date, end: date) -> Decimal | None:
    def within(day: date) -> bool:
        return start <= day <= end

    bought = sum((t.amount.amount for t in transactions if within(t.day)
                  and t.direction is Direction.outflow and t.category is TxCategory.purchase),
                 ZERO) + sum((b.amount.amount for b in bills if within(b.issue_date)), ZERO)
    sold = sum((t.amount.amount for t in transactions if within(t.day)
                and t.direction is Direction.inflow and t.category is TxCategory.sales),
               ZERO) + sum((i.amount.amount for i in invoices if within(i.issue_date)), ZERO)
    return bought / sold if sold > 0 else None


def _stock_building(sim: Simulation, transactions: Sequence[Transaction],
                    invoices: Sequence[Invoice], bills: Sequence[Bill], evidence: Evidence
                    ) -> list[Signal]:
    as_of = sim.baseline.as_of
    split = as_of - timedelta(days=STOCK_RECENT_DAYS)
    recent = _purchase_ratio(transactions, invoices, bills, split + timedelta(days=1), as_of)
    prior = _purchase_ratio(transactions, invoices, bills,
                            split - timedelta(days=STOCK_PRIOR_DAYS - 1), split)
    if recent is None or not prior or recent < prior * STOCK_RISE:
        return []
    figures = (
        make_figure(sim, "cash.purchase_to_sales", "cash.purchase_ratio_recent", recent,
                    Unit.ratio, evidence, params={"days": STOCK_RECENT_DAYS}),
        make_figure(sim, "cash.purchase_to_sales", "cash.purchase_ratio_before", prior,
                    Unit.ratio, evidence, params={"days": STOCK_PRIOR_DAYS}))
    return [Signal(LeadingIndicator.stock_building, figures)]


def _below_norm(sim: Simulation, transactions: Sequence[Transaction],
                festivals: Sequence[Festival], evidence: Evidence) -> list[Signal]:
    as_of = sim.baseline.as_of
    cut = as_of - timedelta(days=NORM_DAYS)
    model = fit_sales([t for t in transactions if t.day <= cut], cut, festivals)
    expected = sum((model.expected(cut + timedelta(days=k)) for k in range(1, NORM_DAYS + 1)),
                   ZERO)
    actual = sum(daily_sales(transactions, cut + timedelta(days=1), as_of).values(), ZERO)
    if expected <= 0 or actual >= expected * NORM_SHARE:
        return []
    figures = (
        make_figure(sim, "cash.sales_vs_norm", "cash.sales_last_14_days", actual, Unit.BDT,
                    evidence, params={"from": cut + timedelta(days=1)}),
        make_figure(sim, "cash.sales_vs_norm", "cash.sales_norm_14_days", expected, Unit.BDT,
                    evidence, params={"fitted_to": cut}))
    return [Signal(LeadingIndicator.sales_below_seasonal_norm, figures)]


def _payroll_at_risk(sim: Simulation, evidence: Evidence) -> list[Signal]:
    base = sim.baseline
    kinds = {ob.id: ob for ob in base.obligations
             if ob.kind in (ObligationKind.salary, ObligationKind.emi)}
    p50 = sim.percentile(50)
    due = sorted((f.day, f.reference_id) for f in base.flows
                 if f.kind is FlowKind.obligation and f.reference_id in kinds)
    for day, ref in due:
        likely = Decimal(int(p50[(day - base.as_of).days - 1])) / PAISA
        if likely < 0:
            ob = kinds[ref]
            figure = make_figure(sim, "cash.p50_on_due_day", f"cash.p50_on_{ob.kind.value}_day",
                                 likely, Unit.BDT, evidence, [f"obl:{ob.id}"], {"due_day": day})
            return [Signal(LeadingIndicator.payroll_or_emi_at_risk, (figure,), ob.id,
                           ob.counterparty_token, day)]
    return []


def leading_indicators(sim: Simulation, transactions: Iterable[Transaction],
                       invoices: Iterable[Invoice], bills: Iterable[Bill],
                       festivals: Sequence[Festival], evidence: Evidence = NO_EVIDENCE
                       ) -> tuple[Signal, ...]:
    """Every indicator that fires as of the simulation's as_of (rows after it are ignored)."""
    as_of = sim.baseline.as_of
    tenant = sim.baseline.tenant_id
    txns = [t for t in transactions if t.day <= as_of and t.tenant_id == tenant]
    invs = [i for i in invoices if i.issue_date <= as_of and i.tenant_id == tenant]
    bls = [b for b in bills if b.issue_date <= as_of and b.tenant_id == tenant]
    return tuple([*_dso_rising(sim, invs, evidence), *_slowing(sim, invs, evidence),
                  *_stock_building(sim, txns, invs, bls, evidence),
                  *_below_norm(sim, txns, festivals, evidence),
                  *_payroll_at_risk(sim, evidence)])
