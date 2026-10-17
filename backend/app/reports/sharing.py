"""Consented, scoped, expiring sharing with lenders (WP-13 milestone 3).

The owner grants one lender a scope (e.g. `passport:read`, `report:read`) for a limited time.
Every access attempt, allowed or not, is recorded; the owner can revoke at any moment.
Access tokens are random and only their SHA-256 is stored.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.contracts import ShareGrant

MAX_TTL = timedelta(days=30)
SCOPES = frozenset({"passport:read", "report:read", "attestations:read"})


class SharingError(PermissionError):
    pass


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class AccessRecord:
    grant_id: str
    at: datetime
    scope: str
    allowed: bool
    reason: str


@dataclass
class ShareLedger:
    grants: dict[str, ShareGrant] = field(default_factory=dict)
    token_hashes: dict[str, str] = field(default_factory=dict)  # token hash -> grant id
    log: list[AccessRecord] = field(default_factory=list)

    def grant(self, *, tenant_id: str, passport_id: str, lender_label: str,
              scopes: tuple[str, ...], ttl: timedelta, now: datetime) -> tuple[ShareGrant, str]:
        unknown = set(scopes) - SCOPES
        if unknown:
            raise SharingError(f"unknown scopes: {sorted(unknown)}")
        if ttl <= timedelta(0) or ttl > MAX_TTL:
            raise SharingError("share links last between 1 second and 30 days")
        grant = ShareGrant(id=f"grant-{secrets.token_hex(6)}", tenant_id=tenant_id,
                           passport_id=passport_id, lender_label=lender_label,
                           scopes=tuple(sorted(scopes)), created_at=now, expires_at=now + ttl)
        token = secrets.token_urlsafe(32)
        self.grants[grant.id] = grant
        self.token_hashes[_hash(token)] = grant.id
        return grant, token

    def revoke(self, grant_id: str) -> ShareGrant:
        grant = self.grants[grant_id].model_copy(update={"revoked": True})
        self.grants[grant_id] = grant
        return grant

    def access(self, token: str, scope: str, *, now: datetime) -> ShareGrant:
        digest = _hash(token)
        grant_id = next((gid for h, gid in self.token_hashes.items()
                         if hmac.compare_digest(h, digest)), None)
        if grant_id is None:
            self.log.append(AccessRecord("unknown", now, scope, False, "unknown token"))
            raise SharingError("invalid link")
        grant = self.grants[grant_id]
        reason = ""
        if grant.revoked:
            reason = "revoked"
        elif now >= grant.expires_at:
            reason = "expired"
        elif scope not in grant.scopes:
            reason = "out of scope"
        self.log.append(AccessRecord(grant.id, now, scope, not reason, reason or "ok"))
        if reason:
            raise SharingError(f"link {reason}")
        return grant

    def views(self, grant_id: str) -> list[AccessRecord]:
        return [r for r in self.log if r.grant_id == grant_id]
