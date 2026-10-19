from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.api.financing import lender_events
from app.contracts import Principal, Role, Unit
from app.engines.financing.lenders import LenderEvent
from app.facts import FactStore
from app.facts.seed import _raw, load_sme_into
from app.security.deps import current_principal

NOW = datetime(2026, 10, 1, 4, 0, tzinfo=UTC)  # 10:00 in Dhaka
OWNER = Principal(user_id="u-owner", tenant_id="sme_grocery", role=Role.owner)
NEED = {"amount": {"amount": "200000.00"}, "needed_by": "2026-10-10", "tenor_days": 365}
CITY = "The City Bank PLC (via bKash)"


@pytest.fixture
def api(client: TestClient, universe) -> TestClient:
    with client.app.state.session_factory() as session:
        load_sme_into(FactStore(session), universe.smes["sme_grocery"], universe.start,
                      universe.as_of)
        session.commit()
    client.app.state.security_clock = lambda: NOW
    _as(client, OWNER)
    return client


def _as(client: TestClient, principal: Principal | None) -> None:
    if principal is None:
        client.app.dependency_overrides.pop(current_principal, None)
    else:
        client.app.dependency_overrides[current_principal] = lambda: principal


def _events(client: TestClient, *events: LenderEvent) -> None:
    client.app.dependency_overrides[lender_events] = lambda: tuple(events)


def _by_id(body: dict) -> dict[str, dict]:
    return {o["product"]["id"]: o for o in body["options"]}


def test_match_ranks_the_catalogue_on_the_callers_own_facts(api: TestClient):
    res = api.post("/api/financing/match", json=NEED)
    assert res.status_code == 200
    body = res.json()
    assert body["need"]["tenant_id"] == "sme_grocery"
    assert body["as_of"] == "2026-10-01"
    assert [o["rank"] for o in body["options"]] == list(range(1, len(body["options"]) + 1))
    options = _by_id(body)
    # the grocery holds a trade licence and is 74 months old (synthetic profile facts)
    assert options["bd-primebank-chalti"]["eligibility"]["status"] == "pass"
    # no ledger fact says the owner is a woman: not on record, never a pass
    assert options["bd-bb-women-refinance"]["eligibility"]["status"] == "not_on_record"
    assert {"owner_is_woman", "collateral_available"} <= set(body["facts_missing"])
    assert "business_age_months" not in body["facts_missing"]
    assert body["data_mode"] == "synthetic"


def test_match_without_facts_abstains_instead_of_passing_rules(api: TestClient):
    _as(api, Principal(user_id="u-new", tenant_id="sme_new", role=Role.owner))
    body = api.post("/api/financing/match", json=NEED).json()
    ruled = [o for o in body["options"] if o["product"]["rules"]]
    assert ruled and all(o["eligibility"]["status"] != "pass" for o in ruled)
    assert "trade_licence" in body["facts_missing"]
    assert body["data_mode"] == "public"


def test_every_option_says_it_was_ranked_without_a_forecast(api: TestClient):
    options = api.post("/api/financing/match", json=NEED).json()["options"]
    assert all("fit.no_forecast" in o["reason_keys"] for o in options)
    assert all(Decimal(o["p_buffer_breach"]) == 0 for o in options)


def test_figures_carry_their_formula(api: TestClient):
    option = _by_id(api.post("/api/financing/match", json=NEED).json())["bd-primebank-chalti"]
    ear = next(f for f in option["figures"] if f["label_key"] == "financing.effective_apr")
    assert Decimal(ear["value"]) == Decimal(option["effective_apr"])
    assert ear["provenance"]["formula_id"] == "financing.effective_annual_rate"
    assert ear["provenance"]["parameters"]["principal"] == "200000.00"


def test_unpriced_products_are_listed_to_ask_not_ranked(api: TestClient):
    body = api.post("/api/financing/match", json=NEED).json()
    asked = {u["id"] for u in body["ask_the_lender"]}
    assert "bd-bracbank-bkash-merchant-loan" in asked
    assert asked.isdisjoint(_by_id(body))
    assert all(u["source_url"].startswith("https://") for u in body["ask_the_lender"])


