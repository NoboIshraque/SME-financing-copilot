from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.contracts import ActionType, DataMode, EligibilityRule, Role, Tier
from app.engines.financing.application import draft_application
from app.engines.financing.ranking import match
from app.security.accounts import Accounts, principal_of
from app.security.approvals import ApprovalProblem, Approvals, issue_cards
from tests.financing.helpers import START, need, product

NOW = datetime(2026, 10, 1, 10, tzinfo=UTC)
RULES = (
    EligibilityRule(id="age", metric="business_age_months", op=">=", threshold=Decimal(24),
                    description_key="rule.business_age"),
    EligibilityRule(id="lic", metric="trade_licence", op="exists",
                    description_key="rule.trade_licence"),
)


def card(facts):
    n = need()
    option = match(n, [product("bank", rules=RULES)], facts, start=START)[0].option
    return draft_application(option, n, facts, now=NOW)


def test_submitting_an_application_needs_owner_approval():
    c = card({"business_age_months": Decimal(36), "trade_licence": Decimal(1)})
    assert c.tier is Tier.EXECUTE and c.requires_approval
    assert c.action_type is ActionType.submit_loan_application


def test_pack_lists_held_facts_and_names_the_missing_ones():
    c = card({"business_age_months": Decimal(36)})
    assert c.payload["facts_provided"] == {"business_age_months": "36"}
    assert c.payload["facts_missing"] == ["trade_licence"]


def test_pack_carries_cost_with_provenance_and_expires():
    c = card({"business_age_months": Decimal(36), "trade_licence": Decimal(1)})
    assert c.cost is not None and c.cost.provenance.parameters["product_id"] == "bank"
    assert (c.expires_at - NOW).total_seconds() == 24 * 3600


def test_owner_approves_and_executes_the_application_an_accountant_requested(client):
    """The WP-06 card goes the whole WP-11 way: request, owner step-up approval, execution."""
    c = card({"business_age_months": Decimal(36), "trade_licence": Decimal(1)})
    with client.app.state.session_factory() as db:
        accounts = Accounts(db, client.app.state.settings)
        accounts.ensure_tenant("sme_grocery", "Grocery", DataMode.synthetic, NOW)
        people = {role: principal_of(accounts.create_user(
            email=f"{role.value}@shop.test", password="a long test password 1", role=role,
            tenant_id="sme_grocery", display_name=role.value, now=NOW))
            for role in (Role.owner, Role.accountant)}
        approvals = Approvals(db)
        issue_cards(db, "sme_grocery", (c,), NOW)  # as POST /api/financing/applications does
        row, _ = approvals.request(people[Role.accountant], c, "idem-apply-1", NOW)
        with pytest.raises(ApprovalProblem) as refused:
            approvals.approve(people[Role.accountant], row.id, step_up_verified=True, now=NOW)
        assert refused.value.status == 403
        with pytest.raises(ApprovalProblem) as no_code:
            approvals.approve(people[Role.owner], row.id, step_up_verified=False, now=NOW)
        assert no_code.value.code == "step_up_required"
        approvals.approve(people[Role.owner], row.id, step_up_verified=True, now=NOW)
        done = approvals.execute(people[Role.owner], row.id, "exec-apply-1", NOW)
        assert done.approval.status.value == "executed"
