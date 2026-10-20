"""Mesh API (WP-08 milestone 8): real sign-in with TOTP, so step-up is exercised end to end."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from argon2.profiles import CHEAPEST
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.contracts import DataMode, NettingRound, Role
from app.engines.mesh.models import NettingRoundRow
from app.main import create_app
from app.security import passwords, totp
from app.security.accounts import Accounts
from app.security.audit import AuditLog
from app.settings import Settings

SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
PASSWORD = "correct horse battery staple"
RING = ("sme_fabric", "sme_garment", "sme_hardware")
NAMES = {"sme_fabric": "Islampur Fabric House", "sme_garment": "Ashulia Stitch Works",
         "sme_hardware": "Nawabpur Hardware Traders", "sme_grocery": "Bismillah Store"}


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 1, 4, 0, 7, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


@pytest.fixture(autouse=True)
def cheap_hashing() -> Iterator[None]:
    previous = passwords.use_parameters(CHEAPEST)
    yield
    passwords.use_parameters(previous)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def app(settings: Settings, clock: Clock) -> Iterator[FastAPI]:
    application = create_app(settings)
    application.state.security_clock = clock
    with TestClient(application):  # run startup so tables exist
        with application.state.session_factory() as db:
            accounts = Accounts(db, application.state.settings)
            for tenant, name in NAMES.items():
                accounts.ensure_tenant(tenant, name, DataMode.synthetic, clock())
                email = f"owner@{tenant.replace('_', '-')}.test"
                owner = accounts.create_user(email=email, password=PASSWORD,
                                             tenant_id=tenant, role=Role.owner,
                                             display_name="Owner", now=clock())
                accounts.set_totp_secret(owner, SECRET, enrolled=True)
            for role in (Role.accountant, Role.staff, Role.lender_viewer):
                accounts.create_user(email=f"{role.value}@sme-garment.test", password=PASSWORD,
                                     tenant_id="sme_garment", role=role, display_name=role.value,
                                     now=clock(), scopes=("passport:read",)
                                     if role is Role.lender_viewer else (),
                                     expires_at=clock() + timedelta(days=30)
                                     if role is Role.lender_viewer else None)
            db.commit()
        yield application


@pytest.fixture
def as_user(app: FastAPI, clock: Clock):
    clients: list[TestClient] = []

    def sign_in(tenant: str, role: Role = Role.owner) -> TestClient:
        client = TestClient(app)
        clients.append(client)
        email = f"{role.value}@{tenant.replace('_', '-')}.test"
        answer = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
        if answer.json().get("status") == "totp_required":
            client.post("/api/auth/login/totp", json={"code": totp.code_at(SECRET, clock())})
            clock.advance(seconds=30)
        return client

    yield sign_in
    for client in clients:
        client.close()


def code(clock: Clock) -> dict[str, str]:
    value = totp.code_at(SECRET, clock())
    clock.advance(seconds=30)  # a code is accepted once
    return {"X-Step-Up-Code": value}


def proposed(client: TestClient) -> dict:
    res = client.post("/api/mesh/rounds/propose")
    assert res.status_code == 200, res.text
    return res.json()


def test_a_ring_member_sees_the_ring_with_business_names(as_user):
    body = as_user("sme_garment").get("/api/mesh/obligations").json()
    assert {o["id"] for o in body["obligations"]} == {"RING-FG-001", "RING-GH-001", "RING-HF-001"}
    assert body["labels"] == {t: NAMES[t] for t in RING}
    assert {o["data_mode"] for o in body["obligations"]} == {"synthetic"}


def test_a_business_outside_the_ring_sees_none_of_it(as_user):
    grocery = as_user("sme_grocery")
    assert grocery.get("/api/mesh/obligations").json() == {"obligations": [], "labels": {}}
    res = grocery.post("/api/mesh/rounds/propose")
    assert (res.status_code, res.json()["code"]) == (409, "nothing_to_net")


def test_mesh_needs_a_signed_in_caller_with_ledger_access(app, as_user):
    assert TestClient(app).get("/api/mesh/obligations").status_code == 401
    lender = as_user("sme_garment", Role.lender_viewer)
    assert lender.get("/api/mesh/obligations").status_code == 403


def test_proposing_nets_the_ring_and_repeating_returns_the_same_round(as_user):
    garment = as_user("sme_garment")
    first = proposed(garment)
    again = proposed(as_user("sme_fabric"))
    assert again["id"] == first["id"]
    assert sorted(first["participants"]) == list(RING)
    gross, net = Decimal(first["gross_total"]["amount"]), Decimal(first["net_total"]["amount"])
    assert gross == Decimal("1150000.00") and Decimal(0) < net < gross
    assert (first["status"], first["data_mode"]) == ("proposed", "synthetic")
    assert [r["id"] for r in garment.get("/api/mesh/rounds").json()] == [first["id"]]


def test_an_accountant_may_propose_but_staff_may_not(as_user):
    assert as_user("sme_garment", Role.accountant).post("/api/mesh/rounds/propose").status_code \
        == 200
    res = as_user("sme_garment", Role.staff).post("/api/mesh/rounds/propose")
    assert (res.status_code, res.json()["detail"]["reason"]) == (403, "tier")


def test_approving_needs_the_owner_and_a_fresh_code(as_user, clock):
    round_id = proposed(as_user("sme_garment"))["id"]
    owner = as_user("sme_garment")
    missing = owner.post(f"/api/mesh/rounds/{round_id}/approve")
    wrong = owner.post(f"/api/mesh/rounds/{round_id}/approve", headers={"X-Step-Up-Code": "000000"})
    accountant = as_user("sme_garment", Role.accountant).post(
        f"/api/mesh/rounds/{round_id}/approve", headers=code(clock))
    assert (missing.status_code, missing.json()["code"]) == (401, "step_up_required")
    assert (wrong.status_code, wrong.json()["code"]) == (401, "invalid_step_up")
    assert accountant.status_code == 403
    ok = owner.post(f"/api/mesh/rounds/{round_id}/approve", headers=code(clock))
    assert (ok.status_code, ok.json()["approvals"], ok.json()["status"]) == \
        (200, {"sme_garment": True}, "proposed")


def test_the_last_approval_settles_anchors_and_verifies(app, as_user, clock):
    round_id = proposed(as_user("sme_garment"))["id"]
    for tenant in RING:
        last = as_user(tenant).post(f"/api/mesh/rounds/{round_id}/approve", headers=code(clock))
    settled = last.json()
    assert settled["status"] == "settled"
    assert settled["anchor"]["chain"] == "offline" and settled["anchor"]["tx_hash"] is None
    garment = as_user("sme_garment")
    check = garment.get(f"/api/mesh/rounds/{round_id}/verify").json()
    assert (check["valid"], check["recomputed_digest"]) == (True, settled["anchor"]["digest"])
    # the debts are discharged: nothing open is left to net
    assert {o["status"] for o in garment.get("/api/mesh/obligations").json()["obligations"]} \
        == {"settled"}
    # the shared demo ring re-opens for the next visitor; the settled round still verifies
    again = proposed(garment)
    assert again["id"] != round_id and again["status"] == "proposed"
    assert garment.get(f"/api/mesh/rounds/{round_id}/verify").json()["valid"] is True
    with app.state.session_factory() as db:
        actions = [e.action for e in AuditLog(db).events("sme_hardware")]
    assert {"mesh.round_approved", "mesh.round_settled"} <= set(actions)


def test_verify_detects_a_record_edited_after_anchoring(app, as_user, clock):
    round_id = proposed(as_user("sme_garment"))["id"]
    for tenant in RING:
        as_user(tenant).post(f"/api/mesh/rounds/{round_id}/approve", headers=code(clock))
    with app.state.session_factory() as db:
        row = db.get(NettingRoundRow, round_id)
        edited = NettingRound.model_validate_json(row.payload)
        first = edited.settlements[0]
        bumped = first.model_copy(update={"amount": first.amount.model_copy(
            update={"amount": first.amount.amount + 1}),
        })
        row.payload = edited.model_copy(update={"settlements": (bumped, *edited.settlements[1:])}
                                        ).model_dump_json()
        db.commit()
    check = as_user("sme_fabric").get(f"/api/mesh/rounds/{round_id}/verify").json()
    assert (check["valid"], check["reason"]) == (False, "record was changed after anchoring")


def test_the_salt_never_leaves_the_server(app, as_user, clock):
    garment = as_user("sme_garment")
    round_id = proposed(garment)["id"]
    for tenant in RING:
        as_user(tenant).post(f"/api/mesh/rounds/{round_id}/approve", headers=code(clock))
    with app.state.session_factory() as db:
        salt = db.get(NettingRoundRow, round_id).salt
    answers = [garment.get("/api/mesh/rounds").text,
               garment.get(f"/api/mesh/rounds/{round_id}/verify").text,
               garment.get("/api/mesh/obligations").text]
    assert all(salt not in text for text in answers)


def test_one_rejection_voids_the_round_and_a_new_one_can_be_proposed(as_user, clock):
    round_id = proposed(as_user("sme_garment"))["id"]
    rejected = as_user("sme_fabric").post(f"/api/mesh/rounds/{round_id}/reject")
    assert rejected.json()["status"] == "rejected"
    late = as_user("sme_hardware").post(f"/api/mesh/rounds/{round_id}/approve",
                                        headers=code(clock))
    assert (late.status_code, late.json()["code"]) == (409, "round_not_open")
    assert proposed(as_user("sme_garment"))["id"] != round_id


def test_a_round_expires_after_48_hours(as_user, clock):
    garment = as_user("sme_garment")
    round_id = proposed(garment)["id"]
    clock.advance(hours=48)  # sign-in sessions last 12 h, so sign in again
    assert as_user("sme_garment").get("/api/mesh/rounds").json()[0]["status"] == "expired"
    late = as_user("sme_fabric").post(f"/api/mesh/rounds/{round_id}/approve", headers=code(clock))
    assert late.json()["code"] == "round_not_open"


def test_rounds_are_invisible_to_non_participants(as_user, clock):
    round_id = proposed(as_user("sme_garment"))["id"]
    grocery = as_user("sme_grocery")
    assert grocery.get("/api/mesh/rounds").json() == []
    for answer in (grocery.get(f"/api/mesh/rounds/{round_id}/verify"),
                   grocery.post(f"/api/mesh/rounds/{round_id}/approve", headers=code(clock))):
        assert (answer.status_code, answer.json()["code"]) == (404, "round_not_found")


def test_verify_before_settlement_says_not_anchored(as_user):
    garment = as_user("sme_garment")
    round_id = proposed(garment)["id"]
    res = garment.get(f"/api/mesh/rounds/{round_id}/verify")
    assert (res.status_code, res.json()["code"]) == (404, "not_anchored")
