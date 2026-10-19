"""Team members and lender access (WP-11 milestone 2).

The owner adds accountants, staff and compliance reviewers, and deactivates them (their
sessions end at once). A lender viewer exists only through a `LenderGrantRow`: the owner's
recorded consent naming the lender, the purpose, the scopes (a subset of `LENDER_SCOPES`) and
an expiry of at most 30 days. Revoking the grant deactivates the account and ends its sessions.
Every function checks that the target belongs to the owner's own tenant.
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import Principal, Role
from app.security.accounts import AccountProblem, Accounts
from app.security.models import LenderGrantRow, UserRow
from app.security.roles import LENDER_SCOPES, MEMBER_ROLES
from app.security.sessions import SessionStore
from app.settings import Settings

MAX_LENDER_DAYS = 30


class Team:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.accounts = Accounts(db, settings)

    def members(self, tenant_id: str) -> list[UserRow]:
        return list(self.db.scalars(select(UserRow).where(UserRow.tenant_id == tenant_id)
                                    .order_by(UserRow.created_at, UserRow.email)))

    def add_member(self, owner: Principal, *, email: str, display_name: str, role: Role,
                   password: str, now: datetime) -> UserRow:
        if role not in MEMBER_ROLES:
            raise AccountProblem("role_not_assignable", "error.role_not_assignable",
                                 role=role.value)
        return self.accounts.create_user(email=email, password=password,
                                         tenant_id=owner.tenant_id, role=role,
                                         display_name=display_name, now=now)

    def _own(self, owner: Principal, user_id: str) -> UserRow:
        user = self.accounts.get(user_id)
        if user is None or user.tenant_id != owner.tenant_id:
            raise AccountProblem("not_found", "error.not_found")  # never confirm other tenants
        return user

    def deactivate(self, owner: Principal, user_id: str, now: datetime) -> UserRow:
        user = self._own(owner, user_id)
        if user.id == owner.user_id:
            raise AccountProblem("cannot_deactivate_self", "error.cannot_deactivate_self")
        user.active = False
        SessionStore(self.db).revoke_user(user.id, now)
        self.db.flush()
        return user

    def grant_lender(self, owner: Principal, *, lender_email: str, lender_label: str,
                     purpose: str, scopes: tuple[str, ...], days: int, consent: bool,
                     now: datetime) -> tuple[LenderGrantRow, str]:
        """Returns the grant and the lender's one-time initial password."""
        if not consent:
            raise AccountProblem("consent_required", "error.consent_required")
        allowed = {scope.value for scope in LENDER_SCOPES}
        if not scopes or not set(scopes) <= allowed:
            raise AccountProblem("invalid_scopes", "error.invalid_scopes",
                                 allowed=",".join(sorted(allowed)))
        if not 1 <= days <= MAX_LENDER_DAYS:
            raise AccountProblem("invalid_expiry", "error.invalid_expiry",
                                 max_days=str(MAX_LENDER_DAYS))
        expires_at = now + timedelta(days=days)
        initial_password = secrets.token_urlsafe(15)
        user = self.accounts.create_user(email=lender_email, password=initial_password,
                                         tenant_id=owner.tenant_id, role=Role.lender_viewer,
                                         display_name=lender_label, now=now,
                                         scopes=tuple(scopes), expires_at=expires_at)
        grant = LenderGrantRow(id="lg-" + secrets.token_hex(8), tenant_id=owner.tenant_id,
                               user_id=user.id, lender_label=lender_label, purpose=purpose,
                               scopes=user.scopes, consented_by=owner.user_id,
                               consented_at=now, expires_at=expires_at)
        self.db.add(grant)
        self.db.flush()
        return grant, initial_password

    def grants(self, tenant_id: str) -> list[LenderGrantRow]:
        return list(self.db.scalars(select(LenderGrantRow)
                                    .where(LenderGrantRow.tenant_id == tenant_id)
                                    .order_by(LenderGrantRow.consented_at)))

    def revoke_lender(self, owner: Principal, grant_id: str, now: datetime) -> LenderGrantRow:
        grant = self.db.get(LenderGrantRow, grant_id)
        if grant is None or grant.tenant_id != owner.tenant_id:
            raise AccountProblem("not_found", "error.not_found")
        if grant.revoked_at is None:
            grant.revoked_at = now
            user = self.accounts.get(grant.user_id)
            if user is not None:
                user.active = False
                SessionStore(self.db).revoke_user(user.id, now)
            self.db.flush()
        return grant


def grant_scopes(grant: LenderGrantRow) -> list[str]:
    return list(json.loads(grant.scopes))
