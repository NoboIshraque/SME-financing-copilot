"""The database side of the analysis engine (WP-07): ledgers, snapshots, comparisons.

Not engine code: the API and the nightly freeze job use it; the engine modules never import it.

- `ledger_for` reads one tenant's typed records from the fact ledger (cached per ledger
  revision) and anchors them with WP-01's `opening_balance` fact for the day a figure starts
  from, so every cash figure cites one stored fact instead of every earlier transaction.
- `keep` is first-writer-wins per (tenant, kind, period): a period's snapshot, once stored, is
  what every later check compares against, even if the ledger changes afterwards.
- `ensure_snapshots` freezes what is due (marked `reconstructed` when frozen after its period
  began) and returns the snapshots with the ledger to compare them against.
"""

from __future__ import annotations

import json
import threading
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contracts import (
    Bill,
    Fact,
    Granularity,
    Invoice,
    Period,
    RecurringObligation,
    Transaction,
)
from app.engines.analysis.ledger import Ledger, NotEnoughData
from app.engines.analysis.models import ComparisonRow, SnapshotRow
from app.engines.analysis.variance import (
    Snapshot,
    SnapshotKind,
    due_dates,
    freeze,
    target_period,
)
from app.engines.cash.calendar import Festival
from app.facts import FactStore, NotComputable, compute

KNOWN_FACTS = ("stock_value", "loan_outstanding", "interest_expense")
CHECKS = {SnapshotKind.weekly: 8, SnapshotKind.quarterly: 4}  # how many past periods to check
CACHE_SIZE = 8


# ---------------------------------------------------------------- ledgers


@dataclass(frozen=True)
class Records:
    transactions: tuple[Transaction, ...]
    invoices: tuple[Invoice, ...]
    bills: tuple[Bill, ...]
    obligations: tuple[RecurringObligation, ...]
    facts: tuple[Fact, ...]

    @property
    def first_day(self) -> date:
        return min(t.day for t in self.transactions)

    @property
    def last_day(self) -> date:
        return max(t.day for t in self.transactions)


_cache: OrderedDict[tuple[int, str, int], tuple[object, Records]] = OrderedDict()
_lock = threading.Lock()


def records(store: FactStore, tenant_id: str) -> Records:
    """Every typed record of a tenant, read once per ledger revision."""
    bind = store.session.get_bind()
    key = (id(bind), tenant_id, store.revision(tenant_id))
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key][1]
    txns = tuple(store.transactions(tenant_id))
    if not txns:
        raise NotEnoughData("transactions")
    found = Records(transactions=txns, invoices=tuple(store.invoices(tenant_id)),
                    bills=tuple(store.bills(tenant_id)),
                    obligations=tuple(store.obligations(tenant_id)),
                    facts=tuple(f for metric in KNOWN_FACTS
                                for f in store.facts(tenant_id, metric)))
    with _lock:
        _cache[key] = (bind, found)  # the bind is kept so its id stays unique
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return found


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def ledger_for(store: FactStore, tenant_id: str, period: Period) -> Ledger:
    """The tenant's ledger anchored at the start of `period` (WP-01 `opening_balance`)."""
    found = records(store, tenant_id)
    try:
        anchor = compute(store, tenant_id, "opening_balance", period)
    except NotComputable as exc:
        raise NotEnoughData("the balance the ledger starts from (initial_balance) on or "
                            f"before {period.start.isoformat()}", exc.reason_key) from exc
    return Ledger(tenant_id, anchor, found.transactions, found.invoices, found.bills,
                  found.obligations, found.facts)


def day_period(day: date) -> Period:
    return Period(start=day, end=day, granularity=Granularity.day)


def latest_ledger(store: FactStore, tenant_id: str) -> Ledger:
    """Anchored the day after the last transaction: where forecasts start."""
    return ledger_for(store, tenant_id,
                      day_period(records(store, tenant_id).last_day + timedelta(days=1)))


# ---------------------------------------------------------------- snapshots


def _snapshot(row: SnapshotRow) -> Snapshot:
    return Snapshot.from_payload(json.loads(row.payload))


def stored(session: Session, tenant_id: str, kind: SnapshotKind,
           period_start: date) -> Snapshot | None:
    row = session.scalar(select(SnapshotRow).where(
        SnapshotRow.tenant_id == tenant_id, SnapshotRow.kind == kind.value,
        SnapshotRow.period_start == period_start))
    return _snapshot(row) if row is not None else None


def keep(session: Session, snapshot: Snapshot) -> Snapshot:
    """Store `snapshot` unless its period already has one; return the one on record."""
    existing = stored(session, snapshot.tenant_id, snapshot.kind, snapshot.period.start)
    if existing is not None:
        return existing
    row = SnapshotRow(id=snapshot.id, tenant_id=snapshot.tenant_id, kind=snapshot.kind.value,
                      as_of=snapshot.as_of, period_start=snapshot.period.start,
                      period_end=snapshot.period.end, frozen_at=snapshot.frozen_at,
                      reconstructed=snapshot.reconstructed,
                      payload=json.dumps(snapshot.payload(), sort_keys=True))
    try:
        with session.begin_nested():
            session.add(row)
    except IntegrityError:  # a concurrent writer froze this period first
        found = stored(session, snapshot.tenant_id, snapshot.kind, snapshot.period.start)
        if found is None:
            raise
        return found
    return snapshot


def history(session: Session, tenant_id: str, kind: SnapshotKind) -> list[Snapshot]:
    """Every stored snapshot of one kind for a tenant, oldest period first."""
    rows = session.scalars(select(SnapshotRow).where(
        SnapshotRow.tenant_id == tenant_id, SnapshotRow.kind == kind.value)
        .order_by(SnapshotRow.period_start)).all()
    return [_snapshot(row) for row in rows]


def ensure_snapshots(session: Session, store: FactStore, tenant_id: str, kind: SnapshotKind,
                     festivals: Sequence[Festival], now: datetime, today: date
                     ) -> list[tuple[Snapshot, Ledger]]:
    """The snapshots of the last `CHECKS[kind]` periods and the current one, freezing any that
    is missing and can be made, each with its ledger anchored at its period's start."""
    found = records(store, tenant_id)
    out = []
    for as_of in due_dates(kind, found.first_day, found.last_day)[-(CHECKS[kind] + 1):]:
        period = target_period(kind, as_of)
        ledger = ledger_for(store, tenant_id, period)
        snapshot = stored(session, tenant_id, kind, period.start)
        if snapshot is None:
            try:
                snapshot = keep(session, freeze(ledger, kind, as_of, festivals, now, today))
            except NotEnoughData:
                continue
        out.append((snapshot, ledger))
    return out


# ---------------------------------------------------------------- comparisons


def remember_comparison(session: Session, comparison_id: str, tenant_id: str,
                        request: dict[str, Any], now: datetime) -> None:
    if session.get(ComparisonRow, comparison_id) is not None:
        return
    try:
        with session.begin_nested():
            session.add(ComparisonRow(id=comparison_id, tenant_id=tenant_id,
                                      request=json.dumps(request, sort_keys=True),
                                      created_at=now))
    except IntegrityError:
        pass  # the same request, stored by a concurrent call


def comparison_request(session: Session, comparison_id: str,
                       tenant_id: str) -> dict[str, Any] | None:
    """The stored request, or None (also for another tenant's id: no existence oracle)."""
    row = session.get(ComparisonRow, comparison_id)
    if row is None or row.tenant_id != tenant_id:
        return None
    return json.loads(row.request)
