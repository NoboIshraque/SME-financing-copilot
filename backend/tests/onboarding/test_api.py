"""Self-service shops (judges sign up and run the app on their own numbers)."""

from datetime import UTC, datetime

import pytest
from argon2.profiles import CHEAPEST
from fastapi.testclient import TestClient

from app.api.onboarding import template_rows
from app.main import create_app
from app.security import passwords
from app.settings import Settings

NOW = datetime(2026, 10, 20, 4, 0, tzinfo=UTC)
PASSWORD = "a long judge password 2026"
SHOP = {"business_name": "Judge Test Store", "email": "judge@example.org", "password": PASSWORD}


@pytest.fixture
def api(client: TestClient) -> TestClient:
    client.app.state.security_clock = lambda: NOW
    return client


def _signup(api: TestClient, **change) -> object:
    return api.post("/api/onboarding/signup", json={**SHOP, **change})


def test_signup_creates_a_live_shop_and_signs_the_owner_in(api: TestClient):
    res = _signup(api)
    assert res.status_code == 201, res.text
    session = res.json()
    assert session["principal"]["role"] == "owner"
    assert session["principal"]["tenant_id"].startswith("shop-")
    assert (session["data_mode"], session["business_name"]) == ("live", "Judge Test Store")
    assert api.get("/api/auth/me").json()["principal"] == session["principal"]


def test_each_signup_is_its_own_tenant_and_emails_are_unique(api: TestClient):
    first = _signup(api).json()["principal"]["tenant_id"]
    api.post("/api/auth/logout")
    second = _signup(api, email="other@example.org").json()["principal"]["tenant_id"]
    assert first != second
    taken = _signup(api)
    assert (taken.status_code, taken.json()["code"]) == (422, "email_taken")


def test_weak_passwords_are_refused(api: TestClient):
    res = _signup(api, password="short")
    assert (res.status_code, res.json()["code"]) == (422, "weak_password")


def test_signup_is_closed_outside_demo_mode():
    settings = Settings(_env_file=None, app_env="test", demo_mode=False, database_url="sqlite://",
                        llm_mode="fixtures", chain_mode="offline")
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/onboarding/signup", json=SHOP).status_code == 404


def test_signups_stop_at_the_cap(api: TestClient, monkeypatch):
    monkeypatch.setattr("app.api.onboarding.MAX_SHOPS", 1)
    assert _signup(api).status_code == 201
    api.post("/api/auth/logout")
    res = _signup(api, email="late@example.org")
    assert (res.status_code, res.json()["code"]) == (403, "signup_closed")


def test_the_profile_needs_a_date_with_the_opening_balance_and_no_future_date(api: TestClient):
    _signup(api)
    res = api.post("/api/onboarding/profile", json={"opening_balance": "50000.00"})
    assert res.json()["code"] == "opening_needs_both"
    res = api.post("/api/onboarding/profile",
                   json={"opening_balance": "50000.00", "opening_date": "2026-11-01"})
    assert res.json()["code"] == "date_in_future"


def test_a_corrected_opening_balance_replaces_the_first(api: TestClient):
    _signup(api)
    for amount in ("50000.00", "65000.00"):
        api.post("/api/onboarding/profile",
                 json={"opening_balance": amount, "opening_date": "2026-06-22"})
    assert api.get("/api/onboarding/profile").json()["opening_balance"] == "65000.00"


def test_the_template_is_a_dated_example_ledger_ending_yesterday():
    rows = template_rows(NOW.date())
    assert rows[0] == ["date", "type", "amount", "party", "category", "channel", "ref"]
    assert rows[-1][0] <= "2026-10-19" and rows[1][0] == "2026-06-22"
    assert {r[1] for r in rows[1:]} == {"in", "out"}


def test_a_judge_signs_up_enters_the_opening_balance_uploads_and_gets_a_live_forecast(
        api: TestClient):
    """The whole journey on the judge's own numbers: no synthetic data anywhere."""
    _signup(api)
    profile = api.post("/api/onboarding/profile", json={
        "opening_balance": "80000.00", "opening_date": "2026-06-22", "business_age_months": 30,
        "trade_licence": True, "etin_registered": False, "staff_count": 3})
    assert profile.status_code == 200, profile.text
    assert profile.json()["trade_licence"] is True
    csv_bytes = api.get("/api/onboarding/template.csv").content
    preview = api.post("/api/ingest/preview",
                       files={"file": ("my-ledger.csv", csv_bytes, "text/csv")}).json()
    assert preview["data_mode"] == "live", preview
    committed = api.post("/api/ingest/commit", json={
        "preview_id": preview["preview_id"], "file_digest": preview["file_digest"]})
    assert committed.status_code == 200 and committed.json()["transactions"] > 100
    forecast = api.get("/api/cash/forecast")
    assert forecast.status_code == 200, forecast.text
    assert forecast.json()["band"]["data_mode"] == "live"
    match = api.post("/api/financing/match", json={
        "amount": {"amount": "200000.00"}, "needed_by": "2026-11-15", "tenor_days": 365})
    assert match.status_code == 200 and match.json()["data_mode"] == "live"


@pytest.fixture(autouse=True)
def cheap_hashing():
    previous = passwords.use_parameters(CHEAPEST)
    yield
    passwords.use_parameters(previous)
