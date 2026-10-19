"""Baseline forecaster: expected daily inflows and outflows for the next 91 days (WP-04 m1).

balance(day) = opening balance + expected inflows - expected outflows, where

- inflows  = recurring sales (see `sales.py`)
           + collections on open invoices x the customer's delay distribution (`delays.py`)
           + collections on invoices not yet issued: recent credit-sales rate x the share of
             invoices paid within that many days of issue
- outflows = recurring obligations on their schedule (rent, salary, EMI, utilities, ...)
           + open bills when the business usually pays that supplier (its median delay; the
             due date without history; overdue ones no earlier than tomorrow)
           + bills not yet issued: recent credit-purchase rate x the share paid within that many
             days of issue
           + cash purchases and other running costs at their recent daily rate (categories
             already covered by an obligation are left out, so nothing is counted twice)

Transfers between the business's own accounts cancel out in the total balance and are left
out. Disputed invoices are not expected to be collected. Every flow keeps the document it
comes from, for drivers and provenance. The day-by-day totals behind each run rate are kept
too: the Monte Carlo (`simulate.py`) resamples them. Pure: contracts in, `Baseline` out.
"""

from __future__ import annotations

import calendar as _calendar
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum

from app.contracts import (
    Bill,
    DataMode,
    Direction,
    DocumentStatus,
    Frequency,
    Invoice,
    ObligationKind,
    RecurringObligation,
    Transaction,
    TxCategory,
)
from app.engines.cash.calendar import Festival
from app.engines.cash.delays import DelayTable, outstanding_on
from app.engines.cash.sales import SalesModel, fit_sales

HORIZON_DAYS = 91
RUN_RATE_DAYS = 91
ZERO = Decimal(0)
CENT = Decimal("0.01")
INFLOW, OUTFLOW = Direction.inflow, Direction.outflow

OBLIGATION_CATEGORY = {
    ObligationKind.rent: TxCategory.rent,
    ObligationKind.salary: TxCategory.salary,
    ObligationKind.emi: TxCategory.loan_repayment,
    ObligationKind.utility: TxCategory.utility,
    ObligationKind.tax: TxCategory.tax,
    ObligationKind.subscription: TxCategory.other,
    ObligationKind.other: TxCategory.other,
}
# Outflow categories never projected at a run rate: transfers net out, supplier payments
# follow bills, and these are the business's own schedule (obligations) when one exists.
_NOT_RUN_RATE = frozenset({TxCategory.transfer, TxCategory.supplier_payment, TxCategory.purchase})


class FlowKind(StrEnum):
    sales = "sales"
    collection = "collection"
    new_invoices = "new_invoices"
    obligation = "obligation"
    bill = "bill"
    new_bills = "new_bills"
    purchases = "purchases"
    running_cost = "running_cost"


@dataclass(frozen=True)
class Flow:
    day: date
    amount: Decimal  # expected (probability-weighted), positive
    direction: Direction
    kind: FlowKind
    reference_id: str | None = None
    counterparty_token: str | None = None


@dataclass(frozen=True)
class OpenBill:
    bill: Bill
    owed: Decimal  # outstanding on as_of
    pay_day: date  # when the forecast pays it (may be after the horizon)


@dataclass(frozen=True)
class Baseline:
    tenant_id: str
    as_of: date
    opening_balance: Decimal
    days: tuple[date, ...]
    flows: tuple[Flow, ...]
    sales: SalesModel
    invoice_delays: DelayTable
    open_invoices: tuple[tuple[Invoice, Decimal], ...]  # (invoice, outstanding on as_of)
    data_mode: DataMode
    bill_delays: DelayTable = DelayTable({}, (), ())
    open_bills: tuple[OpenBill, ...] = ()
    obligations: tuple[RecurringObligation, ...] = ()
    disputed_invoices: tuple[tuple[Invoice, Decimal], ...] = ()  # owed, not expected
    # Day-by-day totals over the run-rate window (oldest first) behind each run-rate flow:
    # new_invoices / new_bills = documents issued that day, purchases / running_cost = spent.
    daily_history: Mapping[FlowKind, tuple[Decimal, ...]] | None = None
    history_days: int = 0  # days from the first known transaction to as_of, inclusive

    @property
    def horizon(self) -> int:
        return len(self.days)

    def total(self, day: date, direction: Direction) -> Decimal:
        return sum((f.amount for f in self.flows if f.day == day and f.direction is direction),
                   ZERO)

    def net(self, day: date) -> Decimal:
        return self.total(day, INFLOW) - self.total(day, OUTFLOW)

    def balances(self) -> list[tuple[date, Decimal]]:
        """Expected end-of-day balance, rounded to the paisa."""
        net: dict[date, Decimal] = dict.fromkeys(self.days, ZERO)
        for flow in self.flows:
            net[flow.day] += flow.amount if flow.direction is INFLOW else -flow.amount
        running, out = self.opening_balance, []
        for day in self.days:
            running += net[day]
            out.append((day, running.quantize(CENT)))
        return out

    def history(self, kind: FlowKind) -> tuple[Decimal, ...]:
        return (self.daily_history or {}).get(kind, ())


