"""Time source for security decisions (sessions, lockout, TOTP, approval expiry).

Routes read the clock from `app.state.security_clock` when a test has set one, so tests move
time forward instead of sleeping. Every datetime here is timezone-aware UTC.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

Clock = Callable[[], datetime]


def system_clock() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    """Aware UTC datetime. Naive values are refused: they hide which timezone was meant."""
    if value.tzinfo is None:
        raise ValueError("naive datetime: pass a timezone-aware value")
    return value.astimezone(UTC)