def test_china_pack_is_ranked_as_modelled(api: TestClient):
    body = api.post("/api/financing/match", json={**NEED, "jurisdiction": "cn"}).json()
    assert body["options"]
    assert all(o["product"]["is_modelled"] for o in body["options"])


@pytest.mark.parametrize("change, code", [
    ({"amount": {"amount": 200000.5}}, None),  # floats are refused for money
    ({"needed_by": "2026-09-30"}, "needed_by_in_past"),
    ({"jurisdiction": "us"}, None),
])
def test_match_refuses_bad_needs(api: TestClient, change: dict, code: str | None):
    res = api.post("/api/financing/match", json={**NEED, **change})
    assert res.status_code == 422
    if code:
        assert res.json()["code"] == code


def test_body_tenant_must_be_the_callers_own(api: TestClient):
    own = api.post("/api/financing/match", json={**NEED, "tenant_id": "sme_grocery"})
    other = api.post("/api/financing/match", json={**NEED, "tenant_id": "sme_fabric"})
    assert (own.status_code, own.json()["need"]["tenant_id"]) == (200, "sme_grocery")
    assert (other.status_code, other.json()["detail"]["reason"]) == (403, "tenant")


def test_web_purpose_keys_reach_the_purpose_rules(api: TestClient):
    def leasing(purpose: str) -> str:
        body = api.post("/api/financing/match", json={**NEED, "purpose_key": purpose}).json()
        return _by_id(body)["bd-bankasia-lease"]["eligibility"]["status"]
    assert leasing("purpose.working_capital") == "fail"  # leasing funds equipment only
    assert leasing("purpose.equipment") != "fail"


def test_match_lists_a_profile_for_every_provider_ranked(api: TestClient):
    body = api.post("/api/financing/match", json=NEED).json()
    names = {lender["name"] for lender in body["lenders"]}
    assert names == {o["product"]["provider"] for o in body["options"]}
    prime = next(lender for lender in body["lenders"] if lender["name"] == "Prime Bank PLC")
    assert (prime["events_count"], prime["licence_status"]) == (0, "unknown")


def test_match_drafts_the_application_for_the_best_passing_option(api: TestClient):
    body = api.post("/api/financing/match", json=NEED).json()
    best = next(o for o in body["options"] if o["eligibility"]["status"] == "pass")
    card = body["application"]
    assert (card["tier"], card["payload"]["product_id"]) == ("EXECUTE", best["product"]["id"])


def test_match_offers_staff_no_application(api: TestClient):
    _as(api, Principal(user_id="u-staff", tenant_id="sme_grocery", role=Role.staff))
    body = api.post("/api/financing/match", json=NEED).json()
    assert body["options"] and body["application"] is None


def test_without_facts_the_application_skips_options_not_on_record(api: TestClient):
    _as(api, Principal(user_id="u-new", tenant_id="sme_new", role=Role.owner))
    body = api.post("/api/financing/match", json=NEED).json()
    chosen = _by_id(body)[body["application"]["payload"]["product_id"]]
    assert chosen["eligibility"]["status"] == "pass"
    assert any(o["eligibility"]["status"] == "not_on_record" and o["rank"] < chosen["rank"]
               for o in body["options"])
    assert body["application"]["payload"]["facts_provided"] == {}


def test_match_needs_a_signed_in_caller_with_ledger_access(api: TestClient):
    _as(api, None)
    assert api.post("/api/financing/match", json=NEED).status_code == 401
    lender = Principal(user_id="u-l", tenant_id="sme_grocery", role=Role.lender_viewer,
                       scopes=("passport:read",), expires_at=datetime(2026, 12, 1, tzinfo=UTC))
    _as(api, lender)
    res = api.post("/api/financing/match", json=NEED)
    assert (res.status_code, res.json()["code"]) == (403, "forbidden")


