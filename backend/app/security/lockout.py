"""Account lockout after repeated failed sign-ins (WP-11 milestone 1).

Five failures (wrong password or wrong TOTP code) within 15 minutes lock the email for
15 minutes. Attempts during a lock are refused without checking the password and do not
extend it, so an attacker cannot keep an owner locked out by hammering. Counters are keyed
by an HMAC of the normalised email and kept for unknown emails too: lockout behaves the same
whether or not an account exists, so it cannot be used to discover accounts.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.security.keys import keyed_digest
from app.security.models import LoginFailureRow

MAX_FAILURES = 5
WINDOW = timedelta(minutes=15)
LOCK_FOR = timedelta(minutes=15)


def minutes_left(remaining: timedelta) -> int:
    return max(1, math.ceil(remaining.total_seconds() / 60))


class Lockout:
    def __init__(self, db: Session, key: bytes) -> None:
        self.db = db
        self.key = key

    def email_key(self, email: str) -> str:
        return keyed_digest(self.key, email)

    def locked_for(self, email: str, now: datetime) -> timedelta | None:
        """Time left on the lock, or None when sign-in may be attempted."""
        row = self.db.get(LoginFailureRow, self.email_key(email))
        if row is None or row.locked_until is None or row.locked_until <= now:
            return None
        return row.locked_until - now

    def record_failure(self, email: str, now: datetime) -> timedelta | None:
        """Count one failure. Returns the lock duration if this failure locked the email."""
        key = self.email_key(email)
        row = self.db.get(LoginFailureRow, key)
        if row is None:
            row = LoginFailureRow(email_key=key, failures=0, window_started_at=now)
            self.db.add(row)
        if now - row.window_started_at >= WINDOW:
            row.failures, row.window_started_at = 0, now
        row.failures += 1
        locked = None
        if row.failures >= MAX_FAILURES:
            row.locked_until = now + LOCK_FOR
            row.failures, row.window_started_at = 0, now
            locked = LOCK_FOR
        self.db.flush()
        return locked

    def clear(self, email: str) -> None:
        row = self.db.get(LoginFailureRow, self.email_key(email))
        if row is not None:
            self.db.delete(row)
            self.db.flush()
