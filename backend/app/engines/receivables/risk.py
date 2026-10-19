"""Risk score per open invoice (WP-05 milestone 2; FEATURES Q2).

Empirical, explainable, 0-100 (WP-17's delay model is not wired in). Points per factor:
  risk.days_late           40 x min(days overdue, 90) / 90
  risk.history_slow        25 x share of the customer's paid invoices that were paid late
                         + 15 x min(median days late, 60) / 60
  risk.amount_above_usual  10 x min(amount / usual amount - 1, 2) / 2   (only when above usual)
  risk.many_open           10 x min(other open invoices of the customer, 5) / 5
  risk.disputed            +20 when the invoice is disputed
  risk.recent_payment      -10 when the customer paid something in the last 14 days
A customer with no paid history gets 10 points of uncertainty (no factor key: nothing is
known). The score never falls when lateness rises (property-tested). The top 3 positive
factors explain it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.contracts import DocumentStatus, Invoice
from app.engines.receivables.aging import History, days_overdue, is_open

FORMULA_ID = "receivables.risk_score"
NO_HISTORY_POINTS = Decimal(10)
RECENT = timedelta(days=14)


@dataclass(frozen=True)
class Risk:
    score: Decimal
    factors: tuple[tuple[str, Decimal], ...]  # positive contributions, largest first

    @property
    def factor_keys(self) -> list[str]:
        return [key for key, _ in self.factors[:3]]


def _cap(value: Decimal, top: Decimal) -> Decimal:
    return min(max(value, Decimal(0)), top)


def score(invoice: Invoice, history: History | None, *, others_open: int, as_of: date) -> Risk:
    parts: dict[str, Decimal] = {}
    parts["risk.days_late"] = 40 * _cap(Decimal(days_overdue(invoice, as_of)), Decimal(90)) / 90
    base = Decimal(0)
    if history is None or history.paid_count == 0:
        base = NO_HISTORY_POINTS
    else:
        parts["risk.history_slow"] = (25 * history.late_share
                                      + 15 * _cap(history.median_days_late, Decimal(60)) / 60)
    if history is not None and history.usual_amount:
        ratio = invoice.amount.amount / history.usual_amount - 1
        parts["risk.amount_above_usual"] = 10 * _cap(ratio, Decimal(2)) / 2
    parts["risk.many_open"] = 10 * _cap(Decimal(others_open), Decimal(5)) / 5
    if invoice.status is DocumentStatus.disputed:
        parts["risk.disputed"] = Decimal(20)
    relief = Decimal(0)
    if history is not None and history.last_paid is not None \
            and as_of - history.last_paid <= RECENT:
        relief = Decimal(10)
    total = _cap(base + sum(parts.values(), Decimal(0)) - relief, Decimal(100))
    factors = sorted(((k, v) for k, v in parts.items() if v > 0), key=lambda kv: (-kv[1], kv[0]))
    return Risk(total.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP), tuple(factors))


def score_all(invoices: Sequence[Invoice], histories: dict[str, History],
              as_of: date) -> dict[str, Risk]:
    open_by_customer: dict[str, int] = {}
    for inv in invoices:
        if is_open(inv, as_of):
            open_by_customer[inv.counterparty_token] = \
                open_by_customer.get(inv.counterparty_token, 0) + 1
    return {
        inv.id: score(inv, histories.get(inv.counterparty_token),
                      others_open=open_by_customer[inv.counterparty_token] - 1, as_of=as_of)
        for inv in invoices if is_open(inv, as_of)
    }
