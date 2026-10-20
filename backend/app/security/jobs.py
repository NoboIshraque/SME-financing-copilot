"""Scheduled jobs (WP-11): the daily audit-chain anchor, discovered by `app.worker`."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.chain.anchor import Anchorer, FallbackAnchorer, OfflineAnchorer, SepoliaAnchorer
from app.db import make_engine, session_factory
from app.security.audit import AuditLog
from app.security.clock import system_clock
from app.settings import ChainMode, Settings, get_settings
from app.worker import Job


def anchorer_for(settings: Settings) -> Anchorer:
    """Sepolia when configured, falling back to an offline anchor (labelled offline) whenever
    the testnet is unreachable or the wallet cannot pay, so the audit anchor never fails."""
    offline = OfflineAnchorer()
    rpc = settings.sepolia_rpc_url.get_secret_value()
    key = settings.sepolia_private_key.get_secret_value()
    if settings.chain_mode is ChainMode.sepolia and rpc and key:
        try:
            return FallbackAnchorer(SepoliaAnchorer.from_settings(rpc, key), offline)
        except Exception:  # a malformed key: stay offline rather than fail
            return offline
    return offline


def anchor_audit_heads(settings: Settings | None = None, now: datetime | None = None) -> str:
    settings = settings or get_settings()
    now = now or system_clock()
    day = now.astimezone(ZoneInfo(settings.timezone)).date()
    engine = make_engine(settings.database_url)
    try:
        with session_factory(engine)() as db:
            row = AuditLog(db).anchor_day(day, anchorer_for(settings), now)
            db.commit()
            return row.digest if row else ""
    finally:
        engine.dispose()


JOBS = [Job(name="security.anchor_audit_heads", func=anchor_audit_heads,
            cron={"hour": 23, "minute": 55})]
