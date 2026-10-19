import dataclasses
import json

import pytest

from app.agents import checker as checker_cache
from app.agents import selfloop
from app.agents.claims import compose
from app.agents.critic import RISKS, critique, risk, risks, strongest
from app.agents.stakes import Stakes, assess
from app.agents.tools import ToolContext
from app.agents.toolset import REGISTRY
from app.api import cash as cash_api
from app.contracts import ActionCard, ActionType, DataMode, EligibilityStatus, Tier
from app.llm import LLMGateway
from tests.agents.helpers import NOW, Scripted, seeded_store

OBJECTION = json.dumps({"objection": "The advance depends on a customer who already pays "
                                     "late.", "severity": "high"})


@pytest.fixture(scope="module")
def ledger(universe):
    cash_api.clear_cache()
    checker_cache.clear_cache()
    selfloop.clear_cache()
    engine, session, store = seeded_store(universe, shops=("sme_hardware", "sme_grocery"))
    yield store
    session.close()
    engine.dispose()
    cash_api.clear_cache()
    checker_cache.clear_cache()
    selfloop.clear_cache()


def tool_run(ledger, tenant, tools):
    ctx = ToolContext(ledger, tenant, NOW)
    for name in tools:
        REGISTRY.run(name, ctx)
    return ctx


@pytest.fixture(scope="module")
def hardware(ledger):
    ctx = tool_run(ledger, "sme_hardware", ("cash.forecast", "cash.gaps", "financing.match"))
    cards = (*ctx.results["cash.gaps"].cards, *ctx.results["financing.match"].cards)
    statements = compose(ctx.results, ("cash.forecast", "cash.gaps", "financing.match"), "en")
    return ctx, cards, statements


def gateway(live_settings, clock, script):
    return LLMGateway(live_settings, transport=Scripted(script), clock=clock)


def caller(gw):
    return lambda request, what: gw.complete(request)


# --- what code finds ------------------------------------------------------------------------

def test_code_finds_the_risks_of_a_loan_recommendation(hardware):
    ctx, cards, _ = hardware
    found = risks(ctx.results, cards, "en", history_days=ctx.history_days,
                  data_mode=DataMode.synthetic)
    top = ctx.results["financing.match"].payload["options"][0]
    gap = ctx.results["cash.gaps"].payload["gaps"][0]
    assert top.speed_days > gap.lead_time_days  # approval is slower than the gap is near
    assert [r.code for r in found] == ["loan_too_slow", "still_breach", "netting_consent",
                                       "no_track_record", "advance_strains", "synthetic"]
    assert found[0].text == f"{top.product.name} may not be approved before the cash gap starts."


def test_unknown_eligibility_is_the_first_objection(hardware):
    ctx, cards, _ = hardware
    result = ctx.results["financing.match"]
    options = result.payload["options"]
    unsure = options[1].model_copy(update={"speed_days": 0})  # women refinance: not on record
    results = {**ctx.results, "financing.match": dataclasses.replace(
        result, payload={**result.payload, "options": (unsure, *options[2:])})}
    found = risks(results, (), "en", history_days=ctx.history_days,
                  data_mode=DataMode.real_anonymised)
    assert unsure.eligibility.status is EligibilityStatus.not_on_record
    assert found[0].code == "eligibility_unknown"
    assert unsure.product.name in found[0].text


def test_an_information_only_answer_on_real_data_still_gets_an_objection(ledger):
    ctx = tool_run(ledger, "sme_grocery", ("cash.forecast",))
    found = risks(ctx.results, (), "en", history_days=ctx.history_days,
                  data_mode=DataMode.real_anonymised)
    assert [r.code for r in found] == ["general"]


@pytest.mark.parametrize("language", ["en", "bn", "zh"])
def test_every_risk_reads_in_every_language_without_digits(language):
    for code in RISKS:
        text = risk(code, language, name="X").text
        assert text and not any(ch.isdigit() for ch in text)


# --- who argues ---------------------------------------------------------------------------

def test_a_model_of_another_family_argues_the_case_against(hardware, live_settings, clock):
    _, _, statements = hardware
    gw = gateway(live_settings, clock, {"groq_qwen": [OBJECTION]})
    found = [risk("synthetic", "en")]
    objection = critique(caller(gw), "Ask for an advance.", statements, found, language="en",
                         brain_families=("google",))
    assert (objection.source, objection.family, objection.severity) == ("groq_qwen", "alibaba",
                                                                        "high")
    assert objection.text.startswith("The advance depends")


def test_the_critic_is_never_the_brains_family(hardware, live_settings, clock):
    _, _, statements = hardware
    gw = gateway(live_settings, clock, {"groq_qwen": [OBJECTION], "groq_gpt_oss_120b":
                                        [OBJECTION], "gemma": [OBJECTION]})
    objection = critique(caller(gw), "Ask for an advance.", statements,
                         [risk("synthetic", "en")], language="en",
                         brain_families=("alibaba", "openai"))
    assert objection.family == "google" and objection.source == "gemma"


@pytest.mark.parametrize("reply", [
    json.dumps({"objection": "Borrow Tk 2,00,000 instead.", "severity": "high"}),  # new number
    json.dumps({"objection": None, "severity": None}),
    json.dumps({"objection": "Fine.", "severity": "catastrophic"}),
    json.dumps({"objection": "x" * 500, "severity": "low"}),
], ids=["invented-number", "no-objection", "bad-severity", "too-long"])
def test_an_unusable_objection_falls_back_to_the_worst_risk(hardware, live_settings, clock,
                                                             reply):
    _, _, statements = hardware
    gw = gateway(live_settings, clock, {"groq_qwen": [reply], "groq_gpt_oss_120b": [reply],
                                        "groq_gpt_oss_20b": [reply]})
    found = [risk("loan_too_slow", "en", name="Loan A"), risk("synthetic", "en")]
    objection = critique(caller(gw), "Take Loan A.", statements, found, language="en",
                         brain_families=("google",))
    assert objection == strongest(found)
    assert objection.text == "Loan A may not be approved before the cash gap starts."


def test_no_model_available_means_the_rules_object(hardware, settings):
    _, _, statements = hardware
    found = [risk("netting_consent", "bn")]
    objection = critique(caller(LLMGateway(settings)), "x", statements, found, language="bn",
                         brain_families=("google",))
    assert objection.source == "rules" and objection.text == found[0].text


# --- stakes -------------------------------------------------------------------------------

def card(action):
    return ActionCard(id="c", title_key="t", action_type=action, tier=Tier.DRAFT)


@pytest.mark.parametrize(("intents", "actions", "expected"), [
    (["business_health"], [], Stakes.low),
    (["cash_outlook"], [], Stakes.low),
    (["settle_debts"], [ActionType.propose_netting_round], Stakes.medium),
    (["what_if"], [], Stakes.medium),
    (["cash_outlook"], [ActionType.send_reminder], Stakes.medium),
    (["find_financing"], [], Stakes.high),
    (["cash_outlook"], [ActionType.request_advance], Stakes.high),
])
def test_stakes(intents, actions, expected):
    assert assess(intents, [card(a) for a in actions]) is expected


def test_checks_rise_with_stakes():
    low, medium, high = Stakes.low, Stakes.medium, Stakes.high
    assert (low.needs_critic, medium.needs_critic, high.needs_critic) == (False, True, True)
    assert low.agreement_threshold < medium.agreement_threshold < high.agreement_threshold
    assert low.stress_runs < medium.stress_runs < high.stress_runs
