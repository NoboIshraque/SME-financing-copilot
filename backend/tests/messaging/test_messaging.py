from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.contracts import Language, MessagePurpose, Principal, Role
from app.facts import FactStore
from app.facts.seed import load_sme_into
from app.messaging.templates import TEMPLATES, TemplateError, amount_text, render
from app.security.audit import AuditLog
from app.security.deps import StepUp, current_principal, step_up
from app.security.errors import SecurityProblem

OWNER = Principal(user_id="u-owner", tenant_id="sme_grocery", role=Role.owner)
VARS = {"customer": "Customer 3", "amount": "5,804.00", "due_date": "2026-09-11",
        "invoices": "3", "shop": "Grocery", "installments": "3", "days": "14"}


@pytest.mark.parametrize("purpose, language, expected", [
    (MessagePurpose.pre_due_reminder, Language.en,
     "Dear Customer 3, a friendly reminder: Tk 5,804.00 for 3 invoice(s) is due on 2026-09-11."),
    (MessagePurpose.overdue_reminder, Language.bn, "প্রিয় Customer 3, 3টি বিলের মোট 5,804.00 টাকা"),
])
def test_templates_render_typed_values(purpose, language, expected):
    assert render(purpose, language, VARS).startswith(expected)


def test_every_purpose_has_english_and_bangla_and_renders_completely():
    purposes = {p for p, _ in TEMPLATES}
    assert all((p, lang) in TEMPLATES for p in purposes for lang in (Language.en, Language.bn))
    assert all("{" not in render(p, lang, VARS) for p, lang in TEMPLATES)


def test_a_template_with_a_missing_variable_is_refused():
    with pytest.raises(TemplateError, match="amount"):
        render(MessagePurpose.overdue_reminder, Language.en, {**VARS, "amount": ""})


def test_amounts_keep_two_decimals():
    assert amount_text(Decimal("5804")) == "5,804.00"


@pytest.fixture
def api(client: TestClient, universe) -> TestClient:
    with client.app.state.session_factory() as session:
        load_sme_into(FactStore(session), universe.smes["sme_grocery"], universe.start,
                      universe.as_of)
        session.commit()
    client.app.state.security_clock = lambda: datetime(2026, 10, 19, 6, tzinfo=UTC)
    client.app.dependency_overrides[current_principal] = lambda: OWNER
    client.app.dependency_overrides[step_up] = lambda: StepUp(auth=None, problem=None)  # type: ignore[arg-type]
    return client


def test_approving_a_message_needs_a_fresh_step_up_code(api: TestClient):
    # A message leaves DecisionGuard, so it is EXECUTE (CLAUDE.md rule 4): owner plus code.
    draft = api.get("/api/messages/drafts").json()[0]
    missing = SecurityProblem(401, "step_up_required", "error.step_up_required")
    api.app.dependency_overrides[step_up] = lambda: StepUp(auth=None, problem=missing)  # type: ignore[arg-type]
    res = api.post(f"/api/messages/{draft['id']}/approve")
    assert (res.status_code, res.json()["code"]) == (401, "step_up_required")
    assert api.get("/api/messages/drafts").json()[0]["status"] == "draft"


def test_one_copy_draft_per_reminder_and_refreshing_adds_no_duplicates(api: TestClient):
    plan = api.get("/api/receivables/plan").json()["reminders"]
    first = api.get("/api/messages/drafts").json()
    again = api.get("/api/messages/drafts").json()
    assert len(first) == len(plan) == len(again)
    assert {d["channel"] for d in first} == {"copy"}
    labels = {c["payload"]["counterparty_label"] for c in plan}
    assert all(any(label in d["body"] for label in labels) for d in first)


def test_bangla_drafts_are_separate(api: TestClient):
    en = api.get("/api/messages/drafts").json()
    bn = api.get("/api/messages/drafts", params={"language": "bn"}).json()
    assert len(bn) == 2 * len(en)  # one draft per reminder per language
    assert {d["language"] for d in bn} == {"en", "bn"}


def test_owner_approves_then_records_the_send_once_and_both_are_audited(api: TestClient):
    draft = api.get("/api/messages/drafts").json()[0]
    early = api.post(f"/api/messages/{draft['id']}/send")
    assert (early.status_code, early.json()["code"]) == (409, "draft_not_open")
    assert api.post(f"/api/messages/{draft['id']}/approve").json()["status"] == "approved"
    sent = api.post(f"/api/messages/{draft['id']}/send").json()
    again = api.post(f"/api/messages/{draft['id']}/send").json()
    assert (sent["status"], again["status"], again["body"]) == ("sent", "sent", draft["body"])
    with api.app.state.session_factory() as db:
        actions = [e.action for e in AuditLog(db).events("sme_grocery")]
    assert actions.count("message.approved") == 1 and actions.count("message.sent") == 1


def test_staff_may_read_drafts_but_not_approve(api: TestClient):
    draft_id = api.get("/api/messages/drafts").json()[0]["id"]
    api.app.dependency_overrides[current_principal] = lambda: Principal(
        user_id="u-staff", tenant_id="sme_grocery", role=Role.staff)
    assert api.get("/api/messages/drafts").status_code == 200
    assert api.post(f"/api/messages/{draft_id}/approve").status_code == 403


def test_another_tenant_cannot_touch_a_draft(api: TestClient):
    draft_id = api.get("/api/messages/drafts").json()[0]["id"]
    api.app.dependency_overrides[current_principal] = lambda: Principal(
        user_id="u-x", tenant_id="sme_fabric", role=Role.owner)
    res = api.post(f"/api/messages/{draft_id}/approve")
    assert (res.status_code, res.json()["code"]) == (404, "draft_not_found")
