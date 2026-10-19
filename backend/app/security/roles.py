"""Roles and what each may see (WP-11 milestone 2).

Permissions gate *resources* (who may read the audit log, manage the team, see unmasked
source rows). What a role may *do* with an action card is the tier policy in
`app.security.policy`.

A lender viewer holds no permission of its own: only the scopes the owner consented to
(at most `LENDER_SCOPES`), and only until the grant expires.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from app.contracts import Principal, Role
from app.facts.masking import mask_value


class Permission(StrEnum):
    ledger_read = "ledger:read"  # facts, forecasts, statements, receivables
    source_rows_read = "source_rows:read"  # unmasked source-row references (provenance)
    ingest_upload = "ingest:upload"
    copilot_ask = "copilot:ask"
    reports_read = "reports:read"
    passport_read = "passport:read"
    approvals_request = "approvals:request"  # ask the owner to approve an action
    approvals_decide = "approvals:decide"  # approve or reject; EXECUTE needs step-up
    audit_read = "audit:read"
    audit_verify = "audit:verify"
    team_manage = "team:manage"  # add and deactivate members
    lender_access_grant = "lender_access:grant"  # consent to a lender seeing data


P = Permission

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.owner: frozenset(Permission),
    Role.accountant: frozenset({P.ledger_read, P.source_rows_read, P.ingest_upload,
                                P.copilot_ask, P.reports_read, P.passport_read,
                                P.approvals_request}),
    Role.staff: frozenset({P.ledger_read, P.ingest_upload, P.copilot_ask, P.approvals_request}),
    Role.lender_viewer: frozenset(),  # only consented scopes, see LENDER_SCOPES
    Role.compliance: frozenset({P.ledger_read, P.source_rows_read, P.reports_read,
                                P.passport_read, P.audit_read, P.audit_verify}),
}

LENDER_SCOPES: frozenset[Permission] = frozenset({P.passport_read, P.reports_read})
MEMBER_ROLES = frozenset({Role.accountant, Role.staff, Role.compliance})  # owner may add these


def permissions_of(principal: Principal, now: datetime) -> frozenset[Permission]:
    if principal.expires_at is not None and principal.expires_at <= now:
        return frozenset()
    if principal.role is Role.lender_viewer:
        known = {permission.value for permission in Permission}
        granted = frozenset(Permission(scope) for scope in principal.scopes if scope in known)
        return granted & LENDER_SCOPES
    return ROLE_PERMISSIONS[principal.role]


def has_permission(principal: Principal, permission: Permission, now: datetime) -> bool:
    return permission in permissions_of(principal, now)


def policy_masker(tenant_id: str, rows: tuple[str, ...], caller: Principal
                  ) -> tuple[tuple[str, ...], bool]:
    """Source-row masking for `app.facts.masking.set_masker`: rows are shown only to a caller
    of the same tenant who holds `source_rows:read` right now (so an expired grant masks);
    everyone else gets WP-01's keyed, stable opaque references."""
    if caller.tenant_id == tenant_id and has_permission(caller, Permission.source_rows_read,
                                                        datetime.now(UTC)):
        return rows, False
    return tuple(mask_value(tenant_id, row) for row in rows), True
