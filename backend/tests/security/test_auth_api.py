from datetime import timedelta

import pytest
from argon2.profiles import CHEAPEST, RFC_9106_LOW_MEMORY
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.contracts import Role
from app.main import create_app
from app.security import passwords, totp
from app.security.demo import DEMO_ACCOUNTS, demo_totp_secret
from app.security.models import UserRow
from app.security.sessions import COOKIE_NAME
from app.settings import Settings
from tests.security.conftest import PASSWORD, sign_in

SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"


def session_cookie_header(response) -> str:
    return next(v for k, v in response.headers.multi_items()
                if k == "set-cookie" and v.startswith(COOKIE_NAME))


def test_sign_in_sets_an_httponly_strict_cookie_scoped_to_the_api(api, make_user):
    make_user()
    response = sign_in(api)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["session"]["principal"]["role"] == "owner"
    assert body["session"]["business_name"] == "Test Shop"
    cookie = session_cookie_header(response).lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/api" in cookie
    assert "max-age=43200" in cookie
    assert response.headers["cache-control"] == "no-store"


def test_me_needs_a_session(api, make_user):
    make_user()
    assert api.get("/api/auth/me").json()["code"] == "not_authenticated"
    sign_in(api)
    me = api.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["principal"]["tenant_id"] == "t1"


def test_wrong_password_and_unknown_email_are_indistinguishable(api, make_user):
    make_user()
    wrong = sign_in(api, password="not the password")
    unknown = sign_in(api, email="nobody@shop.test")
    malformed = sign_in(api, email="not-an-email")
    assert wrong.status_code == unknown.status_code == malformed.status_code == 401
    assert wrong.json() == unknown.json() == malformed.json() == {
        "code": "invalid_credentials", "message_key": "error.invalid_credentials", "detail": {}}


def test_email_matching_ignores_case_and_surrounding_spaces(api, make_user):
    make_user("owner@shop.test")
    assert sign_in(api, email="  OWNER@Shop.Test ").json()["status"] == "ok"


def test_unknown_fields_in_the_login_body_are_rejected(api, make_user):
    make_user()
    response = api.post("/api/auth/login", json={"email": "owner@shop.test",
                                                 "password": PASSWORD, "role": "owner"})
    assert response.status_code == 422


def test_logout_revokes_the_session_on_the_server(api, make_user):
    make_user()
    sign_in(api)
    token = api.cookies.get(COOKIE_NAME)
    assert api.post("/api/auth/logout").status_code == 204
    assert api.get("/api/auth/me").status_code == 401
    api.cookies.set(COOKIE_NAME, token, path="/api")  # replay the stolen cookie
    assert api.get("/api/auth/me").status_code == 401


def test_a_new_sign_in_revokes_the_previous_session(api, make_user):
    make_user()
    sign_in(api)
    first = api.cookies.get(COOKIE_NAME)
    sign_in(api)
    assert api.cookies.get(COOKIE_NAME) != first
    with TestClient(api.app) as other:
        other.cookies.set(COOKIE_NAME, first, path="/api")
        assert other.get("/api/auth/me").status_code == 401


def test_the_fifth_failure_locks_the_account_with_retry_after(api, make_user):
    make_user()
    codes = [sign_in(api, password=f"wrong guess {i}").status_code for i in range(5)]
    assert codes == [401, 401, 401, 401, 423]
    locked = sign_in(api)  # even the right password
    assert locked.status_code == 423
    assert locked.json()["message_key"] == "error.account_locked"
    assert locked.json()["detail"] == {"retry_after_minutes": "15"}


def test_attempts_during_a_lock_neither_succeed_nor_extend_it(api, make_user, clock):
    make_user()
    for i in range(5):
        sign_in(api, password=f"wrong guess {i}")
    clock.advance(minutes=10)
    assert sign_in(api, password="wrong again").json()["detail"]["retry_after_minutes"] == "5"
    clock.advance(minutes=5)
    assert sign_in(api).json()["status"] == "ok"


