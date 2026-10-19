"""Aging and payment history (WP-05 milestone 1; FEATURES Q2).

Pure functions over typed invoices. An invoice is open while something is still owed on it and
it is not paid or written off. Days overdue count from the due date (0 while not yet due), and
buckets are 0-30, 31-60, 61-90 and 90+ days overdue.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.contracts import DocumentStatus, Invoice, Money

BUCKETS = ("0_30", "31_60", "61_90", "90_plus")
CLOSED = (DocumentStatus.paid, DocumentStatus.written_off)


def open_amount(invoice: Invoice) -> Money:
    return invoice.amount - invoice.amount_paid


def is_open(invoice: Invoice, as_of: date) -> bool:
    return (invoice.issue_date <= as_of and invoice.status not in CLOSED
            and open_amount(invoice).amount > 0)


def days_overdue(invoice: Invoice, as_of: date) -> int:
    return max(0, (as_of - invoice.due_date).days)


def bucket(days: int) -> str:
    if days < 0:
        raise ValueError("days overdue cannot be negative")
    if days <= 30:
        return "0_30"
    if days <= 60:
        return "31_60"
    if days <= 90:
        return "61_90"
    return "90_plus"


@dataclass(frozen=True)
class BucketTotal:
    bucket: str
    amount: Money
    count: int
    invoice_ids: tuple[str, ...]


def aging(invoices: Iterable[Invoice], as_of: date) -> list[BucketTotal]:
    """Open amounts per bucket, every bucket present (empty ones at zero), in order."""
    amounts: dict[str, Money] = {b: Money.zero() for b in BUCKETS}
    ids: dict[str, list[str]] = {b: [] for b in BUCKETS}
    for inv in invoices:
        if is_open(inv, as_of):
            b = bucket(days_overdue(inv, as_of))
            amounts[b] = amounts[b] + open_amount(inv)
            ids[b].append(inv.id)
    return [BucketTotal(b, amounts[b], len(ids[b]), tuple(sorted(ids[b]))) for b in BUCKETS]


@dataclass(frozen=True)
class History:
    """How one customer has paid: only invoices paid on or before `as_of` count."""

    paid_count: int
    late_count: int
    days_late: tuple[int, ...]  # per paid invoice, negative = early
    usual_amount: Decimal | None  # median invoice amount
    last_paid: date | None

    @property
    def late_share(self) -> Decimal:
        return Decimal(self.late_count) / self.paid_count if self.paid_count else Decimal(0)

    @property
    def median_days_late(self) -> Decimal:
        return _median([Decimal(d) for d in self.days_late]) if self.days_late else Decimal(0)


def _median(values: Sequence[Decimal]) -> Decimal:
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def histories(invoices: Iterable[Invoice], as_of: date) -> dict[str, History]:
    by_customer: dict[str, list[Invoice]] = defaultdict(list)
    for inv in invoices:
        if inv.issue_date <= as_of:
            by_customer[inv.counterparty_token].append(inv)
    out = {}
    for token, docs in by_customer.items():
        paid = [d for d in docs if d.status is DocumentStatus.paid and d.paid_date is not None
                and d.paid_date <= as_of]
        late = tuple((d.paid_date - d.due_date).days for d in paid)  # type: ignore[operator]
        out[token] = History(
            paid_count=len(paid),
            late_count=sum(1 for d in late if d > 0),
            days_late=late,
            usual_amount=_median([d.amount.amount for d in docs]) if docs else None,
            last_paid=max((d.paid_date for d in paid), default=None),  # type: ignore[type-var]
        )
    return out
