from datetime import UTC, datetime, timedelta

import pytest

from app.contracts import Principal, Role
from app.security import totp
from app.security.roles import (
    LENDER_SCOPES,
    Permission,
    has_permission,
    permissions_of,
    policy_masker,
)
from app.security.sessions import COOKIE_NAME
from tests.security.conftest import PASSWORD, sign_in

NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"

# Written out independently of app.security.roles: changing the policy means changing this.
EXPECTED = {
    Role.owner: "ledger source_rows ingest copilot reports passport request decide audit_read "
                "audit_verify team lender_grant",
    Role.accountant: "ledger source_rows ingest copilot reports passport request",
    Role.staff: "ledger ingest copilot request",
    Role.lender_viewer: "",
    Role.compliance: "ledger source_rows reports passport audit_read audit_verify",
}
SHORT = {
    "ledger": Permission.ledger_read, "source_rows": Permission.source_rows_read,
    "ingest": Permission.ingest_upload, "copilot": Permission.copilot_ask,
    "reports": Permission.reports_read, "passport": Permission.passport_read,
    "request": Permission.approvals_request, "decide": Permission.approvals_decide,
    "audit_read": Permission.audit_read, "audit_verify": Permission.audit_verify,
    "team": Permission.team_manage, "lender_grant": Permission.lender_access_grant,
}


def principal(role: Role, scopes=(), expires_at=None) -> Principal:
    if role is Role.lender_viewer and expires_at is None:
        expires_at = NOW + timedelta(days=7)
    return Principal(user_id="u-1", tenant_id="t1", role=role, scopes=scopes,
                     expires_at=expires_at)


@pytest.mark.parametrize("role", list(Role))
@pytest.mark.parametrize("permission", list(Permission))
def test_role_permission_matrix(role, permission):
    expected = {SHORT[name] for name in EXPECTED[role].split()}
    assert has_permission(principal(role), permission, NOW) is (permission in expected)


def test_lender_viewer_gets_only_consented_lender_scopes():
    lender = principal(Role.lender_viewer, scopes=("passport:read", "audit:read", "bogus"))
    assert permissions_of(lender, NOW) == {Permission.passport_read}
    everything = principal(Role.lender_viewer, scopes=tuple(p.value for p in Permission))
    assert permissions_of(everything, NOW) == LENDER_SCOPES


def test_expired_access_has_no_permissions():
    lender = principal(Role.lender_viewer, scopes=("passport:read",),
                       expires_at=NOW + timedelta(seconds=1))
    assert permissions_of(lender, NOW + timedelta(seconds=1)) == frozenset()


@pytest.mark.parametrize(("role", "masked"), [
    (Role.owner, False), (Role.accountant, False), (Role.compliance, False),
    (Role.staff, True), (Role.lender_viewer, True),
])
def test_source_rows_are_masked_for_roles_without_source_row_access(role, masked):
    rows, was_masked = policy_masker("t1", ("bank.csv#L1", "bank.csv#L2"), role)
    assert was_masked is masked
    if masked:
        assert rows[0].startswith("masked:") and rows[0] != rows[1]
        assert policy_masker("t1", ("bank.csv#L1",), role)[0][0] == rows[0]  # stable
    else:
        assert rows == ("bank.csv#L1", "bank.csv#L2")


# ------------------------------------------------------------------------- team API


def owner_with_totp(api, make_user, clock):
    make_user(totp_secret=SECRET)
    sign_in(api)
    api.post("/api/auth/login/totp", json={"code": totp.code_at(SECRET, clock())})
    clock.advance(seconds=30)  # the next code is a fresh one for step-up


def fresh_code(clock) -> dict[str, str]:
    code = totp.code_at(SECRET, clock())
    clock.advance(seconds=30)
    return {"X-Step-Up-Code": code}


