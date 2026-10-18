"""Request and response shapes of the auth API (WP-11).

Not shared contracts: they mirror `web/src/api/types.ts` (Session, LoginRequest,
LoginResponse, DemoAccount), which WP-14's mock API serves until this router is live.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.contracts import ActionCard, ActionType, Approval, DataMode, Principal, Role


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginBody(_Body):
    email: str = Field(max_length=254)
    password: str = Field(max_length=1024)


class CodeBody(_Body):
    code: str = Field(max_length=32)


class PasswordChangeBody(_Body):
    current_password: str = Field(max_length=1024)
    new_password: str = Field(max_length=1024)


class SessionView(BaseModel):
    principal: Principal
    display_name: str
    business_name: str
    totp_enrolled: bool
    data_mode: DataMode


class LoginOk(BaseModel):
    status: Literal["ok"] = "ok"
    session: SessionView


class LoginTotpRequired(BaseModel):
    status: Literal["totp_required"] = "totp_required"


class DemoAccountView(BaseModel):
    email: str
    password: str
    role: Role
    business_name: str
    totp_hint: str | None = None


class TotpEnrolment(BaseModel):
    secret: str
    otpauth_uri: str


class NewMemberBody(_Body):
    email: str = Field(max_length=254)
    display_name: str = Field(min_length=1, max_length=128)
    role: Role
    password: str = Field(max_length=1024)


class MemberView(BaseModel):
    user_id: str
    email: str
    role: Role
    display_name: str
    active: bool
    totp_enrolled: bool
    expires_at: datetime | None
    scopes: list[str]


class LenderGrantBody(_Body):
    lender_email: str = Field(max_length=254)
    lender_label: str = Field(min_length=1, max_length=80)
    purpose: str = Field(min_length=1, max_length=200)
    scopes: list[str] = Field(min_length=1, max_length=8)
    days: int = Field(ge=1, le=365)
    consent: bool


class LenderGrantView(BaseModel):
    id: str
    lender_email: str
    lender_label: str
    purpose: str
    scopes: list[str]
    consented_by: str
    consented_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    initial_password: str | None = Field(
        default=None, description="Shown once, when the grant is created")


class ApprovalRequestBody(_Body):
    card: ActionCard


class ApprovalView(BaseModel):
    approval: Approval
    action_type: ActionType
    card: ActionCard
    result: dict[str, str] | None = None
    replayed: bool = False


class ChainReportView(BaseModel):
    tenant_id: str
    valid: bool
    length: int
    head_hash: str
    first_bad_seq: int | None = None
    reason: str | None = None
    anchors_checked: int = 0


class AnchorView(BaseModel):
    day: date
    digest: str
    chain: str
    tx_hash: str | None
    block_number: int | None
    explorer_url: str | None
    anchored_at: datetime
    heads: int
