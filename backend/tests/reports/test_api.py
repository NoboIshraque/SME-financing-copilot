from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.contracts import PassportVersion, Principal, Role
from app.facts import FactStore
from app.facts.seed import load_sme_into
from app.reports.models import PassportRow
from app.security.deps import StepUp, current_principal, step_up
from app.security.errors import SecurityProblem

OWNER = Principal(user_id="u-owner", tenant_id="sme_grocery", role=Role.owner)
LENDER = Principal(user_id="u-l", tenant_id="sme_grocery", role=Role.lender_viewer,
                   scopes=("passport:read",), expires_at=datetime(2026, 12, 1, tzinfo=UTC))
SHARE = {"lender_label": "City Bank SME desk", "scopes": ["passport:read"], "days": 14}


@pytest.fixture
def api(client: TestClient, universe) -> TestClient:
    with client.app.state.session_factory() as session:
        load_sme_into(FactStore(session), universe.smes["sme_grocery"], universe.start,
                      universe.as_of)
        session.commit()
    client.app.state.security_clock = lambda: datetime(2026, 10, 19, 6, tzinfo=UTC)
    _as(client, OWNER)
    client.app.dependency_overrides[step_up] = lambda: StepUp(None, None)  # code verified
    return client


def _as(client: TestClient, principal: Principal | None) -> None:
    if principal is None:
        client.app.dependency_overrides.pop(current_principal, None)
    else:
        client.app.dependency_overrides[current_principal] = lambda: principal


def test_a_demo_shop_gets_version_one_on_first_read(api: TestClient):
    listed = api.get("/api/reports/passport").json()
    assert [p["version"] for p in listed] == [1]
    assert api.get("/api/reports/passport").json() == listed  # issued once, not on every read


def test_owner_issues_versioned_anchored_passports_from_the_ledger(api: TestClient):
    first = api.post("/api/reports/passport").json()
    second = api.post("/api/reports/passport").json()
    assert (first["version"], second["version"]) == (1, 2)
    assert [p["version"] for p in api.get("/api/reports/passport").json()] == [2, 1]
    kinds = {e["kind"] for e in first["evidence"]}
    assert kinds == {"mobile_money_statement", "trade_licence", "etin"}
    assert not any(e["verified"] for e in first["evidence"])  # recorded, not third-party checked
    assert first["anchor"]["chain"] == "offline" and first["data_mode"] == "synthetic"
    assert first["digest"] != second["digest"]  # a fresh salt per version


def test_anyone_can_verify_without_signing_in_and_an_edit_is_caught(api: TestClient):
    passport = api.post("/api/reports/passport").json()
    _as(api, None)
    good = api.get(f"/api/verify/{passport['id']}").json()
    assert (good["valid"], good["recomputed_digest"]) == (True, passport["digest"])
    with api.app.state.session_factory() as db:
        row = db.get(PassportRow, passport["id"])
        edited = PassportVersion.model_validate_json(row.payload)
        row.payload = edited.model_copy(update={"attestations_confirmed": 9}).model_dump_json()
        db.commit()
    assert api.get(f"/api/verify/{passport['id']}").json()["valid"] is False
    assert api.get("/api/verify/pp-nobody-v1").status_code == 404


def test_no_evidence_no_passport(api: TestClient):
    _as(api, Principal(user_id="u-new", tenant_id="sme_new", role=Role.owner))
    res = api.post("/api/reports/passport")
    assert (res.status_code, res.json()["code"]) == (422, "not_enough_evidence")


def test_sharing_needs_the_owners_code_and_can_be_revoked(api: TestClient):
    passport_id = api.post("/api/reports/passport").json()["id"]
    api.app.dependency_overrides[step_up] = lambda: StepUp(
        None, SecurityProblem(401, "step_up_required", "error.step_up_required"))
    refused = api.post(f"/api/reports/passport/{passport_id}/share", json=SHARE)
    assert (refused.status_code, refused.json()["code"]) == (401, "step_up_required")
    api.app.dependency_overrides[step_up] = lambda: StepUp(None, None)
    grant = api.post(f"/api/reports/passport/{passport_id}/share", json=SHARE).json()
    assert (grant["scopes"], grant["revoked"]) == (["passport:read"], False)
    revoked = api.post(f"/api/reports/shares/{grant['id']}/revoke").json()
    assert revoked["revoked"] is True
    assert api.get("/api/reports/shares").json()[0]["revoked"] is True


@pytest.mark.parametrize("change, status", [
    ({"days": 31}, 422),                    # at most 30 days
    ({"scopes": ["ledger:read"]}, 422),     # only passport scopes can be shared
])
def test_a_share_beyond_the_rules_is_refused(api: TestClient, change, status):
    passport_id = api.post("/api/reports/passport").json()["id"]
    res = api.post(f"/api/reports/passport/{passport_id}/share", json={**SHARE, **change})
    assert res.status_code == status


def test_a_consented_lender_reads_passports_but_cannot_issue_or_share(api: TestClient):
    passport_id = api.post("/api/reports/passport").json()["id"]
    _as(api, LENDER)
    assert [p["id"] for p in api.get("/api/reports/passport").json()] == [passport_id]
    assert api.post("/api/reports/passport").status_code == 403
    assert api.post(f"/api/reports/passport/{passport_id}/share", json=SHARE).status_code == 403


def test_staff_cannot_read_passports(api: TestClient):
    _as(api, Principal(user_id="u-s", tenant_id="sme_grocery", role=Role.staff))
    assert api.get("/api/reports/passport").status_code == 403