def test_unknown_emails_lock_exactly_like_real_ones(api):
    codes = [sign_in(api, email="ghost@shop.test", password=f"guess {i}").status_code
             for i in range(6)]
    assert codes == [401, 401, 401, 401, 423, 423]


def test_totp_accounts_get_a_pending_session_that_opens_nothing_else(api, make_user):
    make_user(totp_secret=SECRET)
    assert sign_in(api).json() == {"status": "totp_required"}
    assert api.get("/api/auth/me").status_code == 401


def test_the_totp_step_completes_sign_in_and_rotates_the_token(api, make_user, clock):
    make_user(totp_secret=SECRET)
    sign_in(api)
    pending = api.cookies.get(COOKIE_NAME)
    response = api.post("/api/auth/login/totp", json={"code": totp.code_at(SECRET, clock())})
    assert response.status_code == 200 and response.json()["totp_enrolled"] is True
    assert api.cookies.get(COOKIE_NAME) != pending
    assert api.get("/api/auth/me").status_code == 200


def test_a_totp_code_cannot_complete_two_sign_ins(api, make_user, clock):
    make_user(totp_secret=SECRET)
    code = totp.code_at(SECRET, clock())
    sign_in(api)
    assert api.post("/api/auth/login/totp", json={"code": code}).status_code == 200
    sign_in(api)
    replay = api.post("/api/auth/login/totp", json={"code": code})
    assert replay.status_code == 401 and replay.json()["code"] == "invalid_totp"


def test_wrong_totp_codes_count_towards_the_lockout(api, make_user, clock):
    make_user(totp_secret=SECRET)
    right = totp.code_at(SECRET, clock())
    wrong = "000000" if right != "000000" else "111111"
    sign_in(api)
    statuses = [api.post("/api/auth/login/totp", json={"code": wrong}).status_code
                for _ in range(5)]
    assert statuses == [401, 401, 401, 401, 423]
    # the pending session is gone: the password is needed again, and it is locked
    assert api.post("/api/auth/login/totp", json={"code": right}).status_code == 401
    assert sign_in(api).status_code == 423


def test_the_pending_totp_step_expires_after_five_minutes(api, make_user, clock):
    make_user(totp_secret=SECRET)
    sign_in(api)
    clock.advance(minutes=5)
    late = api.post("/api/auth/login/totp", json={"code": totp.code_at(SECRET, clock())})
    assert late.status_code == 401 and late.json()["code"] == "not_authenticated"


def test_sessions_end_after_thirty_idle_minutes(api, make_user, clock):
    make_user()
    sign_in(api)
    clock.advance(minutes=29)
    assert api.get("/api/auth/me").status_code == 200
    clock.advance(minutes=30)
    assert api.get("/api/auth/me").status_code == 401


def test_expired_lender_access_cannot_sign_in(api, make_user, clock):
    make_user("bank@lender.test", role=Role.lender_viewer,
              expires_at=clock() + timedelta(days=1), scopes=("passport:read",))
    session = sign_in(api, email="bank@lender.test").json()["session"]
    assert session["principal"]["scopes"] == ["passport:read"]
    assert session["principal"]["expires_at"] is not None
    clock.advance(days=1)
    assert api.get("/api/auth/me").status_code == 401
    assert sign_in(api, email="bank@lender.test").status_code == 401


def test_totp_enrolment_then_sign_in_needs_the_code(api, make_user, clock):
    make_user()
    sign_in(api)
    enrolment = api.post("/api/auth/totp/enrol")
    assert enrolment.status_code == 200 and enrolment.headers["cache-control"] == "no-store"
    secret = enrolment.json()["secret"]
    assert secret in enrolment.json()["otpauth_uri"]
    assert api.post("/api/auth/totp/confirm", json={"code": "000000"}).status_code == 401
    confirmed = api.post("/api/auth/totp/confirm", json={"code": totp.code_at(secret, clock())})
    assert confirmed.json()["totp_enrolled"] is True
    assert api.post("/api/auth/totp/enrol").json()["code"] == "totp_already_enrolled"
    clock.advance(seconds=30)
    assert sign_in(api).json() == {"status": "totp_required"}


