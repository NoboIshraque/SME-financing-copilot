"""Server-side sessions in an HttpOnly, SameSite=Strict cookie (WP-11 milestone 1).

The cookie holds 256 random bits; the database holds only their SHA-256, so a leaked sessions
table cannot be replayed. Sessions end after 30 idle minutes or 12 hours, whichever is first.
A password-verified sign-in that still owes its TOTP code gets a separate `totp_pending`
session that lasts 5 minutes and opens nothing but the TOTP step. Every sign-in issues a new
token (no session fixation).
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.security.models import SessionRow
from app.settings import AppEnv, Settings

COOKIE_NAME = "hishab_session"
COOKIE_PATH = "/api"
IDLE_TIMEOUT = timedelta(minutes=30)
ABSOLUTE_TIMEOUT = timedelta(hours=12)
PENDING_TIMEOUT = timedelta(minutes=5)
TOUCH_EVERY = timedelta(minutes=1)  # write last_seen_at at most once a minute
MAX_TOKEN_LENGTH = 128


class Stage(StrEnum):
    active = "active"
    totp_pending = "totp_pending"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def lifetime(stage: Stage) -> timedelta:
    return ABSOLUTE_TIMEOUT if stage is Stage.active else PENDING_TIMEOUT


class SessionStore:
    def __init__(self, db: Session) -> None:
        self.db = db

    def issue(self, user_id: str, stage: Stage, now: datetime) -> tuple[str, SessionRow]:
        token = secrets.token_urlsafe(32)
        row = SessionRow(token_hash=hash_token(token), user_id=user_id, stage=stage.value,
                         created_at=now, last_seen_at=now, expires_at=now + lifetime(stage))
        self.db.add(row)
        self.db.flush()
        return token, row

    def find(self, token: str | None, now: datetime, stage: Stage = Stage.active
             ) -> SessionRow | None:
        if not token or len(token) > MAX_TOKEN_LENGTH:
            return None
        row = self.db.get(SessionRow, hash_token(token))
        if row is None or row.revoked_at is not None or row.stage != stage.value:
            return None
        if now >= row.expires_at or (stage is Stage.active
                                     and now - row.last_seen_at >= IDLE_TIMEOUT):
            row.revoked_at = now
            self.db.flush()
            return None
        if now - row.last_seen_at >= TOUCH_EVERY:
            row.last_seen_at = now
            self.db.flush()
        return row

    def revoke(self, token: str | None, now: datetime) -> bool:
        if not token or len(token) > MAX_TOKEN_LENGTH:
            return False
        row = self.db.get(SessionRow, hash_token(token))
        if row is None or row.revoked_at is not None:
            return False
        row.revoked_at = now
        self.db.flush()
        return True

    def revoke_user(self, user_id: str, now: datetime, *, keep: str | None = None) -> int:
        """Revoke every live session of a user (password change, deactivation), optionally
        keeping the one making the request. Returns how many were revoked."""
        keep_hash = hash_token(keep) if keep else None
        rows = self.db.scalars(select(SessionRow).where(SessionRow.user_id == user_id,
                                                        SessionRow.revoked_at.is_(None)))
        count = 0
        for row in rows:
            if row.token_hash != keep_hash:
                row.revoked_at = now
                count += 1
        self.db.flush()
        return count


def cookie_secure(settings: Settings) -> bool:
    """Secure (HTTPS-only) wherever the app is deployed; plain HTTP only on a developer PC."""
    return settings.app_env in (AppEnv.demo, AppEnv.production)


def cookie_attributes(settings: Settings) -> dict[str, object]:
    return {"httponly": True, "samesite": "strict", "secure": cookie_secure(settings),
            "path": COOKIE_PATH}
