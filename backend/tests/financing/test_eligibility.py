from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.contracts import EligibilityRule, EligibilityStatus, Money
from app.engines.financing.eligibility import check_rule, evaluate, missing_facts
from tests.financing.helpers import product

PASS, FAIL, MISSING = (EligibilityStatus.pass_, EligibilityStatus.fail,
                       EligibilityStatus.not_on_record)


def rule(op, threshold=None, metric="business_age_months"):
    return EligibilityRule(id=f"r-{op}", metric=metric, op=op,
                           threshold=None if threshold is None else Decimal(threshold),
                           description_key="rule.x")


@pytest.mark.parametrize(("op", "threshold", "value", "expected"), [
    (">=", 24, 24, PASS),
    (">=", 24, 23, FAIL),
    ("<=", 5, 5, PASS),
    ("<=", 5, 6, FAIL),
    ("==", 1, 1, PASS),
    ("==", 1, 0, FAIL),
    ("exists", None, 1, PASS),
    ("exists", None, 0, FAIL),
])
def test_each_operator(op, threshold, value, expected):
    result = check_rule(rule(op, threshold), {"business_age_months": Decimal(value)})
    assert result.status is expected
    assert result.observed_value == Decimal(value)


@pytest.mark.parametrize("op", [">=", "<=", "==", "exists"])
def test_a_missing_fact_is_not_on_record_never_a_pass(op):
    result = check_rule(rule(op, None if op == "exists" else 1), {})
    assert result.status is MISSING
    assert result.message_key.endswith("not_on_record")


@pytest.mark.property
@given(st.dictionaries(st.sampled_from(["business_age_months", "monthly_sales", "trade_licence"]),
                       st.none() | st.integers(0, 500).map(Decimal)))
def test_not_on_record_never_passes_overall(facts):
    rules = (rule(">=", 12), rule(">=", 100000, "monthly_sales"),
             rule("exists", None, "trade_licence"))
    result = evaluate(product(rules=rules), facts, Money.of(50000), 180)
    if any(facts.get(r.metric) is None for r in rules):
        assert result.status is not PASS


@pytest.mark.parametrize(("amount", "tenor", "rule_id"), [
    (40000, 180, "limit.amount_min"),
    (6000000, 180, "limit.amount_max"),
    (100000, 60, "limit.tenor_min"),
    (100000, 400, "limit.tenor_max"),
])
def test_published_limits_become_failing_reasons(amount, tenor, rule_id):
    p = product(min_amount=Money.of(50000), max_amount=Money.of(5000000), min_tenor_days=90,
                max_tenor_days=365)
    result = evaluate(p, {}, Money.of(amount), tenor)
    assert result.status is FAIL
    assert [r.rule_id for r in result.reasons] == [rule_id]


def test_fail_outranks_missing_in_the_overall_status():
    p = product(rules=(rule(">=", 24), rule("exists", None, "trade_licence")))
    result = evaluate(p, {"business_age_months": Decimal(3)}, Money.of(1000), 30)
    assert result.status is FAIL


def test_missing_facts_lists_what_the_owner_can_add():
    p = product(rules=(rule(">=", 24), rule("exists", None, "trade_licence")))
    result = evaluate(p, {"business_age_months": Decimal(30)}, Money.of(1000), 30)
    assert result.status is MISSING
    assert missing_facts(result, p) == ["trade_licence"]
