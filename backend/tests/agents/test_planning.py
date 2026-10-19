from decimal import Decimal

import pytest

from app.agents.budget import Budget
from app.agents.planning import build_plan, what_if_params
from app.agents.toolset import REGISTRY


def plan(proposal, question="q", **kw):
    return build_plan(proposal, question, REGISTRY, planner="test", **kw)


def test_unknown_intents_and_invented_tools_are_dropped():
    p = plan({"intents": ["cash_outlook", "launder_money"],
              "tools": ["cash.forecast", "bank.transfer"]})
    assert p.intents == ("cash_outlook",)
    assert p.tools == ("cash.forecast", "cash.gaps")
    assert p.dropped == ("launder_money", "bank.transfer")


def test_every_intent_gets_its_tools_even_if_the_planner_forgot_them():
    assert plan({"intents": ["find_financing"], "tools": []}).tools == ("cash.gaps",
                                                                         "financing.match")


def test_a_tool_that_serves_no_intent_is_not_run():
    p = plan({"intents": ["business_health"], "tools": ["analysis.ratios", "mesh.propose"]})
    assert p.tools == ("analysis.ratios",)


def test_dependencies_run_first():
    p = plan({"intents": ["settle_debts", "find_financing"], "tools": []})
    assert p.tools == ("cash.gaps", "financing.match", "mesh.propose")
    assert p.subagents() == [("settle_debts", ("mesh.propose",)),
                             ("find_financing", ("cash.gaps", "financing.match"))]


@pytest.mark.parametrize("proposal", [None, {}, {"intents": "cash_outlook"},
                                      {"intents": ["unknown"], "tools": []}])
def test_nothing_runnable_means_not_understood(proposal):
    p = plan(proposal)
    assert not p.understood and p.intents == () and p.tools == ()


def test_language_explicit_then_proposed_then_script():
    assert plan({"intents": ["cash_outlook"], "language": "zh"}, language="bn").language == "bn"
    assert plan({"intents": ["cash_outlook"], "language": "zh"}).language == "zh"
    assert plan({"intents": ["cash_outlook"], "language": "fr"}, "নগদ?").language == "bn"


def test_engine_parameters_never_come_from_the_model():
    p = plan({"intents": ["what_if"], "tools": ["analysis.scenarios"],
              "params": {"analysis.scenarios": {"sales_change_pct": -90}}},
             "What if sales drop by 10%?")
    assert p.params == {"analysis.scenarios": {"sales_change_pct": Decimal(-10)}}


@pytest.mark.parametrize(("question", "expected"), [
    ("What if sales drop by 30%?", {"sales_change_pct": Decimal(-30)}),
    ("if my sales fall 15% next month", {"sales_change_pct": Decimal(-15)}),
    ("যদি বিক্রি ২০% কমে যায়?", {"sales_change_pct": Decimal(-20)}),
    ("Jodi bikri 25% kome jay?", {"sales_change_pct": Decimal(-25)}),
    ("如果销售下降10%会怎样？", {"sales_change_pct": Decimal(-10)}),
    ("what if sales go up 10%", {"sales_change_pct": Decimal(10)}),
    ("what if costs rise 12%?", {"cost_change_pct": Decimal(12)}),
    ("what if customers pay 15 days late?", {"collection_delay_days": 15}),
    ("what if sales drop 10% and costs rise 5%?",
     {"sales_change_pct": Decimal(-10), "cost_change_pct": Decimal(5)}),
])
def test_what_if_shocks_are_read_from_the_owners_words(question, expected):
    assert what_if_params(question) == (expected, ())


def test_a_what_if_without_a_number_uses_the_standard_stress_and_says_so():
    assert what_if_params("what if things get worse?") == (
        {"sales_change_pct": Decimal(-20)}, ("scenario.default_shock",))


def test_tool_budget_stops_and_names_what_it_refused():
    budget = Budget(max_tool_calls=2)
    assert [budget.take_tool(n) for n in ("a", "b", "c", "d")] == [True, True, False, False]
    assert budget.refused == ["c", "d"] and budget.tools_exhausted


def test_model_budget_counts_calls_and_tokens():
    by_calls = Budget(max_llm_calls=1)
    assert by_calls.take_llm("plan") and not by_calls.take_llm("narrate")
    by_tokens = Budget(max_tokens=100)
    assert by_tokens.take_llm("plan")
    by_tokens.spend_tokens(100)
    assert not by_tokens.take_llm("narrate")
    assert by_tokens.refused == ["llm:narrate"] and not by_tokens.tools_exhausted