def test_an_unconfirmed_totp_secret_does_not_gate_sign_in(api, make_user):
    make_user()
    sign_in(api)
    api.post("/api/auth/totp/enrol")
    assert sign_in(api).json()["status"] == "ok"


def test_password_change_revokes_every_other_session(api, make_user):
    make_user()
    sign_in(api)
    with TestClient(api.app) as laptop:
        sign_in(laptop)
        changed = api.post("/api/auth/password", json={
            "current_password": PASSWORD, "new_password": "a whole new passphrase"})
        assert changed.status_code == 204
        assert laptop.get("/api/auth/me").status_code == 401
    assert api.get("/api/auth/me").status_code == 200
    assert sign_in(api).status_code == 401
    assert sign_in(api, password="a whole new passphrase").json()["status"] == "ok"


@pytest.mark.parametrize(("current", "new", "status", "code"), [
    ("not the password", "a whole new passphrase", 401, "invalid_credentials"),
    (PASSWORD, "too-short", 422, "weak_password"),
])
def test_password_change_refusals(api, make_user, current, new, status, code):
    make_user()
    sign_in(api)
    response = api.post("/api/auth/password",
                        json={"current_password": current, "new_password": new})
    assert response.status_code == status and response.json()["code"] == code


def test_stored_hashes_are_upgraded_when_parameters_change(api, app, make_user):
    make_user()
    passwords.use_parameters(RFC_9106_LOW_MEMORY)
    try:
        assert sign_in(api).json()["status"] == "ok"
    finally:
        passwords.use_parameters(CHEAPEST)
    with app.state.session_factory() as session:
        stored = session.scalars(select(UserRow).where(UserRow.email == "owner@shop.test")).one()
        assert "m=65536,t=3,p=4" in stored.password_hash


def test_demo_accounts_cover_every_role_and_publish_owner_codes(api, settings, clock):
    listing = api.get("/api/auth/demo-accounts").json()
    assert {row["role"] for row in listing} == {role.value for role in Role}
    owner = next(row for row in listing if row["email"] == "owner@grocery.hishab.test")
    assert owner["business_name"] == "Mirpur Mudi Store"
    secret = demo_totp_secret(settings, owner["email"])
    assert owner["totp_hint"] == totp.code_at(secret, clock())
    assert sign_in(api, owner["email"], owner["password"]).json() == {"status": "totp_required"}
    session = api.post("/api/auth/login/totp", json={"code": owner["totp_hint"]}).json()
    assert session["data_mode"] == "synthetic"


def test_every_demo_account_can_sign_in_in_demo_mode(api):
    api.get("/api/auth/demo-accounts")
    for demo in DEMO_ACCOUNTS:
        expected = "totp_required" if demo.totp else "ok"
        assert sign_in(api, demo.email, demo.password).json()["status"] == expected


def test_demo_accounts_are_neither_listed_nor_usable_outside_demo_mode(tmp_path):
    url = f"sqlite:///{tmp_path / 'hishab.db'}"
    base = {"_env_file": None, "app_env": "test", "database_url": url,
            "llm_mode": "fixtures", "chain_mode": "offline"}
    with TestClient(create_app(Settings(**base, demo_mode=True))) as demo:
        assert demo.get("/api/auth/demo-accounts").status_code == 200  # seeds the accounts
    with TestClient(create_app(Settings(**base, demo_mode=False))) as live:
        assert live.get("/api/auth/demo-accounts").json()["code"] == "not_found"
        response = sign_in(live, "staff@grocery.hishab.test", "hishab-demo-staff")
        assert response.status_code == 401