def test_owner_adds_a_staff_member_who_can_sign_in(api, make_user, clock):
    owner_with_totp(api, make_user, clock)
    added = api.post("/api/auth/users", headers=fresh_code(clock), json={
        "email": "staff@shop.test", "display_name": "Karim", "role": "staff",
        "password": "staff passphrase 1"})
    assert added.status_code == 201 and added.json()["role"] == "staff"
    emails = [m["email"] for m in api.get("/api/auth/users").json()]
    assert emails == ["owner@shop.test", "staff@shop.test"]
    with type(api)(api.app) as phone:
        assert sign_in(phone, "staff@shop.test", "staff passphrase 1").json()["status"] == "ok"


@pytest.mark.parametrize(("headers", "status", "code"), [
    ({}, 401, "step_up_required"),
    ({"X-Step-Up-Code": "000000"}, 401, "invalid_step_up"),
])
def test_adding_a_member_needs_a_fresh_step_up_code(api, make_user, clock, headers, status,
                                                    code):
    owner_with_totp(api, make_user, clock)
    response = api.post("/api/auth/users", headers=headers, json={
        "email": "staff@shop.test", "display_name": "Karim", "role": "staff",
        "password": "staff passphrase 1"})
    assert response.status_code == status and response.json()["code"] == code
    assert len(api.get("/api/auth/users").json()) == 1


def test_a_step_up_code_cannot_be_reused(api, make_user, clock):
    owner_with_totp(api, make_user, clock)
    header = {"X-Step-Up-Code": totp.code_at(SECRET, clock())}
    body = {"display_name": "A", "role": "staff", "password": "staff passphrase 1"}
    assert api.post("/api/auth/users", headers=header,
                    json={**body, "email": "a@shop.test"}).status_code == 201
    replay = api.post("/api/auth/users", headers=header, json={**body, "email": "b@shop.test"})
    assert replay.json()["code"] == "invalid_step_up"


def test_wrong_step_up_codes_lock_the_account(api, make_user, clock):
    owner_with_totp(api, make_user, clock)
    body = {"email": "s@shop.test", "display_name": "S", "role": "staff",
            "password": "staff passphrase 1"}
    statuses = [api.post("/api/auth/users", headers={"X-Step-Up-Code": "000000"},
                         json=body).status_code for _ in range(5)]
    assert statuses == [401, 401, 401, 401, 423]


def test_step_up_needs_an_enrolled_authenticator(api, make_user):
    make_user()
    sign_in(api)
    response = api.post("/api/auth/users", headers={"X-Step-Up-Code": "123456"}, json={
        "email": "s@shop.test", "display_name": "S", "role": "staff",
        "password": "staff passphrase 1"})
    assert response.status_code == 403 and response.json()["code"] == "totp_not_enrolled"


@pytest.mark.parametrize("role", ["owner", "lender_viewer"])
def test_owners_and_lenders_cannot_be_added_as_members(api, make_user, clock, role):
    owner_with_totp(api, make_user, clock)
    response = api.post("/api/auth/users", headers=fresh_code(clock), json={
        "email": "x@shop.test", "display_name": "X", "role": role,
        "password": "some passphrase 1"})
    assert response.status_code == 422 and response.json()["code"] == "role_not_assignable"


@pytest.mark.parametrize("role", [Role.accountant, Role.staff, Role.compliance])
def test_only_the_owner_manages_the_team(api, make_user, role):
    make_user()
    make_user("member@shop.test", role=role)
    sign_in(api, "member@shop.test")
    assert api.get("/api/auth/users").json() == {
        "code": "forbidden", "message_key": "error.forbidden",
        "detail": {"reason": "team:manage"}}
    assert api.post("/api/auth/users", json={}).status_code == 403  # before the body is read


