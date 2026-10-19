from datetime import timedelta

import pytest

from app.contracts import ActionCard, ActionType, Role, Tier
from app.security import approvals as approvals_module
from app.security import policy, totp
from app.security.models import ApprovalRow, UserRow
from tests.security.conftest import sign_in

SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
CARD = ActionCard(id="act-pay-1", title_key="action.move_money",
                  action_type=ActionType.move_money, tier=Tier.EXECUTE,
                  payload={"bill_id": "t1:BILL-7", "amount": "15000.00"})


def card_json(card: ActionCard = CARD) -> dict:
    return {"card": card.model_dump(mode="json")}


def key(value: str = "idem-0001") -> dict[str, str]:
    return {"X-Idempotency-Key": value}


def relogin(api, clock):
    """Sign the owner in with password + TOTP (sessions end after 12 h, so long jumps need it)."""
    sign_in(api)
    api.post("/api/auth/login/totp", json={"code": totp.code_at(SECRET, clock())})
    clock.advance(seconds=30)


@pytest.fixture
def owner(api, make_user, clock):
    make_user(totp_secret=SECRET)
    relogin(api, clock)
    return api


def step_up(clock) -> dict[str, str]:
    code = totp.code_at(SECRET, clock())
    clock.advance(seconds=30)
    return {"X-Step-Up-Code": code}


def requested(api) -> dict:
    response = api.post("/api/approvals", headers=key(), json=card_json())
    assert response.status_code == 201
    return response.json()


def approved(api, clock) -> str:
    approval_id = requested(api)["approval"]["id"]
    response = api.post(f"/api/approvals/{approval_id}/approve", headers=step_up(clock))
    assert response.status_code == 200
    return approval_id


def test_a_request_creates_a_pending_approval_expiring_in_24_hours(owner, clock):
    view = requested(owner)
    approval = view["approval"]
    assert approval["status"] == "pending" and approval["tier"] == "EXECUTE"
    assert approval["action_card_id"] == "act-pay-1" and view["card"]["payload"]["amount"] == \
        "15000.00"
    assert owner.get("/api/approvals", params={"status": "pending"}).json()[0]["approval"][
        "id"] == approval["id"]
    clock.advance(hours=24)
    relogin(owner, clock)
    assert owner.get(f"/api/approvals/{approval['id']}").json()["approval"]["status"] == \
        "expired"


def test_approval_needs_a_fresh_totp_and_records_who_approved(owner, clock):
    approval_id = requested(owner)["approval"]["id"]
    assert owner.post(f"/api/approvals/{approval_id}/approve").json()["code"] == \
        "step_up_required"
    response = owner.post(f"/api/approvals/{approval_id}/approve", headers=step_up(clock))
    approval = response.json()["approval"]
    assert approval["status"] == "approved" and approval["step_up_verified"] is True
    assert approval["decided_by"].startswith("u-")


def test_execution_runs_once_per_idempotency_key(owner, clock, monkeypatch):
    runs = []
    monkeypatch.setitem(approvals_module._EXECUTORS, ActionType.move_money,
                        lambda card, approval: runs.append(card.id) or {"status": "simulated"})
    approval_id = approved(owner, clock)
    first = owner.post(f"/api/approvals/{approval_id}/execute", headers=key("exec-0001"))
    again = owner.post(f"/api/approvals/{approval_id}/execute", headers=key("exec-0001"))
    other = owner.post(f"/api/approvals/{approval_id}/execute", headers=key("exec-0002"))
    assert first.json()["result"] == {"status": "simulated"} and first.json()["replayed"] is False
    assert again.json()["replayed"] is True and again.json()["result"] == first.json()["result"]
    assert other.status_code == 409 and other.json()["code"] == "approval_executed"
    assert runs == ["act-pay-1"]
    assert first.json()["approval"]["status"] == "executed"


def test_without_an_executor_an_approved_action_is_only_recorded(owner, clock):
    approval_id = approved(owner, clock)
    result = owner.post(f"/api/approvals/{approval_id}/execute",
                        headers=key("exec-0001")).json()["result"]
    assert result["status"] == "recorded"


