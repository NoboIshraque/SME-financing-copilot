"""The copilot reads the WP-09 market engine: TCB prices and deal negotiation (Session A).

Prices come only from the TCB lists saved under data/public/prices/tcb/; every figure is
re-read from those files by the checker. Deal terms (item, quantity, offer, payment days) are
read by rules from the owner's own words; when one is missing the copilot names it.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.agents import checker as checker_cache
from app.agents import marketwords, selfloop
from app.agents.checker import Checker
from app.agents.orchestrator import Orchestrator
from app.agents.tools import ToolContext
from app.agents.toolset import REGISTRY
from app.api import cash as cash_api
from app.api import market as market_api
from app.contracts import AbstentionReason, CheckStatus, DataMode
from app.engines.market import watch
from app.llm import LLMGateway
from app.settings import LLMMode
from tests.agents.helpers import seeded_store

TODAY = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)  # the saved TCB lists run to 19 Oct


@pytest.fixture(scope="module")
def ledger(universe):
    for cache in (cash_api, checker_cache, selfloop):
        cache.clear_cache()
    engine, session, store = seeded_store(universe, ("sme_grocery",))
    yield store
    session.close()
    engine.dispose()
    for cache in (cash_api, checker_cache, selfloop):
        cache.clear_cache()


@pytest.fixture
def orch(settings):
    return Orchestrator(LLMGateway(settings.model_copy(update={"llm_mode": LLMMode.deterministic})))


def ask(orch, ledger, question):
    return orch.ask(ToolContext(ledger, "sme_grocery", TODAY), question)


def tcb_row(commodity):
    rows = watch.watchlist(market_api.observations(), TODAY.date())
    return next(r for r in rows if r.commodity == commodity)


# ---------------------------------------------------------------- prices


@pytest.mark.parametrize(("question", "commodities"), [
    ("What's the price of rice?", ("rice_coarse", "rice_fine")),
    ("চালের দাম কত?", ("rice_coarse", "rice_fine")),
    ("鸡蛋多少钱？", ("egg_farm",)),
    ("peyaj er dam koto?", ("onion",)),
], ids=["en", "bn", "zh", "banglish"])
def test_a_price_question_states_the_tcb_price_of_the_items_named(orch, ledger, question,
                                                                 commodities):
    run = ask(orch, ledger, question)
    rec = run.recommendation
    assert rec.abstention is None and rec.tools_used == ("market.prices",)
    assert {c.status for c in rec.checks} == {CheckStatus.verified}
    stated = {c.value for c in rec.claims}
    for commodity in commodities:
        row = tcb_row(commodity)
        assert row.latest.point.price.amount in stated
        assert row.change_pct in stated  # and how it moved against its baseline
    assert run.results["market.prices"].data_mode is DataMode.public  # TCB's public lists
    assert rec.data_mode is DataMode.synthetic  # ...answered to a synthetic demo shop


def test_with_no_item_named_it_reports_the_biggest_moves(orch, ledger):
    run = ask(orch, ledger, "Any big market price moves?")
    rows = run.results["market.prices"].payload["rows"]
    biggest = [row for row, _ in watch.alerts(watch.watchlist(market_api.observations(),
                                                              TODAY.date()))]
    assert [r.commodity for r in rows] == [r.commodity for r in biggest[:3]]


def test_a_changed_tcb_price_is_rejected_by_the_checker(ledger):
    context = ToolContext(ledger, "sme_grocery", TODAY)
    result = REGISTRY.run("market.prices", context, {"commodities": ("sugar",)})
    checker = Checker(context, context.results)
    for figure in result.figures:
        assert checker.check_figure(figure) is CheckStatus.verified
        moved = figure.model_copy(update={"value": figure.value + Decimal("0.5")})
        assert checker.check_figure(moved) is CheckStatus.rejected


# ---------------------------------------------------------------- negotiating a sale

DEAL = "A buyer offers Tk {offer} per kg for 200 kg of sugar, paying in 45 days. Accept the offer?"


@pytest.mark.parametrize(("offer", "verdict"), [
    ("130", "claim:negotiation.offer_ok:"),  # above today's TCB price on credit
    ("100", "claim:negotiation.offer_low:"),  # below what selling for cash earns today
], ids=["offer-clears", "offer-too-low"])
def test_a_deal_gets_a_verdict_against_the_walk_away_price_first(orch, ledger, offer, verdict):
    run = ask(orch, ledger, DEAL.format(offer=offer))
    rec = run.recommendation
    assert rec.abstention is None and run.plan.intents[0] == "negotiate"
    assert rec.claims[0].id.startswith(verdict)
    assert {c.status for c in rec.checks} == {CheckStatus.verified}
    plan = run.results["market.negotiate"].payload["plan"]
    sugar = tcb_row("sugar").latest.point.price.amount
    assert plan.walk_away.value >= sugar  # credit never prices below cash today
    assert (Decimal(offer) >= plan.walk_away.value) == verdict.endswith("offer_ok:")


def test_a_deal_without_its_terms_abstains_naming_each_missing_term(orch, ledger):
    rec = ask(orch, ledger, "Help me negotiate a better deal for my sugar").recommendation
    assert rec.abstention.reason is AbstentionReason.insufficient_data
    missing = " ".join(rec.abstention.missing)
    assert "how much you are selling" in missing and "offer per unit" in missing
    assert "when the buyer pays" in missing and "which item" not in missing


def test_a_changed_negotiation_price_is_rejected_by_the_checker(ledger):
    context = ToolContext(ledger, "sme_grocery", TODAY)
    REGISTRY.run("market.prices", context, {"commodities": ("sugar",)})
    result = REGISTRY.run("market.negotiate", context, {
        "commodity": "sugar", "quantity": "200", "offer": "120", "payment_days": 45})
    checker = Checker(context, context.results)
    for figure in result.figures:
        assert checker.check_figure(figure) is CheckStatus.verified
        moved = figure.model_copy(update={"value": figure.value + Decimal("0.01")})
        assert checker.check_figure(moved) is CheckStatus.rejected


# ---------------------------------------------------------------- reading the owner's words


@pytest.mark.parametrize(("question", "terms"), [
    ("A buyer offers Tk 60 per kg for 500 kg, paying in 30 days",
     {"quantity": Decimal(500), "offer": Decimal(60), "payment_days": 30}),
    ("৫০০ কেজি চাল কেজিপ্রতি ৬০ টাকা, ৩০ দিন পরে টাকা দেবে",
     {"quantity": Decimal(500), "offer": Decimal(60), "payment_days": 30}),
    ("1,200 kg at 55 taka, cash on delivery",
     {"quantity": Decimal(1200), "offer": Decimal(55), "payment_days": 0}),
    ("买家要 300 公斤，每公斤 58 元，60 天后付款",
     {"quantity": Decimal(300), "offer": Decimal(58), "payment_days": 60}),
    ("Help me negotiate", {}),
], ids=["en", "bn-digits", "cash", "zh", "nothing-stated"])
def test_deal_terms_are_read_from_the_owners_words(question, terms):
    assert marketwords.deal_terms(question) == terms


@pytest.mark.parametrize(("question", "commodities"), [
    ("চালান কবে আসবে?", ()),  # চালান (consignment) starts with চাল (rice)
    ("তেলের দাম", ("soybean_oil",)),
    ("sugar and salt prices", ("sugar", "salt")),
], ids=["consignment-is-not-rice", "bn-ending", "two-items"])
def test_items_are_named_by_whole_words(question, commodities):
    assert marketwords.commodities(question) == commodities
