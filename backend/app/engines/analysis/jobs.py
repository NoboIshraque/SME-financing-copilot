"""Nightly forecast-snapshot freeze (WP-07; FEATURES N1), discovered by `app.worker`.

For every tenant with a ledger, freeze the weekly and quarterly snapshots that are due (the
same `ensure_snapshots` that `GET /api/analysis/variance` uses). Run at the end of each Dhaka
day, a snapshot for the week or quarter starting tomorrow is frozen on time; one the scan could
only make later (the books were uploaded after the period began) is marked `reconstructed`.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import distinct, select
from sqlalchemy.orm import Session

from app.engines.analysis.ledger import NotEnoughData
from app.engines.analysis.store import ensure_snapshots, history
from app.engines.analysis.variance import SnapshotKind
from app.engines.cash.calendar import load_festivals
from app.facts import FactStore
from app.facts.models import LedgerTransactionRow
from app.settings import Settings, get_settings
from app.worker import Job

log = logging.getLogger("hishab.analysis")
DHAKA = ZoneInfo("Asia/Dhaka")


def freeze_tenant(db: Session, tenant_id: str, now: datetime) -> int:
    """Freeze what is due for one tenant; returns how many snapshots were stored."""
    store, festivals, today = FactStore(db), load_festivals(), now.astimezone(DHAKA).date()
    stored = 0
    for kind in SnapshotKind:
        before = len(history(db, tenant_id, kind))
        try:
            ensure_snapshots(db, store, tenant_id, kind, festivals, now, today)
        except NotEnoughData as exc:
            log.info("no %s snapshot for %s: needs %s", kind.value, tenant_id, exc.missing)
            continue
        stored += len(history(db, tenant_id, kind)) - before
    return stored


def freeze_snapshots(settings: Settings | None = None, now: datetime | None = None) -> int:
    from app.db import init_db, make_engine, session_factory

    settings = settings or get_settings()
    now = now or datetime.now(UTC)
    engine = make_engine(settings.database_url)
    try:
        init_db(engine)
        with session_factory(engine)() as db:
            tenants = db.scalars(select(distinct(LedgerTransactionRow.tenant_id))).all()
            count = sum(freeze_tenant(db, tenant, now) for tenant in sorted(tenants))
            db.commit()
            return count
    finally:
        engine.dispose()


JOBS = [Job(name="analysis.snapshot_freeze", func=freeze_snapshots,
            cron={"hour": 23, "minute": 45})]
