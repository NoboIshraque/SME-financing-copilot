"""Market API (WP-09): real TCB prices with source and date, alerts that /explain opens."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.api import market
from app.contracts import Principal, Role
from app.security.deps import current_principal

OWNER = Principal(user_id="u-owner", tenant_id="sme_grocery", role=Role.owner)


@pytest.fixture
def api(client: TestClient) -> TestClient:
    client.app.state.security_clock = lambda: datetime(2026, 10, 20, 6, tzinfo=UTC)
    client.app.dependency_overrides[current_principal] = lambda: OWNER
    return client


def test_prices_are_tcbs_published_lists_with_source_url_and_date(api: TestClient):
    body = api.get("/api/market/prices").json()
    assert len(body) == 13
    rice = next(item for item in body if item["commodity"] == "rice_coarse")
    assert rice["latest"]["source"] == "tcb" and rice["latest"]["data_mode"] == "public"
    assert rice["latest"]["source_url"].startswith("https://objectstorage.")
    assert rice["latest"]["observed_on"] == rice["published_on"] == "2026-10-19"
    assert rice["latest"]["price"]["amount"] == "52.50"
    assert rice["baseline_basis"] == "median_4w" and rice["baseline_points"] >= 4
    assert len(rice["history"]) > 4
    assert all(p["observed_on"] <= "2026-10-19" for p in rice["history"])


def test_change_is_against_the_four_week_median(api: TestClient):
    chickpea = next(i for i in api.get("/api/market/prices").json()
                    if i["commodity"] == "chickpea")
    latest = Decimal(chickpea["latest"]["price"]["amount"])
    median = Decimal(chickpea["median_4w"]["amount"])
    assert Decimal(chickpea["change_pct"]) == ((latest - median) / median * 100).quantize(
        Decimal("0.1"))


def test_alerts_flag_tcbs_chickpea_rise_and_explain_opens_the_figure(api: TestClient):
    body = api.get("/api/market/alerts").json()
    assert [a["commodity"] for a in body] == ["chickpea"]
    alert = body[0]
    assert alert["direction"] == "rise" and alert["published_on"] == "2026-10-19"
    assert alert["change"]["provenance"]["formula_id"] == "market.change_vs_4w_median"
    explained = api.get(f"/api/explain/{alert['change']['id']}").json()
    assert Decimal(explained["value"]) == Decimal(alert["change"]["value"])
    assert explained["formula"]["formula_id"] == "market.change_vs_4w_median"


def test_asking_twice_records_the_same_alert_figure(api: TestClient):
    first = api.get("/api/market/alerts").json()
    assert api.get("/api/market/alerts").json() == first


def test_with_no_saved_price_list_both_routes_abstain(api: TestClient, tmp_path, monkeypatch):
    monkeypatch.setattr(market, "PRICE_DIR", tmp_path)
    for path in ("/api/market/prices", "/api/market/alerts"):
        response = api.get(path)
        assert response.status_code == 422
        assert response.json()["detail"] == {"missing": "price_snapshot"}


def test_market_needs_a_signed_in_user(client: TestClient):
    assert client.get("/api/market/prices").status_code == 401