def test_a_pending_approval_cannot_be_executed(owner):
    approval_id = requested(owner)["approval"]["id"]
    response = owner.post(f"/api/approvals/{approval_id}/execute", headers=key("exec-0001"))
    assert response.status_code == 409 and response.json()["code"] == "approval_pending"


def test_an_approval_expires_24_hours_after_the_request_even_once_approved(owner, clock):
    approval_id = approved(owner, clock)
    clock.advance(hours=24)
    relogin(owner, clock)
    response = owner.post(f"/api/approvals/{approval_id}/execute", headers=key("exec-0001"))
    assert response.json()["code"] == "approval_expired"


def test_an_expired_request_cannot_be_approved(owner, clock):
    approval_id = requested(owner)["approval"]["id"]
    clock.advance(hours=25)
    relogin(owner, clock)
    response = owner.post(f"/api/approvals/{approval_id}/approve", headers=step_up(clock))
    assert response.status_code == 409 and response.json()["code"] == "approval_expired"


def test_repeating_a_request_with_the_same_key_returns_the_same_approval(owner):
    first = requested(owner)
    again = owner.post("/api/approvals", headers=key(), json=card_json())
    assert again.status_code == 200 and again.json()["replayed"] is True
    assert again.json()["approval"]["id"] == first["approval"]["id"]
    assert len(owner.get("/api/approvals").json()) == 1


def test_reusing_a_key_for_a_different_card_is_refused(owner):
    requested(owner)
    changed = CARD.model_copy(update={"payload": {"bill_id": "t1:BILL-7", "amount": "99000.00"}})
    response = owner.post("/api/approvals", headers=key(), json=card_json(changed))
    assert response.status_code == 409 and response.json()["code"] == "idempotency_key_reused"


@pytest.mark.parametrize("bad_key", [None, "short", "x" * 129])
def test_requests_need_a_usable_idempotency_key(owner, bad_key):
    headers = {} if bad_key is None else key(bad_key)
    response = owner.post("/api/approvals", headers=headers, json=card_json())
    assert response.status_code == 400 and response.json()["code"] == "idempotency_key_required"


@pytest.mark.parametrize("action", ["change_bank_details", "add_payee", "disable_audit",
                                    "export_raw_pii"])
def test_deny_list_actions_cannot_even_be_requested(owner, action):
    card = ActionCard(id="act-x", title_key="t", action_type=ActionType(action),
                      tier=Tier.DRAFT)
    response = owner.post("/api/approvals", headers=key(), json=card_json(card))
    assert response.status_code == 403 and response.json()["code"] == "action_denied"


def test_actions_below_execute_need_no_approval(owner):
    card = ActionCard(id="act-d", title_key="t", action_type=ActionType.record_dispute,
                      tier=Tier.DRAFT)
    response = owner.post("/api/approvals", headers=key(), json=card_json(card))
    assert response.status_code == 422 and response.json()["code"] == "approval_not_needed"


def test_a_card_claiming_a_low_tier_is_still_treated_as_execute(owner):
    sneaky = CARD.model_copy(update={"tier": Tier.READ})
    response = owner.post("/api/approvals", headers=key(), json=card_json(sneaky))
    assert response.json()["approval"]["tier"] == "EXECUTE"


def test_an_accountant_drafts_and_only_the_owner_approves(api, make_user, clock):
    make_user(totp_secret=SECRET)
    make_user("acc@shop.test", role=Role.accountant)
    sign_in(api, "acc@shop.test")
    approval_id = requested(api)["approval"]["id"]
    assert api.post(f"/api/approvals/{approval_id}/approve",
                    headers={"X-Step-Up-Code": "123456"}).status_code == 403
    with type(api)(api.app) as owner_client:
        sign_in(owner_client)
        owner_client.post("/api/auth/login/totp", json={"code": totp.code_at(SECRET, clock())})
        clock.advance(seconds=30)
        decided = owner_client.post(f"/api/approvals/{approval_id}/approve",
                                    headers=step_up(clock))
        assert decided.json()["approval"]["status"] == "approved"
    executed = api.post(f"/api/approvals/{approval_id}/execute", headers=key("exec-0001"))
    assert executed.json()["approval"]["status"] == "executed"  # the requester may run it


