from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.contracts import Principal, Role
from app.facts import FactStore
from app.facts.seed import load_sme_into
from app.security.deps import current_principal

OWNER = Principal(user_id="u-owner", tenant_id="sme_grocery", role=Role.owner)


@pytest.fixture
def api(client: TestClient, universe) -> TestClient:
    with client.app.state.session_factory() as session:
        load_sme_into(FactStore(session), universe.smes["sme_grocery"], universe.start,
                      universe.as_of)
        session.commit()
    client.app.state.security_clock = lambda: datetime(2026, 10, 19, 6, tzinfo=UTC)
    client.app.dependency_overrides[current_principal] = lambda: OWNER
    return client


def test_overview_ages_open_invoices_and_agrees_with_the_fact_ledger(api: TestClient):
    body = api.get("/api/receivables").json()
    assert body["as_of"] == "2026-09-30"  # the synthetic ledger stops before today
    figures = {f["label_key"]: f for f in body["figures"]}
    open_total = sum(Decimal(a["amount"]["amount"]) for a in body["aging"])
    assert Decimal(figures["receivables.open"]["value"]) == open_total
    assert figures["receivables.dso"]["provenance"]["formula_id"] == "receivables.dso"
    overdue = figures["receivables.overdue"]
    assert Decimal(overdue["value"]) == sum(
        Decimal(r["invoice"]["amount"]["amount"]) - Decimal(r["invoice"]["amount_paid"]["amount"])
        for r in body["invoices"] if r["days_overdue"] > 0)
    assert sum(a["count"] for a in body["aging"]) == len(body["invoices"])


def test_invoices_are_riskiest_first_and_customers_are_never_named(api: TestClient):
    body = api.get("/api/receivables").json()
    scores = [Decimal(r["risk_score"]) for r in body["invoices"]]
    assert scores == sorted(scores, reverse=True)
    labels = {r["counterparty_label"] for r in body["invoices"]}
    assert all(label.startswith("Customer ") for label in labels)
    assert all(c["credit_limit"] is None and c["stop_credit"] is False
               for c in body["customers"])  # credit limits were cut


def test_plan_offers_one_reminder_per_customer_with_open_invoices(api: TestClient):
    overview = api.get("/api/receivables").json()
    cards = api.get("/api/receivables/plan").json()["reminders"]
    assert len(cards) == len({r["invoice"]["counterparty_token"] for r in overview["invoices"]})
    assert {c["tier"] for c in cards} == {"EXECUTE"}
    assert [c["payload"]["send_on"] for c in cards] == sorted(c["payload"]["send_on"]
                                                              for c in cards)


def test_a_business_with_no_ledger_gets_an_abstention(api: TestClient):
    api.app.dependency_overrides[current_principal] = lambda: Principal(
        user_id="u-new", tenant_id="sme_new", role=Role.owner)
    for path in ("/api/receivables", "/api/receivables/plan"):
        res = api.get(path)
        assert (res.status_code, res.json()["code"]) == (422, "not_enough_data")


def test_receivables_need_ledger_access(api: TestClient):
    api.app.dependency_overrides[current_principal] = lambda: Principal(
        user_id="u-l", tenant_id="sme_grocery", role=Role.lender_viewer, scopes=("passport:read",),
        expires_at=datetime(2026, 12, 1, tzinfo=UTC))
    assert api.get("/api/receivables").status_code == 403
    api.app.dependency_overrides.pop(current_principal)
    assert api.get("/api/receivables").status_code == 401
