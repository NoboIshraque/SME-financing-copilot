"""Baseline forecaster: expected daily inflows and outflows for the next 91 days (WP-04 m1).

balance(day) = opening balance + expected inflows - expected outflows, where

- inflows  = recurring sales (see `sales.py`)
           + collections on open invoices x the customer's delay distribution (`delays.py`)
           + collections on invoices not yet issued: recent credit-sales rate x the share of
             invoices paid within that many days of issue
- outflows = recurring obligations on their schedule (rent, salary, EMI, utilities, ...)
           + open bills on their due date (overdue ones tomorrow)
           + bills not yet issued: recent credit-purchase rate x the share paid within that many
             days of issue
           + cash purchases and other running costs at their recent daily rate (categories
             already covered by an obligation are left out, so nothing is counted twice)

Transfers between the business's own accounts cancel out in the total balance and are left
out. Disputed invoices are not expected to be collected. Every flow keeps the document it
comes from, for drivers and provenance. Pure: contracts in, `Baseline` out.
"""

from __future__ import annotations

import calendar as _calendar
from collections.abc import Iterable, Sequence
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


def _run_rate(transactions: Iterable[Transaction], as_of: date,
              categories: frozenset[TxCategory]) -> Decimal:
    since = as_of - timedelta(days=RUN_RATE_DAYS - 1)
    total = sum((t.amount.amount for t in transactions
                 if t.direction is OUTFLOW and t.category in categories
                 and since <= t.day <= as_of), ZERO)
    return total / RUN_RATE_DAYS


def _issued_rate(documents: Iterable[Invoice | Bill], as_of: date) -> Decimal:
    since = as_of - timedelta(days=RUN_RATE_DAYS - 1)
    return sum((d.amount.amount for d in documents if since <= d.issue_date <= as_of),
               ZERO) / RUN_RATE_DAYS


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
    days = tuple(as_of + timedelta(days=n) for n in range(1, horizon + 1))
    end = days[-1]
    flows: list[Flow] = []

    sales = fit_sales(known_txns, as_of, festivals)
    for day in days:
        if (amount := sales.expected(day)) > 0:
            flows.append(Flow(day, amount, INFLOW, FlowKind.sales))

    invoice_delays = DelayTable.from_documents(known_invoices, as_of)
    open_invoices = []
    for inv in known_invoices:
        owed = outstanding_on(inv, as_of)
        if owed <= 0 or inv.status is DocumentStatus.disputed:
            continue
        open_invoices.append((inv, owed))
        for day, probability in invoice_delays.payment_days(inv, as_of):
            if day <= end:
                flows.append(Flow(day, owed * probability, INFLOW, FlowKind.collection, inv.id,
                                  inv.counterparty_token))
    credit_sales = _issued_rate(known_invoices, as_of)
    bill_delays = DelayTable.from_documents(known_bills, as_of)
    credit_purchases = _issued_rate(known_bills, as_of)
    for n, day in enumerate(days, start=1):
        if credit_sales and (share := invoice_delays.paid_within(n - 1)):
            flows.append(Flow(day, credit_sales * share, INFLOW, FlowKind.new_invoices))
        if credit_purchases and (share := bill_delays.paid_within(n - 1)):
            flows.append(Flow(day, credit_purchases * share, OUTFLOW, FlowKind.new_bills))

    for bill in known_bills:
        owed = outstanding_on(bill, as_of)
        if owed > 0:
            due = bill.due_date if bill.due_date > as_of else days[0]
            if due <= end:
                flows.append(Flow(due, owed, OUTFLOW, FlowKind.bill, bill.id,
                                  bill.counterparty_token))

    covered: set[TxCategory] = set()
    for obligation in obligations:
        if obligation.tenant_id != tenant_id:
            continue
        if obligation_days(obligation, days[0], end) or obligation.end_date is None or \
                obligation.end_date >= as_of:
            covered.add(OBLIGATION_CATEGORY[obligation.kind])
        for due in obligation_days(obligation, days[0], end):
            flows.append(Flow(due, obligation.amount.amount, OUTFLOW, FlowKind.obligation,
                              obligation.id, obligation.counterparty_token))

    purchases = _run_rate(known_txns, as_of, frozenset({TxCategory.purchase}))
    running = _run_rate(known_txns, as_of, frozenset(
        c for c in TxCategory if c not in _NOT_RUN_RATE and c not in covered))
    for day in days:
        if purchases:
            flows.append(Flow(day, purchases, OUTFLOW, FlowKind.purchases))
        if running:
            flows.append(Flow(day, running, OUTFLOW, FlowKind.running_cost))

    return Baseline(
        tenant_id=tenant_id, as_of=as_of, opening_balance=opening_balance, days=days,
        flows=tuple(flows), sales=sales, invoice_delays=invoice_delays,
        open_invoices=tuple(open_invoices),
        data_mode=_modes(known_txns, known_invoices, known_bills, obligations),
    )
