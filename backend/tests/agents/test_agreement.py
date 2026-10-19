import json
from decimal import Decimal

import pytest

from app.agents import checker as checker_cache
from app.agents.agreement import Judgement, agree, judgement_for, tally
from app.agents.planning import build_plan
from app.agents.stakes import Stakes
from app.agents.tools import ToolContext
from app.agents.toolset import REGISTRY
from app.api import cash as cash_api
from app.contracts import AgreementReport, Vote
from app.llm import LLMGateway, NoProviderAvailable
from app.privacy import is_safe
from app.settings import LLMMode
from tests.agents.helpers import NOW, Scripted, seeded_store

OPTIONS = ({"id": "opt_a", "summary": "a"}, {"id": "opt_b", "summary": "b"},
           {"id": "opt_c", "summary": "c"})
JUDGEMENT = Judgement("financing_option", "Which option?", OPTIONS, "opt_a")


def votes(*choices):
    return [Vote(model=f"m{i}", choice=c) for i, c in enumerate(choices)]


@pytest.mark.parametrize(("choices", "winner", "rate"), [
    (("opt_a", "opt_a", "opt_a"), "opt_a", Decimal(1)),
    (("opt_a", "opt_a", "opt_b"), "opt_a", Decimal(2) / 3),
    (("opt_a", "opt_b", "opt_b"), "opt_b", Decimal(2) / 3),  # the models outvote the engine
    (("opt_a", "opt_b", "opt_c"), "opt_a", Decimal(1) / 3),  # a three-way tie goes to code
    (("opt_a", "opt_b"), "opt_a", Decimal(1) / 2),
    (("opt_b", "opt_c", "opt_c", "opt_b"), "opt_b", Decimal(1) / 2),  # tie: earliest vote
])
def test_agreement_math(choices, winner, rate):
    assert tally(votes(*choices), "opt_a") == (winner, rate)


@pytest.mark.parametrize(("rate", "stakes", "passed"), [
    (Decimal(1) / 2, Stakes.low, True),
    (Decimal(1) / 2, Stakes.medium, False),
    (Decimal(2) / 3, Stakes.medium, True),
    (Decimal(2) / 3, Stakes.high, False),
    (Decimal(1), Stakes.high, True),
])
def test_thresholds_rise_with_stakes(rate, stakes, passed):
    n = 2 if rate == Decimal(1) / 2 else 3
    agreeing = int(rate * n)
    choices = ["opt_a"] * agreeing + ["opt_b"] * (n - agreeing)
    report = AgreementReport(question="q", votes=tuple(votes(*choices)), winning_choice="opt_a",
                             agreement_rate=rate, threshold=stakes.agreement_threshold,
                             stakes=stakes.value)
    assert report.passed is passed


def caller(gateway):
    def call(request, what, slots):
        try:
            return gateway.complete(request, slots=slots, rules_fallback=False)
        except NoProviderAvailable:
            return None
    return call


def scripted(live_settings, clock, **answers):
    script = {slot: [json.dumps({"choice": choice, "rationale": "because"})]
              for slot, choice in answers.items()}
    return LLMGateway(live_settings, transport=Scripted(script), clock=clock)


def test_two_other_models_agree_with_code(live_settings, clock):
    gw = scripted(live_settings, clock, groq_gpt_oss_120b="opt_a", groq_qwen="opt_a")
    outcome = agree(caller(gw), JUDGEMENT, Stakes.high)
    report = outcome.report
    assert [v.model for v in report.votes] == ["engine:ranking",
                                               "groq_gpt_oss_120b:openai/gpt-oss-120b",
                                               "groq_qwen:qwen/qwen3-32b"]
    assert report.agreement_rate == 1 and outcome.supports_code


def test_one_dissent_passes_medium_but_not_high(live_settings, clock):
    gw = scripted(live_settings, clock, groq_gpt_oss_120b="opt_a", groq_qwen="opt_b")
    assert agree(caller(gw), JUDGEMENT, Stakes.medium).supports_code
    gw = scripted(live_settings, clock, groq_gpt_oss_120b="opt_a", groq_qwen="opt_b")
    high = agree(caller(gw), JUDGEMENT, Stakes.high)
    assert high.report.agreement_rate == Decimal(2) / 3 and not high.supports_code


