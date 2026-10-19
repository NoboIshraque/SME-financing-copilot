"""Builders for cash-engine tests."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.contracts import (
    Bill,
    Channel,
    DataMode,
    Direction,
    DocumentStatus,
    Frequency,
    Invoice,
    Money,
    ObligationKind,
    RecurringObligation,
    Transaction,
    TxCategory,
)

DHAKA = ZoneInfo("Asia/Dhaka")
T = "tenant_a"
S = DataMode.synthetic
AS_OF = date(2026, 9, 30)
_counter = iter(range(1, 10**9))


def txn(day: date, amount, direction: str = "inflow", category: TxCategory = TxCategory.sales,
        party: str | None = None) -> Transaction:
    n = next(_counter)
    return Transaction(id=f"{T}-T{n}", tenant_id=T,
                       occurred_at=datetime.combine(day, time(12), DHAKA),
                       amount=Money.of(amount), direction=Direction(direction),
                       channel=Channel.cash, category=category, counterparty_token=party,
                       source_ref=f"book.csv#L{n}", data_mode=S)


def daily(start: date, days: int, amount_for) -> list[Transaction]:
    """One sales transaction per day where amount_for(day) is positive."""
    out = []
    for i in range(days):
        day = start + timedelta(days=i)
        amount = amount_for(day)
        if amount:
            out.append(txn(day, amount))
    return out


def _doc(cls, number: str, issue: date, due: date, amount, paid="0", paid_date=None,
         party="PARTY_cust000001", status=None):
    paid_d = Decimal(str(paid))
    if status is None:
        status = (DocumentStatus.paid if paid_d == Decimal(str(amount)) else
                  DocumentStatus.partially_paid if paid_d > 0 else DocumentStatus.open)
    return cls(id=f"{T}:{number}", tenant_id=T, counterparty_token=party, issue_date=issue,
               due_date=due, amount=Money.of(amount), amount_paid=Money.of(paid), status=status,
               paid_date=paid_date, source_ref=f"register.csv#{number}", data_mode=S)


def invoice(number, issue, due, amount, **kw) -> Invoice:
    return _doc(Invoice, number, issue, due, amount, **kw)


def bill(number, issue, due, amount, **kw) -> Bill:
    return _doc(Bill, number, issue, due, amount, party=kw.pop("party", "PARTY_supp000001"), **kw)


def paid_invoice(number, due: date, delay: int, amount=100, party="PARTY_cust000001") -> Invoice:
    issue = due - timedelta(days=15)
    return invoice(number, issue, due, amount, paid=amount, paid_date=due + timedelta(days=delay),
                   party=party)


def obligation(kind=ObligationKind.rent, amount=35000, frequency=Frequency.monthly, day=5,
               start=date(2025, 1, 1), end=None) -> RecurringObligation:
    n = next(_counter)
    return RecurringObligation(id=f"{T}:OBL-{n}", tenant_id=T, kind=kind,
                               counterparty_token="PARTY_land000001", amount=Money.of(amount),
                               frequency=frequency, day_of_period=day, start_date=start,
                               end_date=end, source_ref=f"obligations.csv#L{n}", data_mode=S)
