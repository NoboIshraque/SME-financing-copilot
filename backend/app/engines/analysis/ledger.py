"""What the analysis engine reads: one tenant's typed ledger and an anchored cash balance (WP-07).

`Ledger.anchor` is a stored fact holding the cash balance at the start of its day (the raw
`initial_balance` fact, or a WP-01 `opening_balance` fact). Cash on any later day is the anchor
plus the signed transactions in between; nothing before the anchor is ever guessed.
`Ledger.facts` are optional facts the ledger cannot derive (`stock_value`, `loan_outstanding`,
`interest_expense`): a figure that needs one that is not on record is left out and named in
`missing` (FEATURES N17: prefer abstaining to guessing).
"""

from __future__ import annotations

import calendar as _calendar
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.contracts import (
    Bill,
    DataMode,
    Fact,
    Granularity,
    Invoice,
    ObligationKind,
    Period,
    RecurringObligation,
    Transaction,
    TxCategory,
    Unit,
)
from app.facts.registry import cite

ZERO = Decimal(0)
FRESH_DAYS = 31  # a stock count or loan statement older than this is not "known" on a day
LOAN_CATEGORIES = frozenset({TxCategory.loan_disbursement, TxCategory.loan_repayment})
_MODE_PRIORITY = (DataMode.synthetic, DataMode.real_anonymised, DataMode.public, DataMode.live)


class NotEnoughData(ValueError):
    """The ledger cannot support the figure: `missing` says exactly what is needed."""

    def __init__(self, missing: str, reason_key: str = "abstain.insufficient_data") -> None:
        super().__init__(missing)
        self.missing = missing
        self.reason_key = reason_key


def combined_mode(modes: Iterable[DataMode]) -> DataMode:
    """Most cautious first: anything built from synthetic data is labelled synthetic."""
    present = set(modes)
    for mode in _MODE_PRIORITY:
        if mode in present:
            return mode
    return DataMode.live


def calendar_period(day: date, granularity: Granularity) -> Period:
    """The calendar week (Monday-Sunday), month, quarter or year containing `day`."""
    if granularity is Granularity.day:
        return Period(start=day, end=day, granularity=granularity)
    if granularity is Granularity.week:
        start = day - timedelta(days=day.weekday())
        return Period(start=start, end=start + timedelta(days=6), granularity=granularity)
    if granularity is Granularity.month:
        months = (day.month, day.month)
    elif granularity is Granularity.quarter:
        first = (day.month - 1) // 3 * 3 + 1
        months = (first, first + 2)
    else:
        months = (1, 12)
    start = date(day.year, months[0], 1)
    end = date(day.year, months[1], _calendar.monthrange(day.year, months[1])[1])
    return Period(start=start, end=end, granularity=granularity)


def previous_period(period: Period) -> Period:
    return calendar_period(period.start - timedelta(days=1), period.granularity)


@dataclass(frozen=True)
class Ledger:
    tenant_id: str
    anchor: Fact
    transactions: tuple[Transaction, ...] = ()
    invoices: tuple[Invoice, ...] = ()
    bills: tuple[Bill, ...] = ()
    obligations: tuple[RecurringObligation, ...] = ()
    facts: tuple[Fact, ...] = ()

    def __post_init__(self) -> None:
        if self.anchor.unit is not Unit.BDT or self.anchor.tenant_id != self.tenant_id:
            raise ValueError("the anchor is a BDT balance fact of this tenant")
        for group in (self.transactions, self.invoices, self.bills, self.obligations,
                      self.facts):
            if any(item.tenant_id != self.tenant_id for item in group):
                raise ValueError("every record must belong to the ledger's tenant")

    @property
    def anchor_day(self) -> date:
        return self.anchor.period.start

    @property
    def as_of(self) -> date:
        """The last day with a transaction: the end of what the ledger knows."""
        if not self.transactions:
            raise NotEnoughData("transactions")
        return max(t.day for t in self.transactions)

    @property
    def data_mode(self) -> DataMode:
        return combined_mode([self.anchor.data_mode,
                              *(r.data_mode for g in (self.transactions, self.invoices,
                                                      self.bills, self.obligations) for r in g)])

    def between(self, first: date, last: date) -> list[Transaction]:
        return [t for t in self.transactions if first <= t.day <= last]

    def cash_at_start(self, day: date) -> tuple[Decimal, list[Transaction]]:
        """(cash before any transaction of `day`, the transactions added to the anchor)."""
        if day < self.anchor_day:
            raise NotEnoughData(f"a cash balance on or before {day.isoformat()}",
                                "abstain.before_anchor")
        before = self.between(self.anchor_day, day - timedelta(days=1))
        return self.anchor.value + sum((t.signed_amount.amount for t in before), ZERO), before

    def known(self, metric: str, day: date, fresh_days: int = FRESH_DAYS) -> Fact | None:
        """The latest fact of `metric` dated within `fresh_days` up to `day`, or None."""
        found = [f for f in self.facts if f.metric == metric and f.entity_token is None
                 and day - timedelta(days=fresh_days) < f.period.end <= day]
        return max(found, key=lambda f: (f.period.end, f.id)) if found else None

    def in_period(self, metric: str, period: Period) -> Fact | None:
        """A fact of `metric` for exactly `period` (e.g. interest_expense for the quarter)."""
        found = [f for f in self.facts if f.metric == metric and f.entity_token is None
                 and f.period == period]
        return max(found, key=lambda f: f.id) if found else None

    def has_loan_activity(self, day: date) -> bool:
        """Any loan disbursement or repayment on record by `day`, or an EMI obligation."""
        return any(t.category in LOAN_CATEGORIES and t.day <= day for t in self.transactions) \
            or any(o.kind is ObligationKind.emi and o.start_date <= day for o in self.obligations)


def cite_all(records: Sequence[Transaction | Invoice | Bill]) -> tuple[str, ...]:
    return tuple(cite(r) for r in records)