def test_models_that_outvote_code_do_not_support_it(live_settings, clock):
    gw = scripted(live_settings, clock, groq_gpt_oss_120b="opt_b", groq_qwen="opt_b")
    outcome = agree(caller(gw), JUDGEMENT, Stakes.medium)
    assert outcome.report.winning_choice == "opt_b" and not outcome.supports_code


def test_a_voter_that_is_down_is_replaced_by_its_fallback(live_settings, clock):
    gw = scripted(live_settings, clock, groq_qwen="opt_a", groq_gpt_oss_20b="opt_a")
    report = agree(caller(gw), JUDGEMENT, Stakes.high).report
    assert [v.model.split(":")[0] for v in report.votes] == [
        "engine", "groq_gpt_oss_20b", "groq_qwen"]


def test_an_invalid_choice_is_no_vote(live_settings, clock):
    gw = scripted(live_settings, clock, groq_gpt_oss_120b="opt_z", groq_gpt_oss_20b="opt_a",
                  groq_qwen="opt_a")
    report = agree(caller(gw), JUDGEMENT, Stakes.high).report
    assert "groq_gpt_oss_120b" not in {v.model.split(":")[0] for v in report.votes}
    assert len(report.votes) == 3


@pytest.mark.parametrize("mode", [LLMMode.deterministic, LLMMode.fixtures])
def test_the_rules_never_vote_so_no_agreement_is_claimed(settings, clock, mode):
    gw = LLMGateway(settings.model_copy(update={"llm_mode": mode}), clock=clock)
    outcome = agree(caller(gw), JUDGEMENT, Stakes.high)
    assert outcome.report is None and outcome.note == "agreement.unavailable"
    assert not outcome.supports_code


# --- which judgement --------------------------------------------------------------------

@pytest.fixture(scope="module")
def ledger(universe):
    cash_api.clear_cache()
    checker_cache.clear_cache()
    engine, session, store = seeded_store(universe, shops=("sme_hardware", "sme_grocery"))
    yield store
    session.close()
    engine.dispose()
    cash_api.clear_cache()
    checker_cache.clear_cache()


def plan(intents, planner="gemini_flash"):
    return build_plan({"intents": intents}, "q", REGISTRY, planner=planner)


def test_a_financing_choice_is_judged_on_the_options(ledger):
    ctx = ToolContext(ledger, "sme_hardware", NOW)
    for name in ("cash.gaps", "financing.match"):
        REGISTRY.run(name, ctx)
    judgement = judgement_for(plan(["find_financing"]), ctx.results,
                              ctx.results["cash.gaps"].cards, "q")
    options = ctx.results["financing.match"].payload["options"]
    assert judgement.kind == "financing_option"
    assert judgement.ids == tuple(o.product.id for o in options)
    assert judgement.default == options[0].product.id
    assert is_safe([judgement.question, *[o["summary"] for o in judgement.options]])


def test_without_options_the_fixes_are_judged(ledger):
    ctx = ToolContext(ledger, "sme_hardware", NOW)
    REGISTRY.run("cash.gaps", ctx)
    cards = ctx.results["cash.gaps"].cards
    judgement = judgement_for(plan(["cash_outlook"]), ctx.results, cards, "q")
    assert judgement.kind == "fix" and judgement.default == cards[0].id


def test_a_model_plan_without_choices_is_judged_on_the_intent():
    judgement = judgement_for(plan(["what_if"]), {}, (), "what if sales fall?")
    assert judgement.kind == "intent" and judgement.default == "what_if"
    assert judgement.default_by == "planner:gemini_flash"
    assert "what if sales fall?" in judgement.question


def test_nothing_to_judge_for_a_rules_plan_without_choices():
    assert judgement_for(plan(["what_if"], planner="deterministic"), {}, (), "q") is None
