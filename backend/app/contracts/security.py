"""Security (WP-11; FEATURES P2): roles, principals, approvals, audit events."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from app.contracts.common import Contract, Tier


class Role(StrEnum):
    owner = "owner"
    accountant = "accountant"
    staff = "staff"
    lender_viewer = "lender_viewer"
    compliance = "compliance"


class Principal(Contract):
    user_id: str
    tenant_id: str
    role: Role
    scopes: tuple[str, ...] = ()
    expires_at: datetime | None = Field(
        default=None, description="Required for lender_viewer (consented, expiring access)"
    )

    @model_validator(mode="after")
    def _lender_access_expires(self) -> Principal:
        if self.role is Role.lender_viewer and self.expires_at is None:
            raise ValueError("lender_viewer access must have an expiry")
        return self


class ApprovalStatus(StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"
    executed = "executed"


class Approval(Contract):
    id: str
    tenant_id: str
    action_card_id: str
    tier: Tier
    requested_by: str
    decided_by: str | None = None
    status: ApprovalStatus
    step_up_verified: bool = False
    idempotency_key: str = Field(min_length=8)
    created_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def _rules(self) -> Approval:
        if self.tier is Tier.DENY:
            raise ValueError("DENY actions cannot be approved")
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")
        if self.status in (ApprovalStatus.approved, ApprovalStatus.executed):
            if self.decided_by is None:
                raise ValueError("an approved action records who approved it")
            if self.tier is Tier.EXECUTE and not self.step_up_verified:
                raise ValueError("EXECUTE approvals need a verified step-up code")
        return self


class AuditEvent(Contract):
    """One link of the append-only, SHA-256 hash-chained audit log."""

    seq: int = Field(ge=0)
    tenant_id: str
    at: datetime
    actor: str
    action: str
    tier: Tier | None = None
    target: str | None = None
    details_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    prev_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    hash: str = Field(pattern=r"^[0-9a-f]{64}$")


GENESIS_HASH = "0" * 64
