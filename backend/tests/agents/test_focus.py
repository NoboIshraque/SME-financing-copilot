"""The copilot answers the question asked, not every engine's report (Nobo, 20 Oct).

"What's my loan looking like?" is about the loan the shop repays; "Can I take a loan of
5000000?" is answered for that amount, yes or no first; a loan answer names the best option
only and attaches only loan cards, not the cash-gap fixes."""

from decimal import Decimal

import pytest

from app.agents import checker as checker_cache
from app.agents import selfloop
from app.agents.planning import build_plan, loan_amount
from app.agents.tools import ToolContext
from app.agents.toolset import REGISTRY
from app.api import cash as cash_api
from app.llm.deterministic import classify
from tests.agents.helpers import NOW, seeded_store


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


@pytest.fixture
def orch(settings):
    from app.agents.orchestrator import Orchestrator
    from app.llm.gateway import LLMGateway
    return Orchestrator(LLMGateway(settings))


def ask(orch, ledger, question, tenant="sme_hardware"):
    return orch.ask(ToolContext(ledger, tenant, NOW), question)


@pytest.mark.parametrize("question, amount", [
    ("can i take a loan of 5000000", "5000000"),
    ("I need 2 lakh taka for Eid stock", "200000"),
    ("loan of Tk 50,00,000 for 6 months", "5000000"),
    ("২ লাখ টাকা ঋণ নিতে পারব?", "200000"),
    ("我想贷50万", "500000"),
    ("borrow 20k for stock", "20000"),
    ("sales drop 20% in 30 days", None),
    ("500 kg of rice", None),
])
def test_the_amount_is_read_from_the_owners_words(question, amount):
    assert loan_amount(question) == (Decimal(amount) if amount else None)


@pytest.mark.parametrize("question, first", [
    ("what's my loan looking like right now", "current_loans"),
    ("When is my next EMI?", "current_loans"),
    ("আমার ঋণের কিস্তি কবে?", "current_loans"),
    ("can i take a loan of 5000000", "find_financing"),
    ("What happens to my cash if sales drop 20% next month?", "what_if"),
])
def test_the_question_asked_is_the_one_answered_first(question, first):
    assert classify(question)[0] == first


def test_a_model_plan_listing_cash_first_still_answers_the_loan_first():
    plan = build_plan({"intents": ["cash_outlook", "find_financing"], "tools": []},
                      "can i take a loan of 5000000", REGISTRY, planner="gemini_flash")
    assert plan.intents[0] == "find_financing"
    limits, answering = plan.focus()
    assert answering == ("financing.match",)
    assert limits == {"cash.forecast": 2, "cash.gaps": 1}


def test_my_loan_is_the_loan_being_repaid(orch, ledger):
    rec = ask(orch, ledger, "what's my loan looking like right now").recommendation
    assert rec.tools_used == ("loans.current",)
    assert rec.answer_text == "Loans you are repaying, on record: 1. " \
                              "Loan instalment: Tk 42,000, due 10 Oct."
    assert rec.action_cards == ()


def test_a_shop_with_no_loan_is_told_so(orch, ledger):
    rec = ask(orch, ledger, "what's my loan looking like", tenant="sme_grocery").recommendation
    assert rec.answer_text == "You are not repaying any loan on record (loans on record: 0)."


def test_a_named_amount_gets_a_yes_or_no_first_and_no_cash_gap_report(orch, ledger):
    rec = ask(orch, ledger, "can i take a loan of 5000", tenant="sme_grocery").recommendation
    assert rec.answer_text.startswith("Yes: a loan of Tk 5,000 is within what your cash flow")
    too_big = ask(orch, ledger, "can i take a loan of 5000000",
                  tenant="sme_grocery").recommendation
    assert too_big.answer_text.startswith("Not safely: a loan of Tk 50,00,000 is more than")
    assert too_big.action_cards == ()  # no application drafted for an unsafe amount
    assert len(too_big.claims) <= 4


def test_a_loan_answer_names_one_option_and_carries_no_cash_fix_cards(orch, ledger):
    rec = ask(orch, ledger, "Which loan is cheapest for me?").recommendation
    assert "Small enterprise refinance" not in (rec.answer_text or "")
    assert "chance of still falling below the buffer" not in rec.answer_text
    assert all(card.action_type.value == "submit_loan_application" for card in rec.action_cards)
    assert rec.answer_text.count("A cash gap is likely") <= 1