def test_deactivating_a_member_ends_their_sessions(api, make_user, clock):
    make_user()
    staff_id = make_user("staff@shop.test", role=Role.staff)
    with type(api)(api.app) as phone:
        sign_in(phone, "staff@shop.test")
        sign_in(api)
        response = api.post(f"/api/auth/users/{staff_id}/deactivate")
        assert response.status_code == 200 and response.json()["active"] is False
        assert phone.get("/api/auth/me").status_code == 401
        assert sign_in(phone, "staff@shop.test").status_code == 401


def test_an_owner_cannot_deactivate_themselves_or_another_tenants_user(api, make_user):
    owner_id = make_user()
    foreign_id = make_user("staff@other.test", role=Role.staff, tenant="t2")
    sign_in(api)
    assert api.post(f"/api/auth/users/{owner_id}/deactivate").json()["code"] == \
        "cannot_deactivate_self"
    foreign = api.post(f"/api/auth/users/{foreign_id}/deactivate")
    assert foreign.status_code == 404


# ------------------------------------------------------------------------- lender access

GRANT = {"lender_email": "officer@bank.test", "lender_label": "Example Bank",
         "purpose": "Working-capital loan review", "scopes": ["passport:read"], "days": 7,
         "consent": True}


def test_lender_access_is_consented_scoped_and_expiring(api, make_user, clock):
    owner_with_totp(api, make_user, clock)
    created = api.post("/api/auth/lender-access", headers=fresh_code(clock), json=GRANT)
    assert created.status_code == 201
    grant = created.json()
    assert grant["consented_by"].startswith("u-") and grant["scopes"] == ["passport:read"]
    assert grant["initial_password"] and created.headers["cache-control"] == "no-store"
    assert "initial_password" not in api.get("/api/auth/lender-access").json()[0] or \
        api.get("/api/auth/lender-access").json()[0]["initial_password"] is None
    with type(api)(api.app) as bank:
        session = sign_in(bank, "officer@bank.test", grant["initial_password"]).json()
        assert session["session"]["principal"]["role"] == "lender_viewer"
        assert session["session"]["principal"]["scopes"] == ["passport:read"]
        clock.advance(days=7)
        assert bank.get("/api/auth/me").status_code == 401


def test_revoking_lender_access_ends_it_immediately(api, make_user, clock):
    owner_with_totp(api, make_user, clock)
    grant = api.post("/api/auth/lender-access", headers=fresh_code(clock), json=GRANT).json()
    with type(api)(api.app) as bank:
        sign_in(bank, "officer@bank.test", grant["initial_password"])
        revoked = api.post(f"/api/auth/lender-access/{grant['id']}/revoke")
        assert revoked.json()["revoked_at"] is not None
        assert bank.get("/api/auth/me").status_code == 401
        bank.cookies.delete(COOKIE_NAME, path="/api")
        assert sign_in(bank, "officer@bank.test", grant["initial_password"]).status_code == 401


@pytest.mark.parametrize(("change", "code"), [
    ({"consent": False}, "consent_required"),
    ({"scopes": ["ledger:read"]}, "invalid_scopes"),
    ({"scopes": ["passport:read", "audit:read"]}, "invalid_scopes"),
    ({"days": 31}, "invalid_expiry"),
])
def test_lender_grants_outside_the_rules_are_refused(api, make_user, clock, change, code):
    owner_with_totp(api, make_user, clock)
    response = api.post("/api/auth/lender-access", headers=fresh_code(clock),
                        json={**GRANT, **change})
    assert response.status_code == 422 and response.json()["code"] == code
    assert api.get("/api/auth/lender-access").json() == []


def test_lender_grants_need_step_up(api, make_user, clock):
    owner_with_totp(api, make_user, clock)
    response = api.post("/api/auth/lender-access", json=GRANT)
    assert response.json()["code"] == "step_up_required"


def test_staff_cannot_grant_lender_access(api, make_user):
    make_user()
    make_user("staff@shop.test", role=Role.staff, password=PASSWORD)
    sign_in(api, "staff@shop.test")
    assert api.post("/api/auth/lender-access", json=GRANT).status_code == 403
