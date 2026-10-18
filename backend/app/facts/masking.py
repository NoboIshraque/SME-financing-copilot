"""Source-row masking hook (stub until WP-03 / WP-11 plug in the real policy).

Everything that leaves WP-01 with source rows in it (`explain`, `explain_rows`, `GET /facts`)
passes them through the active masker, for every caller, so the real policy only has to
replace the function:

    from app.facts.masking import set_masker
    set_masker(my_policy)       # (tenant_id, rows, caller: Principal) -> (rows, masked)

The caller is the full `Principal` (tenant, role, scopes), so a policy can enforce a lender's
consent scope or expiry, not just a role.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Callable
from datetime import UTC, datetime

from app.contracts import Bill, Fact, Invoice, Principal, Role, Transaction

SourceRowMasker = Callable[[str, tuple[str, ...], Principal], tuple[tuple[str, ...], bool]]

UNMASKED_ROLES = frozenset({Role.owner, Role.accountant, Role.compliance})

# Keyed so a masked reference cannot be recomputed from a tenant id and a guessed row. The
# default key lives only in this process; WP-11 sets a stable one from settings.
_key = secrets.token_bytes(32)


def set_masking_key(key: bytes) -> None:
    global _key
    if len(key) < 16:
        raise ValueError("masking key must be at least 16 bytes")
    _key = key


def mask_value(tenant_id: str, value: str) -> str:
    digest = hmac.new(_key, f"{tenant_id}|{value}".encode(), hashlib.sha256).hexdigest()[:16]
    return f"masked:{digest}"


def sees_rows(tenant_id: str, caller: Principal) -> bool:
    """The tenant's own owner, accountant or compliance officer, with access not expired."""
    expired = caller.expires_at is not None and caller.expires_at <= datetime.now(UTC)
    return caller.tenant_id == tenant_id and caller.role in UNMASKED_ROLES and not expired


def role_masker(tenant_id: str, rows: tuple[str, ...],
                caller: Principal) -> tuple[tuple[str, ...], bool]:
    """Stub policy: the tenant's owner, accountant and compliance officer see source rows;
    anyone else gets one stable opaque reference per row."""
    if sees_rows(tenant_id, caller):
        return rows, False
    return tuple(mask_value(tenant_id, row) for row in rows), True


_active: SourceRowMasker = role_masker


def set_masker(masker: SourceRowMasker) -> SourceRowMasker:
    """Install a masking policy; returns the previous one (so tests can restore it)."""
    global _active
    previous, _active = _active, masker
    return previous


def get_masker() -> SourceRowMasker:
    return _active


def mask_record(record: Transaction | Invoice | Bill | Fact, tenant_id: str
                ) -> Transaction | Invoice | Bill | Fact:
    """A record as a masked caller may see it: amounts and dates stay (they are the figure's
    evidence), the counterparty and the exact source location do not."""
    if isinstance(record, Fact):
        return record.model_copy(update={
            "source_refs": tuple(mask_value(tenant_id, r) for r in record.source_refs)})
    update: dict[str, object] = {"source_ref": mask_value(tenant_id, record.source_ref)}
    if isinstance(record, Transaction):
        update.update(counterparty_token=None, reference=None, invoice_id=None)
    else:
        update["counterparty_token"] = mask_value(tenant_id, record.counterparty_token)
    return record.model_copy(update=update)
