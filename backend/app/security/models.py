"""Security tables (WP-11).

Datetimes are stored as UTC and always come back timezone-aware (`UTCDateTime`), so expiry
comparisons behave the same on SQLite and PostgreSQL. No secret is stored in the clear:
passwords are argon2id hashes, TOTP secrets are AES-GCM sealed, session tokens and attempted
emails are stored only as digests.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    DDL,
    Boolean,
    Date,
    DateTime,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from app.db import Base


class UTCDateTime(TypeDecorator[datetime]):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("security tables store timezone-aware datetimes only")
        value = value.astimezone(UTC)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class TenantRow(Base):
    """A business using Hishab. `data_mode` labels synthetic demo tenants."""

    __tablename__ = "security_tenants"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    business_name: Mapped[str] = mapped_column(String(128))
    data_mode: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class UserRow(Base):
    __tablename__ = "security_users"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(32))
    display_name: Mapped[str] = mapped_column(String(128))
    password_hash: Mapped[str] = mapped_column(String(256))
    totp_nonce: Mapped[bytes | None] = mapped_column(LargeBinary(12), default=None)
    totp_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, default=None)
    totp_enrolled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Highest TOTP time step ever accepted: a code at or below it is a replay.
    totp_last_step: Mapped[int | None] = mapped_column(Integer, default=None)
    scopes: Mapped[str] = mapped_column(Text, default="[]")  # JSON list
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    password_changed_at: Mapped[datetime] = mapped_column(UTCDateTime)


class SessionRow(Base):
    """A sign-in session. Only the SHA-256 of the cookie token is stored."""

    __tablename__ = "security_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(40), index=True)
    stage: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)


class LoginFailureRow(Base):
    """Failed sign-in counter per email, keyed by an HMAC of the email (never the email),
    kept for unknown emails too so lockout does not reveal which accounts exist."""

    __tablename__ = "security_login_failures"

    email_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    window_started_at: Mapped[datetime] = mapped_column(UTCDateTime)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)


class LenderGrantRow(Base):
    """The owner's consent for one lender to see some scopes until a date (milestone 2)."""

    __tablename__ = "security_lender_grants"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(40), index=True)  # the lender_viewer account
    lender_label: Mapped[str] = mapped_column(String(80))
    purpose: Mapped[str] = mapped_column(String(200))
    scopes: Mapped[str] = mapped_column(Text)  # JSON list
    consented_by: Mapped[str] = mapped_column(String(40))
    consented_at: Mapped[datetime] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)


class ApprovalRow(Base):
    """An owner approval for one exact action card (milestone 3). The card is stored with its
    digest; execution refuses a card that no longer matches."""

    __tablename__ = "security_approvals"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    action_card_id: Mapped[str] = mapped_column(String(128))
    action_type: Mapped[str] = mapped_column(String(48))
    tier: Mapped[str] = mapped_column(String(16))
    card_json: Mapped[str] = mapped_column(Text)
    card_digest: Mapped[str] = mapped_column(String(64))
    requested_by: Mapped[str] = mapped_column(String(40))
    decided_by: Mapped[str | None] = mapped_column(String(40), default=None)
    status: Mapped[str] = mapped_column(String(16), index=True)
    step_up_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    executed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    execution_key: Mapped[str | None] = mapped_column(String(128), default=None)
    result_json: Mapped[str | None] = mapped_column(Text, default=None)


class AuditRow(Base):
    """One link of a tenant's append-only, SHA-256 hash-chained audit log (milestone 4).

    `details` is the redacted JSON whose SHA-256 is `details_digest` (ids, counts and digests,
    never personal data). UPDATE and DELETE are refused by the ORM and by database triggers.
    """

    __tablename__ = "security_audit"

    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    at: Mapped[datetime] = mapped_column(UTCDateTime)
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64), index=True)
    tier: Mapped[str | None] = mapped_column(String(16), default=None)
    target: Mapped[str | None] = mapped_column(String(128), default=None)
    details: Mapped[str] = mapped_column(Text)
    details_digest: Mapped[str] = mapped_column(String(64))
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class AuditAnchorRow(Base):
    """A day's audit heads (one per tenant) committed to one digest and anchored on chain."""

    __tablename__ = "security_audit_anchors"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    digest: Mapped[str] = mapped_column(String(64))
    heads: Mapped[str] = mapped_column(Text)  # JSON [[tenant_id, seq, hash], ...]
    chain: Mapped[str] = mapped_column(String(16))
    tx_hash: Mapped[str | None] = mapped_column(String(80), default=None)
    block_number: Mapped[int | None] = mapped_column(Integer, default=None)
    explorer_url: Mapped[str | None] = mapped_column(String(200), default=None)
    anchored_at: Mapped[datetime] = mapped_column(UTCDateTime)


class AppendOnlyViolation(RuntimeError):
    pass


@event.listens_for(AuditRow, "before_update")
def _refuse_update(_mapper: object, _connection: object, _target: object) -> None:
    raise AppendOnlyViolation("the audit log is append-only: rows are never updated")


@event.listens_for(AuditRow, "before_delete")
def _refuse_delete(_mapper: object, _connection: object, _target: object) -> None:
    raise AppendOnlyViolation("the audit log is append-only: rows are never deleted")


_SQLITE_TRIGGERS = [
    "CREATE TRIGGER security_audit_no_update BEFORE UPDATE ON security_audit "
    "BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END",
    "CREATE TRIGGER security_audit_no_delete BEFORE DELETE ON security_audit "
    "BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END",
]
_POSTGRES_TRIGGERS = [
    "CREATE OR REPLACE FUNCTION security_audit_append_only() RETURNS trigger AS $$ "
    "BEGIN RAISE EXCEPTION 'audit log is append-only'; END; $$ LANGUAGE plpgsql",
    "CREATE TRIGGER security_audit_no_change BEFORE UPDATE OR DELETE ON security_audit "
    "FOR EACH ROW EXECUTE FUNCTION security_audit_append_only()",
    "CREATE TRIGGER security_audit_no_truncate BEFORE TRUNCATE ON security_audit "
    "FOR EACH STATEMENT EXECUTE FUNCTION security_audit_append_only()",
]
for _statement in _SQLITE_TRIGGERS:
    event.listen(AuditRow.__table__, "after_create", DDL(_statement).execute_if(dialect="sqlite"))
for _statement in _POSTGRES_TRIGGERS:
    event.listen(AuditRow.__table__, "after_create",
                 DDL(_statement).execute_if(dialect="postgresql"))
