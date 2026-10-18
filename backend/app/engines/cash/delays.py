"""When open invoices get paid: each customer's own payment-delay history (WP-04).

Delay = paid date - due date, from documents settled on or before `as_of` only. A customer with
fewer than `MIN_HISTORY` settled documents borrows the tenant-wide distribution. For an open
document the distribution is conditioned on what is known: it is still unpaid on `as_of`, so
delays that would have put the payment in the past are dropped. When no observed delay is left
(the customer is later than ever before), the document is not expected within the evidence and
contributes nothing: the forecast prefers to under-count cash rather than invent it.

(WP-17's LightGBM delay model scored MAE 2.92 days against 2.83 for the per-customer history
on its time-split test, so the empirical distribution is the default here.)
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.contracts import Bill, DocumentStatus, Invoice

MIN_HISTORY = 3
ZERO = Decimal(0)


def outstanding_on(doc: Invoice | Bill, day: date) -> Decimal:
    """What was still owed on a document at the end of `day` (0 if issued later). A document
    settled after `day` counts in full; undated partial payments count as already made."""
    if doc.issue_date > day or doc.status is DocumentStatus.written_off:
        return ZERO
    if doc.paid_date is not None and doc.paid_date > day:
        return doc.amount.amount
    return doc.outstanding.amount


def settled_by(doc: Invoice | Bill, day: date) -> bool:
    return doc.paid_date is not None and doc.paid_date <= day and doc.amount_paid == doc.amount


@dataclass(frozen=True)
class DelayTable:
    by_party: Mapping[str, tuple[int, ...]]
    overall: tuple[int, ...]
    issue_to_paid: tuple[int, ...]

    @classmethod
    def from_documents(cls, documents: Iterable[Invoice | Bill], as_of: date) -> DelayTable:
        by_party: dict[str, list[int]] = {}
        overall: list[int] = []
        issue_to_paid: list[int] = []
        for doc in documents:
            if not settled_by(doc, as_of):
                continue
            assert doc.paid_date is not None
            delay = (doc.paid_date - doc.due_date).days
            by_party.setdefault(doc.counterparty_token, []).append(delay)
            overall.append(delay)
            issue_to_paid.append((doc.paid_date - doc.issue_date).days)
        return cls({k: tuple(sorted(v)) for k, v in by_party.items()}, tuple(sorted(overall)),
                   tuple(sorted(issue_to_paid)))

    def delays_for(self, party: str) -> tuple[int, ...]:
        own = self.by_party.get(party, ())
        return own if len(own) >= MIN_HISTORY else self.overall

    def payment_days(self, doc: Invoice | Bill, as_of: date) -> list[tuple[date, Decimal]]:
        """(day, probability) of payment for a document still open on `as_of`."""
        possible = [d for d in self.delays_for(doc.counterparty_token)
                    if doc.due_date + timedelta(days=d) > as_of]
        if not possible:
            return []
        counts = Counter(doc.due_date + timedelta(days=d) for d in possible)
        total = Decimal(len(possible))
        return sorted((day, Decimal(n) / total) for day, n in counts.items())

    def paid_within(self, days: int) -> Decimal:
        """Share of documents paid within `days` of being issued (for documents not yet issued)."""
        if not self.issue_to_paid:
            return ZERO
        return Decimal(sum(1 for d in self.issue_to_paid if d <= days)) / len(self.issue_to_paid)
