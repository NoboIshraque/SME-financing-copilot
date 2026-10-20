"""B1: the first demo owner sign-in on the hosted site. The published demo code must be the one
the server accepts at the moment the owner types it, also when the code was just used."""

from app.security import totp
from app.security.demo import demo_totp_secret
from tests.security.conftest import sign_in

OWNER = "owner@grocery.hishab.test"
OWNER_PASSWORD = "hishab-demo-owner"


def owner_hint(api) -> str:
    listing = api.get("/api/auth/demo-accounts").json()
    return next(row["totp_hint"] for row in listing if row["email"] == OWNER)


def test_the_very_first_request_to_a_fresh_server_can_be_the_owner_login(api, settings, clock):
    # No demo-accounts call first: login itself must seed the demo tenants and accounts.
    assert sign_in(api, OWNER, OWNER_PASSWORD).json() == {"status": "totp_required"}
    code = totp.code_at(demo_totp_secret(settings, OWNER), clock())
    response = api.post("/api/auth/login/totp", json={"code": code})
    assert response.status_code == 200 and response.json()["principal"]["role"] == "owner"


def test_a_second_sign_in_in_the_same_30_seconds_gets_a_fresh_working_code(api, clock):
    first = owner_hint(api)
    sign_in(api, OWNER, OWNER_PASSWORD)
    assert api.post("/api/auth/login/totp", json={"code": first}).status_code == 200
    api.post("/api/auth/logout")

    clock.advance(seconds=5)  # same 30-second step: the code just used would be a replay
    second = owner_hint(api)
    assert second != first
    sign_in(api, OWNER, OWNER_PASSWORD)
    assert api.post("/api/auth/login/totp", json={"code": second}).status_code == 200


def test_a_code_shown_more_than_a_minute_ago_is_refused_so_the_page_must_refresh_it(api, clock):
    stale = owner_hint(api)
    clock.advance(seconds=75)
    sign_in(api, OWNER, OWNER_PASSWORD)
    refused = api.post("/api/auth/login/totp", json={"code": stale})
    assert refused.status_code == 401 and refused.json()["code"] == "invalid_totp"
    assert api.post("/api/auth/login/totp", json={"code": owner_hint(api)}).status_code == 200
