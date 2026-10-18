"""Request and response shapes of the auth API (WP-11).

Not shared contracts: they mirror `web/src/api/types.ts` (Session, LoginRequest,
LoginResponse, DemoAccount), which WP-14's mock API serves until this router is live.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.contracts import DataMode, Principal, Role


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
