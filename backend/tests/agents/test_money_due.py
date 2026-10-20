"""Upcoming payments, money owed and the safe loan size, end to end (Session A).

The two questions that got "won't guess" or a non-answer on the hosted site on 20 Oct are
kept here as regressions, through the real orchestrator on the deterministic planner (what the
hosted demo runs), with every claim recomputed by the checker.
"""

import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.agents import checker as checker_cache
from app.agents import ledgerdue, loansize, selfloop
from app.agents.checker import Checker
from app.agents.claims import statement
from app.agents.models import AbstentionRow
from app.agents.orchestrator import Orchestrator
from app.agents.tools import ToolContext
from app.agents.toolset import REGISTRY
from app.api import cash as cash_api
from app.contracts import AbstentionReason, CheckStatus
from app.llm import LLMGateway
from app.settings import LLMMode
from tests.agents.helpers import NOW, Scripted, seeded_store

AS_OF = date(2026, 9, 30)


@pytest.fixture(scope="module")
def ledger(universe):
    for cache in (cash_api, checker_cache, selfloop):
        cache.clear_cache()
    engine, session, store = seeded_store(universe, ("sme_grocery", "sme_garment",
                                                     "sme_hardware"))
    yield store
    session.close()
    engine.dispose()
    for cache in (cash_api, checker_cache, selfloop):
        cache.clear_cache()


@pytest.fixture
def orch(settings):
    return Orchestrator(LLMGateway(settings.model_copy(update={"llm_mode": LLMMode.deterministic})))


def ask(orch, ledger, question, tenant):
    return orch.ask(ToolContext(ledger, tenant, NOW), question)


def verified_claims(run):
    status = {c.claim_id: c.status for c in run.recommendation.checks}
    return [c for c in run.recommendation.claims if status[c.id] is CheckStatus.verified]


# ---------------------------------------------------------------- the two hosted-site failures


def test_bangla_when_do_i_pay_the_next_bills_lists_them_soonest_first(orch, ledger, universe):
    run = ask(orch, ledger, "সামনে কবে বিল দিব", "sme_grocery")
    rec = run.recommendation
    assert rec.abstention is None and rec.tools_used == ("payables.upcoming",)
    assert len(verified_claims(run)) == len(rec.claims) >= 3
    grocery = universe.smes["sme_grocery"]
    expected = ledgerdue.upcoming(grocery.bills, grocery.obligations, AS_OF)
    assert run.results["payables.upcoming"].figure("copilot.payables_total").value == \
        sum(d.amount for d in expected)
    assert "বিল" in rec.answer_text and "৩ অক্টোবর" in rec.answer_text  # Bangla, dated


def test_how_big_a_loan_answers_with_the_largest_safe_amount_first(orch, ledger):
    run = ask(orch, ledger, "How big a loan can I safely take?", "sme_garment")
    rec = run.recommendation
    assert rec.abstention is None
    lead = rec.claims[0]
    assert lead.formula_id == loansize.FORMULA_ID and lead.value > 0
    assert rec.answer_text.startswith("The largest loan you can safely repay")
    assert len(verified_claims(run)) == len(rec.claims)
    # the amount really is the largest safe one on this forecast
    size, figure = run.results["financing.match"].payload["safe"][0]
    band = run.results["cash.gaps"].payload["band"]
    start = date.fromisoformat(figure.provenance.parameters["start"])
    assert loansize.is_safe(size.product, size.amount, 90, start, band, {})
    assert not loansize.is_safe(size.product, size.amount + loansize.STEP, 90, start, band, {})


def test_how_big_a_loan_with_a_cash_gap_says_no_loan_is_safe_and_why(orch, ledger):
    rec = ask(orch, ledger, "How big a loan can I safely take?", "sme_hardware").recommendation
    assert rec.abstention is None
    assert rec.claims[0].id.startswith("claim:copilot.no_safe_loan_gap:")


def test_which_loan_with_no_gap_no_longer_stops_at_no_gap(orch, ledger):
    rec = ask(orch, ledger, "Which loan is best for me?", "sme_garment").recommendation
    assert any(c.formula_id == loansize.FORMULA_ID for c in rec.claims)


# ---------------------------------------------------------------- money owed, help, cut engines


def test_who_owes_me_names_the_customer_to_chase_first(orch, ledger):
    run = ask(orch, ledger, "Which customer should I chase first?", "sme_hardware")
    rec = run.recommendation
    assert rec.abstention is None and rec.tools_used == ("receivables.plan",)
    assert len(verified_claims(run)) == len(rec.claims)
    owed = run.results["receivables.plan"].payload["owed"]
    first = owed.customers[0]
    assert first.overdue and "Chase Customer" in rec.answer_text
    assert rec.claims[0].value == owed.open_total


