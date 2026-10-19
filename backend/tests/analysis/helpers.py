"""Builders for analysis-engine tests."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.contracts import (
    Bill,
    Channel,
    DataMode,
    Direction,
    DocumentStatus,
    Fact,
    Frequency,
    Granularity,
    Invoice,
    Money,
    ObligationKind,
    Period,
    RecurringObligation,
    Transaction,
    TxCategory,
    Unit,
)
from app.engines.analysis.ledger import Ledger
from app.facts.seed import INITIAL_BALANCE, PROFILE_REF, _raw
from app.facts.store import fact_id

DHAKA = ZoneInfo("Asia/Dhaka")
T = "tenant_a"
S = DataMode.synthetic
START = date(2026, 1, 1)
_counter = iter(range(1, 10**9))


def txn(day: date, amount, category: TxCategory = TxCategory.sales, direction: str = "inflow",
        party: str | None = None, tenant: str = T) -> Transaction:
    n = next(_counter)
    return Transaction(id=f"{tenant}-T{n}", tenant_id=tenant,
                       occurred_at=datetime.combine(day, time(12), DHAKA),
                       amount=Money.of(amount), direction=Direction(direction),
                       channel=Channel.cash, category=category, counterparty_token=party,
                       source_ref=f"book.csv#L{n}", data_mode=S)


def out(day: date, amount, category: TxCategory, party: str | None = None) -> Transaction:
    return txn(day, amount, category, "outflow", party)


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


def emi(amount=10000, start=START) -> RecurringObligation:
    n = next(_counter)
    return RecurringObligation(id=f"{T}:OBL-{n}", tenant_id=T, kind=ObligationKind.emi,
                               counterparty_token="PARTY_bank000001", amount=Money.of(amount),
                               frequency=Frequency.monthly, day_of_period=10, start_date=start,
                               source_ref=f"obligations.csv#L{n}", data_mode=S)


def anchor(value="10000", day: date = START, tenant: str = T) -> Fact:
    return _raw(tenant, INITIAL_BALANCE, Decimal(value), Unit.BDT, day, PROFILE_REF)


def known(metric: str, value, day: date, granularity=Granularity.day, end: date | None = None
          ) -> Fact:
    period = Period(start=day, end=end or day, granularity=granularity)
    ref = f"upload.csv#{metric}"
    return Fact(id=fact_id(T, metric, period, None, 0, Decimal(str(value)), (ref,)),
                tenant_id=T, metric=metric, value=Decimal(str(value)), unit=Unit.BDT,
                period=period, source_refs=(ref,), data_mode=S)


def ledger(transactions=(), invoices=(), bills=(), obligations=(), facts=(),
           opening="10000", day: date = START) -> Ledger:
    return Ledger(T, anchor(opening, day), tuple(transactions), tuple(invoices), tuple(bills),
                  tuple(obligations), tuple(facts))


def universe_ledger(universe, sme_id: str) -> Ledger:
    sme = universe.smes[sme_id]
    return Ledger(sme_id, anchor(str(sme.opening_total.amount), universe.start, sme_id),
                  sme.transactions, sme.invoices, sme.bills, sme.obligations)


def month(year: int, month_: int) -> Period:
    from app.engines.analysis.ledger import calendar_period
    return calendar_period(date(year, month_, 1), Granularity.month)
