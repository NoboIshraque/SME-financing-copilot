"""Source-row masking hook (stub until WP-03 / WP-11 plug in the real policy).

`explain()` always passes its source rows through the active masker, whatever the caller's
role, so the real policy only has to replace the function:

    from app.facts.masking import set_masker
    set_masker(my_policy)       # (tenant_id, rows, role) -> (rows, masked)
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable

from app.contracts import Role

SourceRowMasker = Callable[[str, tuple[str, ...], Role], tuple[tuple[str, ...], bool]]

UNMASKED_ROLES = frozenset({Role.owner, Role.accountant, Role.compliance})


def role_masker(tenant_id: str, rows: tuple[str, ...], role: Role) -> tuple[tuple[str, ...], bool]:
    """Stub policy: the owner, accountant and compliance see source rows; other roles get a
    stable opaque reference per row (the same row always masks to the same reference)."""
    if role in UNMASKED_ROLES:
        return rows, False
    masked = tuple(
        "masked:" + hashlib.sha256(f"{tenant_id}|{row}".encode()).hexdigest()[:16] for row in rows
    )
    return masked, True


_active: SourceRowMasker = role_masker


def set_masker(masker: SourceRowMasker) -> SourceRowMasker:
    """Install a masking policy; returns the previous one (so tests can restore it)."""
    global _active
    previous, _active = _active, masker
    return previous


def get_masker() -> SourceRowMasker:
    return _active