def test_track_record_changes_the_lender_term(api: TestClient):
    cold = _by_id(api.post("/api/financing/match", json=NEED).json())["bd-primebank-chalti"]
    _events(api, LenderEvent("Prime Bank PLC", Decimal("9"), Decimal("14"), 3, hidden_fee=True,
                             disputed=True))
    body = api.post("/api/financing/match", json=NEED).json()
    warm = _by_id(body)["bd-primebank-chalti"]
    assert "lender.no_track_record" in cold["reason_keys"]
    assert "lender.no_track_record" not in warm["reason_keys"]
    assert Decimal(warm["score"]) < Decimal(cold["score"])
    assert body["data_mode"] == "synthetic"


def test_lender_without_track_record_is_cold_start_with_unknown_licence(api: TestClient):
    res = api.get(f"/api/financing/lenders/{CITY}")
    assert res.status_code == 200
    profile = res.json()
    assert (profile["lender_id"], profile["name"], profile["events_count"]) == (CITY, CITY, 0)
    assert profile["licence_status"] == "unknown"
    assert profile["data_mode"] == "public"


def test_lender_profile_reflects_hidden_fees(api: TestClient):
    _events(api, LenderEvent(CITY, Decimal("9"), Decimal("9"), 2, False, False),
            LenderEvent(CITY, Decimal("9"), Decimal("11"), 4, hidden_fee=True, disputed=False),
            LenderEvent("Someone Else", Decimal("9"), Decimal("30"), 9, True, True))
    profile = api.get(f"/api/financing/lenders/{CITY}").json()
    assert (profile["events_count"], profile["hidden_fee_incidents"]) == (2, 1)
    assert Decimal(profile["quoted_vs_realised_apr_gap"]) == Decimal("1.00")
    assert Decimal(profile["median_disbursal_days"]) == Decimal(3)
    assert profile["data_mode"] == "synthetic"


def test_unknown_lender_is_not_found(api: TestClient):
    res = api.get("/api/financing/lenders/Not a lender")
    assert (res.status_code, res.json()["code"]) == (404, "lender_not_found")


def test_owner_drafts_an_application_pack_from_ledger_facts(api: TestClient):
    res = api.post("/api/financing/applications",
                   json={**NEED, "product_id": "bd-primebank-chalti"})
    assert res.status_code == 201
    card = res.json()
    assert (card["action_type"], card["tier"]) == ("submit_loan_application", "EXECUTE")
    assert card["payload"]["facts_provided"] == {"business_age_months": "74",
                                                 "trade_licence": "1"}
    assert card["payload"]["amount"] == "200000.00"
    assert card["expires_at"].startswith("2026-10-02T04:00")


def test_staff_may_not_draft_an_application(api: TestClient):
    _as(api, Principal(user_id="u-staff", tenant_id="sme_grocery", role=Role.staff))
    res = api.post("/api/financing/applications",
                   json={**NEED, "product_id": "bd-primebank-chalti"})
    assert (res.status_code, res.json()["detail"]["reason"]) == (403, "tier")


def test_no_application_for_a_product_the_business_fails(api: TestClient):
    young = Principal(user_id="u-young", tenant_id="sme_young", role=Role.owner)
    with api.app.state.session_factory() as session:
        FactStore(session).put_fact(_raw("sme_young", "business_age_months", Decimal(12),
                                         Unit.count, date(2026, 9, 30), "profile.json#age"))
        session.commit()
    _as(api, young)
    res = api.post("/api/financing/applications",
                   json={**NEED, "product_id": "bd-primebank-chalti"})
    assert (res.status_code, res.json()["code"]) == (422, "not_eligible")


def test_application_for_an_unknown_product_is_not_found(api: TestClient):
    res = api.post("/api/financing/applications", json={**NEED, "product_id": "bd-nope"})
    assert (res.status_code, res.json()["code"]) == (404, "product_not_found")
