"""Demo accounts for the hosted competition demo (WP-11 milestone 1; demo mode only).

One account per role on the grocery tenant, plus an owner for each other synthetic SME (the
mesh netting round needs every owner's approval). Tenants are the synthetic universe's SMEs,
labelled synthetic. In demo mode the passwords and each owner's current TOTP code are published
on purpose (`GET /api/auth/demo-accounts`), so judges can sign in without an authenticator app;
that is safe only because every demo tenant holds synthetic data.

Outside demo mode nothing is seeded and existing demo accounts are refused at sign-in
(`Accounts.usable`); production refuses demo mode altogether (`Settings._production_guards`).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contracts import DataMode, Role
from app.security import totp
from app.security.accounts import Accounts
from app.security.keys import derive_key
from app.security.schemas import DemoAccountView
from app.settings import AppEnv, Settings
from app.synthetic.universe import UNIVERSE_DIR

DEMO_DOMAIN = "hishab.test"  # RFC 2606 reserved name: never a real mailbox
LENDER_ACCESS = timedelta(days=30)
LENDER_SCOPES = ("passport:read", "reports:read")


@dataclass(frozen=True)
class DemoAccount:
    email: str
    password: str
    role: Role
    tenant_id: str
    display_name: str
    totp: bool


def _account(local: str, shop: str, role: Role, tenant: str, totp_on: bool) -> DemoAccount:
    label = role.value.replace("_", " ")
    return DemoAccount(email=f"{local}@{shop}.{DEMO_DOMAIN}",
                       password=f"hishab-demo-{local}", role=role, tenant_id=tenant,
                       display_name=f"Demo {label}", totp=totp_on)


DEMO_ACCOUNTS: tuple[DemoAccount, ...] = (
    _account("owner", "grocery", Role.owner, "sme_grocery", True),
    _account("accountant", "grocery", Role.accountant, "sme_grocery", False),
    _account("staff", "grocery", Role.staff, "sme_grocery", False),
    _account("lender", "grocery", Role.lender_viewer, "sme_grocery", False),
    _account("compliance", "grocery", Role.compliance, "sme_grocery", False),
    _account("owner", "pharmacy", Role.owner, "sme_pharmacy", True),
    _account("owner", "fabric", Role.owner, "sme_fabric", True),
    _account("owner", "garment", Role.owner, "sme_garment", True),
    _account("owner", "hardware", Role.owner, "sme_hardware", True),
)


def demo_enabled(settings: Settings) -> bool:
    return settings.demo_mode and settings.app_env is not AppEnv.production


@lru_cache
def business_name(tenant_id: str) -> str:
    profile = json.loads((UNIVERSE_DIR / tenant_id / "profile.json").read_text(encoding="utf-8"))
    return str(profile["display_name"])


def demo_totp_secret(settings: Settings, email: str) -> str:
    """Stable per deployment (derived from secret_key), so published codes survive restarts."""
    key = derive_key(settings.secret_key.get_secret_value(), "demo-totp")
    raw = hmac.new(key, email.encode(), hashlib.sha256).digest()[:20]
    return base64.b32encode(raw).decode()


def ensure_demo_accounts(db: Session, settings: Settings, now: datetime) -> int:
    """Create missing demo tenants and accounts (idempotent). Returns how many were created."""
    if not demo_enabled(settings):
        return 0
    accounts = Accounts(db, settings)
    created = 0
    for demo in DEMO_ACCOUNTS:
        user = accounts.by_email(demo.email)
        if user is not None:
            if demo.role is Role.lender_viewer and (user.expires_at is None
                                                    or user.expires_at <= now):
                user.expires_at = now + LENDER_ACCESS  # keep the public demo lender usable
            continue
        lender = demo.role is Role.lender_viewer
        try:
            with db.begin_nested():
                accounts.ensure_tenant(demo.tenant_id, business_name(demo.tenant_id),
                                       DataMode.synthetic, now)
                user = accounts.create_user(
                    email=demo.email, password=demo.password, tenant_id=demo.tenant_id,
                    role=demo.role, display_name=demo.display_name, now=now,
                    scopes=LENDER_SCOPES if lender else (),
                    expires_at=now + LENDER_ACCESS if lender else None, is_demo=True)
                if demo.totp:
                    accounts.set_totp_secret(user, demo_totp_secret(settings, demo.email),
                                             enrolled=True)
        except IntegrityError:
            continue  # a concurrent request seeded it first
        created += 1
    db.flush()
    return created


def demo_listing(settings: Settings, now: datetime) -> list[DemoAccountView]:
    return [
        DemoAccountView(
            email=demo.email, password=demo.password, role=demo.role,
            business_name=business_name(demo.tenant_id),
            totp_hint=totp.code_at(demo_totp_secret(settings, demo.email), now)
            if demo.totp else None,
        )
        for demo in DEMO_ACCOUNTS
    ]
