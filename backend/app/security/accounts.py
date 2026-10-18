"""Accounts and the sign-in flow (WP-11 milestone 1).

    accounts = Accounts(db, settings)
    result = accounts.sign_in(email, password, now)     # ok | totp_required | invalid | locked
    result = accounts.complete_totp(user, code, now)    # second step when TOTP is enrolled

Unknown emails, wrong passwords, disabled or expired accounts, and demo accounts outside demo
mode all answer `invalid` after the same argon2 work, so responses do not reveal which accounts
exist. Wrong passwords and wrong TOTP codes both count towards the lockout.
"""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.contracts import DataMode, Principal, Role
from app.security import passwords, totp
from app.security.keys import SecretBox, derive_key
from app.security.lockout import Lockout, minutes_left
from app.security.models import TenantRow, UserRow
from app.security.schemas import SessionView
from app.settings import Settings

_EMAIL = re.compile(r"^[^@\s]{1,64}@(?:[a-z0-9-]{1,63}\.)+[a-z]{2,63}$")
MAX_EMAIL_LENGTH = 254


def normalise_email(raw: str) -> str:
    return raw.strip().lower()


def valid_email(email: str) -> bool:
    return len(email) <= MAX_EMAIL_LENGTH and _EMAIL.match(email) is not None


class AccountProblem(ValueError):
    def __init__(self, code: str, message_key: str, **detail: str) -> None:
        super().__init__(code)
        self.code = code
        self.message_key = message_key
        self.detail = detail


@dataclass(frozen=True)
class SignIn:
    status: Literal["ok", "totp_required", "invalid", "locked"]
    user: UserRow | None = None
    retry_after_minutes: int | None = None


def principal_of(user: UserRow) -> Principal:
    return Principal(user_id=user.id, tenant_id=user.tenant_id, role=Role(user.role),
                     scopes=tuple(json.loads(user.scopes)), expires_at=user.expires_at)


