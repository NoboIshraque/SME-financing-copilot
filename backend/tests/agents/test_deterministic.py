import json

import pytest

from app.llm import deterministic
from app.llm.messages import LLMRequest, Task
from app.llm.prompts import critique_request, narrate_request, vote_request
from app.llm.providers import Role


@pytest.mark.parametrize(("question", "intents", "language"), [
    ("Will I run out of cash next month?", ["cash_outlook"], "en"),
    ("আমার টাকা দরকার, ঋণের সুদ কত?", ["find_financing"], "bn"),
    ("Customer 1 er baki koto? aday korte chai", ["collect_receivables"], "en"),
    ("我下个月现金够吗？要不要贷款", ["cash_outlook", "find_financing"], "zh"),
    ("What if sales drop by a fifth?", ["what_if"], "en"),
    ("Can we net off the circular debt with Firm A?", ["settle_debts"], "en"),
    ("Negotiate better terms with Supplier 2", ["negotiate"], "en"),
    ("Draft a WhatsApp message to Customer 3", ["draft_message"], "en"),
    ("এই মাসে লাভ কেমন হলো?", ["business_health"], "bn"),
    ("Is the wholesale price of rice cheaper elsewhere?", ["market_prices"], "en"),
    ("Tell me a joke", ["unknown"], "en"),
], ids=["en-cash", "bn-loan-not-market", "banglish-baki", "zh-two-intents", "what-if",
        "netting", "negotiate", "draft", "bn-profit", "prices", "unknown"])
def test_plan_intents_across_languages(question, intents, language):
    plan = deterministic.plan(question)
    assert plan["intents"] == intents
    assert plan["language"] == language


def test_plan_tools_follow_intents_without_duplicates():
    plan = deterministic.plan("Will I run out of cash, and should I take a loan?")
    assert plan["intents"] == ["cash_outlook", "find_financing"]
    assert plan["tools"] == ["cash.forecast", "cash.gaps", "financing.match"]


def test_unknown_question_plans_no_tools():
    assert deterministic.plan("good morning")["tools"] == []


def test_english_keywords_match_whole_words_only():
    # "gap" inside "singapore", "dam" inside "damaged", "loan" inside "loaned" are not intents
    assert deterministic.classify("a damaged box from singapore") == []


def test_at_most_three_intents():
    question = "cash loan profit what if netting price draft"
    assert len(deterministic.classify(question)) == deterministic.MAX_INTENTS


@pytest.mark.parametrize(("default", "expected"), [
    ("opt_b", "opt_b"),  # the engine's top-ranked option
    ("opt_x", "opt_a"),  # a default that is not an option is ignored
    (None, "opt_a"),
])
def test_rule_vote_echoes_the_engine_ranking(default, expected):
    request = vote_request("Which?", [{"id": "opt_a", "summary": "a"},
                                      {"id": "opt_b", "summary": "b"}], default=default)
    assert json.loads(deterministic.answer(request))["choice"] == expected


def test_rule_critique_picks_the_most_severe_risk():
    request = critique_request("Take the loan.", ["gap of Tk 50000"], risks=[
        {"text": "approval takes longer than the gap", "severity": "medium"},
        {"text": "repayment exceeds next month's inflow", "severity": "high"},
        {"text": "fee is above the market median", "severity": "low"}])
    assert json.loads(deterministic.answer(request)) == {
        "objection": "repayment exceeds next month's inflow", "severity": "high"}


def test_rule_critique_without_risks_has_no_objection():
    request = critique_request("Send a reminder.", ["invoice 20 days overdue"])
    assert json.loads(deterministic.answer(request))["objection"] is None


def test_rule_narration_repeats_only_verified_claims():
    request = narrate_request(["Cash falls below zero on day t+12.",
                               "Customer 1 owes Tk 65000."])
    text = json.loads(deterministic.answer(request))["text"]
    assert text == "Cash falls below zero on day t+12. Customer 1 owes Tk 65000."


@pytest.mark.parametrize("request_", [
    narrate_request([]),
    vote_request("Which?", []),
    LLMRequest(Role.brain, Task.chat, ()),
], ids=["narrate-nothing", "vote-no-options", "chat"])
def test_rules_refuse_what_they_cannot_answer(request_):
    with pytest.raises(deterministic.Unsupported):
        deterministic.answer(request_)


def test_gross_margin_in_chinese_is_an_analysis_question_not_financing():
    from app.llm.deterministic import classify
    assert classify("我们的毛利率是多少？") == ["business_health"]
    assert "find_financing" in classify("贷款利率是多少？")  # interest rate still means financing