@pytest.mark.parametrize(("role", "action"), [
    (Role.staff, ActionType.move_money),
    (Role.staff, ActionType.retime_payable),
    (Role.compliance, ActionType.send_reminder),
])
def test_roles_that_cannot_draft_an_action_cannot_request_it(api, make_user, role, action):
    make_user("member@shop.test", role=role)
    sign_in(api, "member@shop.test")
    card = ActionCard(id="act-r", title_key="t", action_type=action, tier=Tier.EXECUTE)
    response = api.post("/api/approvals", headers=key(), json=card_json(card))
    assert response.status_code == 403


def test_policy_is_checked_again_at_execution(owner, clock, monkeypatch):
    approval_id = approved(owner, clock)
    tightened = dict(policy.POLICY)
    tightened[ActionType.move_money] = (Tier.DRAFT,) + tightened[ActionType.move_money][1:]
    monkeypatch.setattr(policy, "POLICY", tightened)
    response = owner.post(f"/api/approvals/{approval_id}/execute", headers=key("exec-0001"))
    assert response.status_code == 403 and response.json()["code"] == "policy_changed"


def test_an_approval_dies_with_the_approver_account(api, app, make_user, clock):
    make_user(totp_secret=SECRET)
    make_user("acc@shop.test", role=Role.accountant)
    sign_in(api, "acc@shop.test")
    approval_id = requested(api)["approval"]["id"]
    with type(api)(api.app) as owner_client:
        relogin(owner_client, clock)
        owner_client.post(f"/api/approvals/{approval_id}/approve", headers=step_up(clock))
    with app.state.session_factory() as session:
        session.query(UserRow).filter(UserRow.email == "owner@shop.test").one().active = False
        session.commit()
    response = api.post(f"/api/approvals/{approval_id}/execute", headers=key("exec-0001"))
    assert response.status_code == 409 and response.json()["code"] == "approver_inactive"


def test_a_tampered_stored_card_is_not_executed(owner, app, clock):
    approval_id = approved(owner, clock)
    with app.state.session_factory() as session:
        row = session.get(ApprovalRow, approval_id)
        row.card_json = row.card_json.replace("15000.00", "95000.00")
        session.commit()
    response = owner.post(f"/api/approvals/{approval_id}/execute", headers=key("exec-0001"))
    assert response.status_code == 409 and response.json()["code"] == "card_changed"


def test_rejected_approvals_cannot_be_approved_or_executed(owner, clock):
    approval_id = requested(owner)["approval"]["id"]
    assert owner.post(f"/api/approvals/{approval_id}/reject").json()["approval"]["status"] == \
        "rejected"
    assert owner.post(f"/api/approvals/{approval_id}/approve",
                      headers=step_up(clock)).json()["code"] == "approval_rejected"
    assert owner.post(f"/api/approvals/{approval_id}/execute",
                      headers=key("exec-0001")).json()["code"] == "approval_rejected"


def test_approvals_are_invisible_to_other_tenants(owner, api, make_user):
    approval_id = requested(owner)["approval"]["id"]
    make_user("owner@other.test", tenant="t2")
    with type(api)(api.app) as other:
        sign_in(other, "owner@other.test")
        assert other.get(f"/api/approvals/{approval_id}").status_code == 404
        assert other.get("/api/approvals").json() == []
        assert other.post(f"/api/approvals/{approval_id}/reject").status_code == 404


def test_lender_viewers_cannot_see_approvals(api, make_user, clock):
    make_user("bank@lender.test", role=Role.lender_viewer, scopes=("passport:read",),
              expires_at=clock() + timedelta(days=3))
    sign_in(api, "bank@lender.test")
    assert api.get("/api/approvals").status_code == 403


def test_the_policy_table_is_served_to_signed_in_users(owner, api):
    tiers = owner.get("/api/policy/tiers").json()
    assert tiers["add_payee"]["owner"] == "DENY" and tiers["send_reminder"]["staff"] == "DRAFT"


def test_registering_an_executor_for_a_denied_action_is_refused():
    with pytest.raises(ValueError):
        approvals_module.register_executor(ActionType.add_payee, lambda card, a: {})