class Accounts:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        secret = settings.secret_key.get_secret_value()
        self.lockout = Lockout(db, derive_key(secret, "lockout"))
        self.box = SecretBox(derive_key(secret, "totp"))

    # ------------------------------------------------------------------ tenants and users

    def ensure_tenant(self, tenant_id: str, business_name: str, data_mode: DataMode,
                      now: datetime) -> TenantRow:
        row = self.db.get(TenantRow, tenant_id)
        if row is None:
            row = TenantRow(id=tenant_id, business_name=business_name,
                            data_mode=data_mode.value, created_at=now)
            self.db.add(row)
            self.db.flush()
        return row

    def create_user(self, *, email: str, password: str, tenant_id: str, role: Role,
                    display_name: str, now: datetime, scopes: tuple[str, ...] = (),
                    expires_at: datetime | None = None, is_demo: bool = False) -> UserRow:
        email = normalise_email(email)
        if not valid_email(email):
            raise AccountProblem("invalid_email", "error.invalid_email")
        if self.by_email(email) is not None:
            raise AccountProblem("email_taken", "error.email_taken")
        if self.db.get(TenantRow, tenant_id) is None:
            raise AccountProblem("unknown_tenant", "error.unknown_tenant")
        problems = passwords.policy_problems(password, email=email)
        if problems:
            raise AccountProblem("weak_password", "error.weak_password",
                                 problems=",".join(problems))
        if role is Role.lender_viewer and (expires_at is None or expires_at <= now):
            raise AccountProblem("expiry_required", "error.lender_access_needs_expiry")
        user = UserRow(id="u-" + secrets.token_hex(8), email=email, tenant_id=tenant_id,
                       role=role.value, display_name=display_name,
                       password_hash=passwords.hash_password(password),
                       scopes=json.dumps(sorted(set(scopes))), expires_at=expires_at,
                       active=True, is_demo=is_demo, totp_enrolled=False,
                       created_at=now, password_changed_at=now)
        self.db.add(user)
        self.db.flush()
        return user

    def by_email(self, email: str) -> UserRow | None:
        return self.db.scalar(select(UserRow).where(UserRow.email == normalise_email(email)))

    def get(self, user_id: str) -> UserRow | None:
        return self.db.get(UserRow, user_id)

    def usable(self, user: UserRow, now: datetime) -> bool:
        if not user.active:
            return False
        if user.is_demo and not self.settings.demo_mode:
            return False
        return user.expires_at is None or user.expires_at > now

    # ------------------------------------------------------------------ sign-in

    def sign_in(self, raw_email: str, password: str, now: datetime) -> SignIn:
        email = normalise_email(raw_email)
        remaining = self.lockout.locked_for(email, now)
        if remaining is not None:
            return SignIn("locked", retry_after_minutes=minutes_left(remaining))
        user = self.by_email(email) if valid_email(email) else None
        if user is None or not self.usable(user, now):
            passwords.burn_verify(password)
            return self._failed(email, now)
        if not passwords.verify_password(user.password_hash, password):
            return self._failed(email, now)
        self.lockout.clear(email)
        if passwords.needs_rehash(user.password_hash):
            user.password_hash = passwords.hash_password(password)
            self.db.flush()
        return SignIn("totp_required" if user.totp_enrolled else "ok", user=user)

    def complete_totp(self, user: UserRow, code: str, now: datetime) -> SignIn:
        remaining = self.lockout.locked_for(user.email, now)
        if remaining is not None:
            return SignIn("locked", retry_after_minutes=minutes_left(remaining))
        if self.usable(user, now) and self.verify_totp(user, code, now):
            self.lockout.clear(user.email)
            return SignIn("ok", user=user)
        return self._failed(user.email, now)

    def _failed(self, email: str, now: datetime) -> SignIn:
        locked = self.lockout.record_failure(email, now)
        if locked is not None:
            return SignIn("locked", retry_after_minutes=minutes_left(locked))
        return SignIn("invalid")

    def change_password(self, user: UserRow, current: str, new: str, now: datetime) -> SignIn:
        """`ok`, `invalid` (wrong current password, counts towards lockout) or `locked`.
        Raises AccountProblem when the new password breaks the policy."""
        remaining = self.lockout.locked_for(user.email, now)
        if remaining is not None:
            return SignIn("locked", retry_after_minutes=minutes_left(remaining))
        if not passwords.verify_password(user.password_hash, current):
            return self._failed(user.email, now)
        problems = passwords.policy_problems(new, email=user.email)
        if problems:
            raise AccountProblem("weak_password", "error.weak_password",
                                 problems=",".join(problems))
        user.password_hash = passwords.hash_password(new)
        user.password_changed_at = now
        self.db.flush()
        return SignIn("ok", user=user)

    # ------------------------------------------------------------------ TOTP

    def totp_secret(self, user: UserRow) -> str | None:
        if user.totp_nonce is None or user.totp_ciphertext is None:
            return None
        return self.box.open(user.totp_nonce, user.totp_ciphertext, owner=user.id)

    def set_totp_secret(self, user: UserRow, secret: str, *, enrolled: bool) -> None:
        user.totp_nonce, user.totp_ciphertext = self.box.seal(secret, owner=user.id)
        user.totp_enrolled = enrolled
        user.totp_last_step = None
        self.db.flush()

    def verify_totp(self, user: UserRow, code: str, now: datetime, *,
                    require_enrolled: bool = True) -> bool:
        """Check a code and burn its time step. The conditional UPDATE makes the replay check
        atomic: of two requests racing with the same code, only one succeeds."""
        if require_enrolled and not user.totp_enrolled:
            return False
        secret = self.totp_secret(user)
        if secret is None:
            return False
        step = totp.verify(secret, code, now, user.totp_last_step)
        if step is None:
            return False
        result = self.db.execute(
            update(UserRow)
            .where(UserRow.id == user.id,
                   or_(UserRow.totp_last_step.is_(None), UserRow.totp_last_step < step))
            .values(totp_last_step=step)
            .execution_options(synchronize_session="fetch")
        )
        return result.rowcount == 1

    def start_totp_enrolment(self, user: UserRow) -> str:
        if user.totp_enrolled:
            raise AccountProblem("totp_already_enrolled", "error.totp_already_enrolled")
        secret = totp.new_secret()
        self.set_totp_secret(user, secret, enrolled=False)
        return secret

    def confirm_totp_enrolment(self, user: UserRow, code: str, now: datetime) -> bool:
        if user.totp_enrolled or not self.verify_totp(user, code, now, require_enrolled=False):
            return False
        user.totp_enrolled = True
        self.db.flush()
        return True

    # ------------------------------------------------------------------ views

    def session_view(self, user: UserRow) -> SessionView:
        tenant = self.db.get(TenantRow, user.tenant_id)
        return SessionView(
            principal=principal_of(user),
            display_name=user.display_name,
            business_name=tenant.business_name if tenant else user.tenant_id,
            totp_enrolled=user.totp_enrolled,
            data_mode=DataMode(tenant.data_mode) if tenant else DataMode.live,
        )