# ---------------------------------------------------------------- schedules


def _month_day(year: int, month: int, day_of_period: int) -> date:
    return date(year, month, min(day_of_period, _calendar.monthrange(year, month)[1]))


def obligation_days(obligation: RecurringObligation, start: date, end: date) -> list[date]:
    """Days within [start, end] when a recurring obligation falls due (day 31 is the month's
    last day in shorter months; weekly obligations use 1 = Monday ... 7 = Sunday)."""
    first = max(start, obligation.start_date)
    last = min(end, obligation.end_date) if obligation.end_date else end
    if first > last:
        return []
    if obligation.frequency is Frequency.weekly:
        offset = (obligation.day_of_period - 1 - first.weekday()) % 7
        return [first + timedelta(days=offset + 7 * k)
                for k in range(((last - first).days - offset) // 7 + 1)
                if first + timedelta(days=offset + 7 * k) <= last]
    step = {Frequency.monthly: 1, Frequency.quarterly: 3, Frequency.yearly: 12}[
        obligation.frequency]
    days, year, month = [], obligation.start_date.year, obligation.start_date.month
    while True:
        due = _month_day(year, month, obligation.day_of_period)
        if due > last:
            return days
        if due >= first:
            days.append(due)
        month += step
        year, month = year + (month - 1) // 12, (month - 1) % 12 + 1


def bill_pay_day(bill: Bill, as_of: date, delays: DelayTable) -> date:
    """When the forecast pays an open bill: when the business usually pays this supplier
    (due date + its median delay, early or late; the due date without history), never in the
    past. The walk-forward backtest showed that paying everything on the due date biases the
    balance low by about a day of supplier payments."""
    typical = delays.typical_delay(bill.counterparty_token) or 0
    return max(bill.due_date + timedelta(days=typical), as_of + timedelta(days=1))


def daily_totals(items: Iterable[Transaction | Invoice | Bill], as_of: date,
                 day_of: Callable, keep: Callable[[object], bool]) -> tuple[Decimal, ...]:
    """Totals per day over the run-rate window ending on `as_of`, oldest first."""
    since = as_of - timedelta(days=RUN_RATE_DAYS - 1)
    totals = [ZERO] * RUN_RATE_DAYS
    for item in items:
        day = day_of(item)
        if since <= day <= as_of and keep(item):
            totals[(day - since).days] += item.amount.amount
    return tuple(totals)


def _spent(categories: frozenset[TxCategory]) -> Callable[[object], bool]:
    return lambda t: t.direction is OUTFLOW and t.category in categories


def _rate(totals: Sequence[Decimal]) -> Decimal:
    return sum(totals, ZERO) / RUN_RATE_DAYS


def _modes(*groups: Iterable[Transaction | Invoice | Bill | RecurringObligation]) -> DataMode:
    present = {item.data_mode for group in groups for item in group}
    for mode in (DataMode.synthetic, DataMode.real_anonymised, DataMode.public, DataMode.live):
        if mode in present:
            return mode
    return DataMode.live


# ---------------------------------------------------------------- forecast


def forecast_baseline(
    tenant_id: str,
    as_of: date,
    opening_balance: Decimal,
    transactions: Sequence[Transaction],
    invoices: Sequence[Invoice],
    bills: Sequence[Bill],
    obligations: Sequence[RecurringObligation],
    festivals: Sequence[Festival],
    horizon: int = HORIZON_DAYS,
) -> Baseline:
    """Expected flows for the `horizon` days after `as_of`, from data up to `as_of` only."""
    known_txns = [t for t in transactions if t.day <= as_of]
    known_invoices = [i for i in invoices if i.issue_date <= as_of]
    known_bills = [b for b in bills if b.issue_date <= as_of]
    own_obligations = tuple(o for o in obligations if o.tenant_id == tenant_id)
    days = tuple(as_of + timedelta(days=n) for n in range(1, horizon + 1))
    end = days[-1]
    flows: list[Flow] = []

    sales = fit_sales(known_txns, as_of, festivals)
    for day in days:
        if (amount := sales.expected(day)) > 0:
            flows.append(Flow(day, amount, INFLOW, FlowKind.sales))

    invoice_delays = DelayTable.from_documents(known_invoices, as_of)
    open_invoices, disputed = [], []
    for inv in known_invoices:
        owed = outstanding_on(inv, as_of)
        if owed <= 0:
            continue
        if inv.status is DocumentStatus.disputed:
            disputed.append((inv, owed))
            continue
        open_invoices.append((inv, owed))
        for day, probability in invoice_delays.payment_days(inv, as_of):
            if day <= end:
                flows.append(Flow(day, owed * probability, INFLOW, FlowKind.collection, inv.id,
                                  inv.counterparty_token))
    bill_delays = DelayTable.from_documents(known_bills, as_of)
    history = {
        FlowKind.new_invoices: daily_totals(known_invoices, as_of, lambda d: d.issue_date,
                                            lambda _d: True),
        FlowKind.new_bills: daily_totals(known_bills, as_of, lambda d: d.issue_date,
                                         lambda _d: True),
    }
    credit_sales = _rate(history[FlowKind.new_invoices])
    credit_purchases = _rate(history[FlowKind.new_bills])
    for n, day in enumerate(days, start=1):
        if credit_sales and (share := invoice_delays.paid_within(n - 1)):
            flows.append(Flow(day, credit_sales * share, INFLOW, FlowKind.new_invoices))
        if credit_purchases and (share := bill_delays.paid_within(n - 1)):
            flows.append(Flow(day, credit_purchases * share, OUTFLOW, FlowKind.new_bills))

    open_bills = []
    for bill in known_bills:
        owed = outstanding_on(bill, as_of)
        if owed > 0:
            pay_day = bill_pay_day(bill, as_of, bill_delays)
            open_bills.append(OpenBill(bill, owed, pay_day))
            if pay_day <= end:
                flows.append(Flow(pay_day, owed, OUTFLOW, FlowKind.bill, bill.id,
                                  bill.counterparty_token))

    covered: set[TxCategory] = set()
    for obligation in own_obligations:
        if obligation_days(obligation, days[0], end) or obligation.end_date is None or \
                obligation.end_date >= as_of:
            covered.add(OBLIGATION_CATEGORY[obligation.kind])
        for due in obligation_days(obligation, days[0], end):
            flows.append(Flow(due, obligation.amount.amount, OUTFLOW, FlowKind.obligation,
                              obligation.id, obligation.counterparty_token))

    history[FlowKind.purchases] = daily_totals(known_txns, as_of, lambda t: t.day,
                                               _spent(frozenset({TxCategory.purchase})))
    history[FlowKind.running_cost] = daily_totals(known_txns, as_of, lambda t: t.day, _spent(
        frozenset(c for c in TxCategory if c not in _NOT_RUN_RATE and c not in covered)))
    purchases = _rate(history[FlowKind.purchases])
    running = _rate(history[FlowKind.running_cost])
    for day in days:
        if purchases:
            flows.append(Flow(day, purchases, OUTFLOW, FlowKind.purchases))
        if running:
            flows.append(Flow(day, running, OUTFLOW, FlowKind.running_cost))

    first_day = min((t.day for t in known_txns), default=None)
    return Baseline(
        tenant_id=tenant_id, as_of=as_of, opening_balance=opening_balance, days=days,
        flows=tuple(flows), sales=sales, invoice_delays=invoice_delays,
        open_invoices=tuple(open_invoices),
        data_mode=_modes(known_txns, known_invoices, known_bills, own_obligations),
        bill_delays=bill_delays, open_bills=tuple(open_bills), obligations=own_obligations,
        disputed_invoices=tuple(disputed),
        daily_history=history,
        history_days=(as_of - first_day).days + 1 if first_day else 0,
    )
