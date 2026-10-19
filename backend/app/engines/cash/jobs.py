"""Daily cash-alert scan (WP-04), discovered by `app.worker`.

For every tenant with a ledger: compute today's alerts (the same pipeline as
`GET /api/cash/alerts`), decide with `alerts.deliver` against what was already sent (dedupe
> 3 days / > 10%, per-tier cooldown, weekly indicator digest), and record each delivery in
`cash_sent_alerts`. Sending email and the weekly digest is WP-12's; until it lands, a delivery
is recorded and logged with its channels, which is what dedupe and cooldown need.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import distinct, select
from sqlalchemy.orm import Session

from app.engines.cash.alerts import SentAlert, deliver
from app.engines.cash.models import SentAlertRow
from app.facts import FactStore
from app.facts.models import LedgerTransactionRow
from app.settings import Settings, get_settings
from app.worker import Job

log = logging.getLogger("hishab.cash")


def scan_tenant(db: Session, tenant_id: str, now: datetime) -> list[SentAlertRow]:
    """Deliver what is due for one tenant; returns the rows recorded."""
    from app.api.cash import Abstain, compute_alerts  # the API owns the store-backed pipeline

    try:
        result = compute_alerts(FactStore(db), tenant_id, now)
    except Abstain:
        return []
    rows = db.scalars(select(SentAlertRow).where(SentAlertRow.tenant_id == tenant_id)
                      .order_by(SentAlertRow.seq)).all()
    sent = [row.as_sent() for row in rows]
    gaps = {f"gap:{g.gap.first_breach_day.isoformat()}": g for g in result.gaps}
    as_of = result.analysis.as_of
    recorded = []
    for alert in result.alerts:
        gap = gaps.get(alert.dedupe_key)
        decision = deliver(alert, gap, as_of, sent, now)
        if not decision.send:
            continue
        mark = SentAlert.of(alert.model_copy(update={"created_at": now}), gap, as_of)
        row = SentAlertRow(tenant_id=tenant_id, alert_id=alert.id, dedupe_key=mark.dedupe_key,
                           tier=mark.tier.value, sent_at=now,
                           first_breach_day=mark.first_breach_day,
                           last_gap_day=mark.last_gap_day,
                           expected_shortfall=mark.expected_shortfall,
                           channels=",".join(decision.channels), reason_key=decision.reason_key)
        db.add(row)
        sent.append(mark)
        recorded.append(row)
        log.info("cash alert %s for %s via %s (%s)", alert.id, tenant_id, row.channels,
                 decision.reason_key)
    db.flush()
    return recorded


def scan_alerts(settings: Settings | None = None, now: datetime | None = None) -> int:
    from app.db import init_db, make_engine, session_factory

    settings = settings or get_settings()
    now = now or datetime.now(UTC)
    engine = make_engine(settings.database_url)
    try:
        init_db(engine)
        with session_factory(engine)() as db:
            tenants = db.scalars(select(distinct(LedgerTransactionRow.tenant_id))).all()
            count = sum(len(scan_tenant(db, tenant, now)) for tenant in sorted(tenants))
            db.commit()
            return count
    finally:
        engine.dispose()


JOBS = [Job(name="cash.alert_scan", func=scan_alerts, cron={"hour": 7, "minute": 30})]
