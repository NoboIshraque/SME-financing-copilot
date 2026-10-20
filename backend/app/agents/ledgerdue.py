"""Money falling due, in and out, read from the typed ledger (Session A; FEATURES Q2).

    upcoming(bills, obligations, as_of)  -> [Due]   what the shop pays next, soonest first
    owed(invoices, as_of)                -> Owed    what customers owe it, who to chase first

Pure functions over contracts, so the tool adapters (toolset.py) and the checker run the same
code on the same ledger rows: the checker re-reads the rows and recomputes every figure.

Upcoming payments are the open bills due within the window (an overdue bill is listed first,
it is already due) and every occurrence of a recurring obligation (rent, salaries, utilities,
loan instalments) inside the window. Suppliers and customers are labelled "Supplier N" and
"Customer N" (stable per tenant, as the receivables screen), never by name.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.contracts import Bill, DocumentStatus, Invoice, RecurringObligation
from app.engines.cash.baseline import obligation_days
from app.engines.receivables import aging as aging_mod
from app.engines.receivables import risk

WINDOW_DAYS = 31  # a month ahead, month-end salaries included
PAYABLES_FORMULA = "copilot.upcoming_payments"
RECEIVABLES_FORMULA = "copilot.receivables_owed"
LOANS_FORMULA = "copilot.loans_on_record"  # loans the shop is repaying: its EMI obligations
FORMULA_VERSION = 1
CLOSED = (DocumentStatus.paid, DocumentStatus.written_off)


@dataclass(frozen=True)
class Due:
    ref: str  # "bill:<id>" or "obl:<id>@<day>": the ledger row it is read from
    day: date
    amount: Decimal
    kind: str  # "bill", or the obligation kind (rent, salary, emi, utility, ...)
    counterparty_token: str
    overdue: bool = False


def labels(tokens: Iterable[str], word: str) -> dict[str, str]:
    """token -> "<word> N", numbered in token order (stable per tenant)."""
    return {token: f"{word} {i}" for i, token in enumerate(sorted(set(tokens)), start=1)}


def upcoming(bills: Iterable[Bill], obligations: Iterable[RecurringObligation], as_of: date,
             days: int = WINDOW_DAYS) -> list[Due]:
    """Payments due from the day after `as_of` to `as_of + days`, plus bills already overdue."""
    start, end = as_of + timedelta(days=1), as_of + timedelta(days=days)
    out: list[Due] = []
    for bill in bills:
        if bill.status in CLOSED or bill.outstanding.amount <= 0:
            continue
        if bill.issue_date > as_of or bill.due_date > end:
            continue
        out.append(Due(f"bill:{bill.id}", bill.due_date, bill.outstanding.amount, "bill",
                       bill.counterparty_token, overdue=bill.due_date <= as_of))
    for obligation in obligations:
        for day in obligation_days(obligation, start, end):
            out.append(Due(f"obl:{obligation.id}@{day.isoformat()}", day,
                           obligation.amount.amount, obligation.kind.value,
                           obligation.counterparty_token))
    return sorted(out, key=lambda d: (d.day, -d.amount, d.ref))


@dataclass(frozen=True)
class CustomerOwed:
    token: str
    amount: Decimal  # open on all their invoices
    oldest_due: date
    overdue: bool
    risk: Decimal  # WP-05 risk score of their riskiest open invoice
    invoice_ids: tuple[str, ...]


@dataclass(frozen=True)
class Owed:
    open_total: Decimal
    overdue_total: Decimal
    open_ids: tuple[str, ...]
    overdue_ids: tuple[str, ...]
    customers: tuple[CustomerOwed, ...]  # chase first: overdue, riskiest, largest


def owed(invoices: Sequence[Invoice], as_of: date) -> Owed:
    open_docs = [inv for inv in invoices if aging_mod.is_open(inv, as_of)]
    overdue = [inv for inv in open_docs if aging_mod.days_overdue(inv, as_of) > 0]
    scores = risk.score_all(invoices, aging_mod.histories(invoices, as_of), as_of)
    by_customer: dict[str, list[Invoice]] = defaultdict(list)
    for inv in open_docs:
        by_customer[inv.counterparty_token].append(inv)
    customers = []
    for token, docs in by_customer.items():
        late = any(aging_mod.days_overdue(d, as_of) > 0 for d in docs)
        worst = max((scores[d.id].score for d in docs if d.id in scores), default=Decimal(0))
        customers.append(CustomerOwed(
            token=token, amount=sum((aging_mod.open_amount(d).amount for d in docs), Decimal(0)),
            oldest_due=min(d.due_date for d in docs), overdue=late, risk=worst,
            invoice_ids=tuple(sorted(d.id for d in docs))))
    customers.sort(key=lambda c: (not c.overdue, -c.risk, -c.amount, c.token))
    return Owed(open_total=sum((aging_mod.open_amount(i).amount for i in open_docs), Decimal(0)),
                overdue_total=sum((aging_mod.open_amount(i).amount for i in overdue), Decimal(0)),
                open_ids=tuple(sorted(i.id for i in open_docs)),
                overdue_ids=tuple(sorted(i.id for i in overdue)), customers=tuple(customers))
