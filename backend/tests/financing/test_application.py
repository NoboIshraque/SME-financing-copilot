from datetime import UTC, datetime
from decimal import Decimal

from app.contracts import ActionType, EligibilityRule, Tier
from app.engines.financing.application import draft_application
from app.engines.financing.ranking import match
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
    assert c.action_type is ActionType.draft_loan_application


def test_pack_lists_held_facts_and_names_the_missing_ones():
    c = card({"business_age_months": Decimal(36)})
    assert c.payload["facts_provided"] == {"business_age_months": "36"}
    assert c.payload["facts_missing"] == ["trade_licence"]


def test_pack_carries_cost_with_provenance_and_expires():
    c = card({"business_age_months": Decimal(36), "trade_licence": Decimal(1)})
    assert c.cost is not None and c.cost.provenance.parameters["product_id"] == "bank"
    assert (c.expires_at - NOW).total_seconds() == 24 * 3600
