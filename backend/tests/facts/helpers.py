"""Small builders for fact ledger tests."""

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
    Granularity,
    Invoice,
    Money,
    Period,
    Provenance,
    Transaction,
    TxCategory,
    Unit,
)
from app.facts.store import fact_id

DHAKA = ZoneInfo("Asia/Dhaka")
T = "tenant_a"
SEP = Period(start=date(2026, 9, 1), end=date(2026, 9, 30))
S = DataMode.synthetic


def txn(n: int, day: date, amount: str | int, direction: str = "inflow",
        category: TxCategory = TxCategory.sales, tenant: str = T) -> Transaction:
    return Transaction(
        id=f"{tenant}-T{n}", tenant_id=tenant,
        occurred_at=datetime.combine(day, time(10, 0), tzinfo=DHAKA),
        amount=Money.of(amount), direction=Direction(direction), channel=Channel.bkash,
        category=category, source_ref=f"bkash.csv#L{n}", data_mode=S,
    )


def _doc(cls, n, issue, amount, paid="0", paid_date=None, tenant=T):
    status = DocumentStatus.open
    if Decimal(str(paid)) == Decimal(str(amount)):
        status = DocumentStatus.paid
    elif Decimal(str(paid)) > 0:
        status = DocumentStatus.partially_paid
    return cls(
        id=f"{tenant}:{cls.__name__[:3].upper()}-{n}", tenant_id=tenant,
        counterparty_token="PARTY_0000000001", issue_date=issue,
        due_date=issue.replace(day=min(issue.day + 14, 28)), amount=Money.of(amount),
        amount_paid=Money.of(paid), status=status, paid_date=paid_date,
        source_ref=f"{cls.__name__.lower()}s.csv#L{n}", data_mode=S,
    )


def invoice(n: int, issue: date, amount, paid="0", paid_date=None, tenant=T) -> Invoice:
    return _doc(Invoice, n, issue, amount, paid, paid_date, tenant)


def bill(n: int, issue: date, amount, paid="0", paid_date=None, tenant=T) -> Bill:
    return _doc(Bill, n, issue, amount, paid, paid_date, tenant)


def raw_fact(metric: str, value: str, period: Period = SEP, entity: str | None = None,
             tenant: str = T, refs: tuple[str, ...] = ("src.csv#L1",),
             provenance: Provenance | None = None) -> Fact:
    version = provenance.formula_version if provenance else 0
    return Fact(
        id=fact_id(tenant, metric, period, entity, version, value, refs),
        tenant_id=tenant, metric=metric, value=Decimal(value), unit=Unit.BDT, period=period,
        entity_token=entity, provenance=provenance, source_refs=refs, data_mode=S,
    )


def month(year: int, mon: int, granularity: Granularity = Granularity.month) -> Period:
    end = (date(year + mon // 12, mon % 12 + 1, 1) - date.resolution)
    return Period(start=date(year, mon, 1), end=end, granularity=granularity)