@pytest.mark.parametrize("question", ["hi", "What can you do?", "কী করতে পারো?", "你能做什么？"])
def test_a_greeting_gets_the_menu_and_is_not_logged_as_an_abstention(orch, ledger, question):
    before = ledger.session.scalar(select(func.count()).select_from(AbstentionRow))
    rec = ask(orch, ledger, question, "sme_grocery").recommendation
    assert rec.abstention.message_key == "copilot.help.intro" and rec.claims == ()
    assert ledger.session.scalar(select(func.count()).select_from(AbstentionRow)) == before


def test_an_unknown_question_still_abstains_and_is_logged(orch, ledger):
    rec = ask(orch, ledger, "Tell me a joke", "sme_grocery").recommendation
    assert rec.abstention.reason is AbstentionReason.out_of_scope
    assert rec.abstention.message_key == "abstain.out_of_scope"


# ---------------------------------------------------------------- the checker does not trust them


def _context(ledger, tenant, *tools, params=None):
    context = ToolContext(ledger, tenant, NOW)
    for tool in tools:
        REGISTRY.run(tool, context, (params or {}).get(tool))
    return context


@pytest.mark.parametrize(("tenant", "tool", "label"), [
    ("sme_grocery", "payables.upcoming", "copilot.payables_total"),
    ("sme_grocery", "payables.upcoming", "copilot.payables_count"),
    ("sme_grocery", "payables.upcoming", "copilot.payable_item"),
    ("sme_hardware", "receivables.plan", "copilot.receivables_open"),
    ("sme_hardware", "receivables.plan", "copilot.receivables_overdue"),
    ("sme_hardware", "receivables.plan", "copilot.customer_owes"),
])
def test_money_due_figures_recompute_and_a_changed_value_is_rejected(ledger, tenant, tool, label):
    context = _context(ledger, tenant, tool)
    checker = Checker(context, context.results)
    figure = context.results[tool].figure(label)
    assert checker.check_figure(figure) is CheckStatus.verified
    bumped = figure.model_copy(update={"value": figure.value + 1})
    assert checker.check(statement("copilot.payables_total", bumped, "en").claim,
                         bumped).status is CheckStatus.rejected


@pytest.mark.parametrize("delta", [-loansize.STEP, loansize.STEP], ids=["smaller", "larger"])
def test_a_safe_loan_amount_that_is_not_the_largest_safe_one_is_rejected(ledger, delta):
    context = _context(ledger, "sme_garment", "cash.gaps", "financing.match")
    checker = Checker(context, context.results)
    _, figure = context.results["financing.match"].payload["safe"][0]
    assert checker.check_figure(figure) is CheckStatus.verified
    moved = figure.model_copy(update={"value": figure.value + delta})
    assert checker.check_figure(moved) is CheckStatus.rejected


def test_upcoming_lists_overdue_bills_and_month_end_salaries(universe):
    grocery = universe.smes["sme_grocery"]
    due = ledgerdue.upcoming(grocery.bills, grocery.obligations, AS_OF)
    assert [d.day for d in due] == sorted(d.day for d in due)
    assert any(d.kind == "salary" and d.day == date(2026, 10, 31) for d in due)
    bill = next(b for b in grocery.bills if b.outstanding.amount > 0)
    overdue = bill.model_copy(update={"due_date": AS_OF - timedelta(days=3),
                                      "issue_date": AS_OF - timedelta(days=20)})
    first = ledgerdue.upcoming([overdue], [], AS_OF)[0]
    assert first.overdue and first.amount == overdue.outstanding.amount


def test_owed_puts_overdue_customers_before_ones_not_yet_due(universe):
    owed = ledgerdue.owed(universe.smes["sme_hardware"].invoices, AS_OF)
    flags = [c.overdue for c in owed.customers]
    assert flags == sorted(flags, reverse=True)
    assert owed.open_total == sum(c.amount for c in owed.customers)
    assert owed.overdue_total <= owed.open_total and owed.overdue_total > Decimal(0)


def test_an_empty_model_plan_falls_back_to_the_rules_locally(live_settings, ledger, clock):
    empty = json.dumps({"intents": ["unknown"], "tools": [], "language": "bn"})
    gateway = LLMGateway(live_settings, transport=Scripted({"gemini_flash": [empty]}),
                         clock=clock)
    run = Orchestrator(gateway).ask(ToolContext(ledger, "sme_grocery", NOW), "সামনে কবে বিল দিব")
    assert run.plan.planner == "deterministic" and run.plan.intents == ("upcoming_payments",)
    assert run.recommendation.abstention is None
    assert any(e.outcome == "model_plan_empty" for e in run.trace)
