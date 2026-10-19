"""Snapshot storage (WP-07 milestone 3): the database side of `variance.py`.

Not engine code: the API and the weekly freeze job use it; the engine modules never import it.
`keep` is first-writer-wins per (tenant, kind, period): a period's snapshot, once stored, is
what every later check compares against, even if the ledger changes afterwards.
"""

from __future__ import annotations

import json
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.engines.analysis.models import SnapshotRow
from app.engines.analysis.variance import Snapshot, SnapshotKind


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
