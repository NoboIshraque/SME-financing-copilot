from decimal import Decimal

import pytest
from sqlalchemy import select

from app.agents import checker as checker_cache
from app.agents.checker import (
    Checker,
    formula_expression,
    log_rejections,
    numbers_in,
    symbolic_value,
    unverified_numbers,
)
from app.agents.claims import Statement, compose, render
from app.agents.models import RejectedClaimRow
from app.agents.tools import ToolContext
from app.agents.toolset import REGISTRY
from app.api import cash as cash_api
from app.contracts import CheckStatus, Period, Unit
from app.facts import REGISTRY as METRICS
from app.facts.registry import MetricDefinition
from tests.agents.helpers import NOW, seeded_store

ORDER = ("cash.forecast", "cash.gaps", "analysis.scenarios", "analysis.ratios",
         "financing.match", "mesh.propose")
STEP = {Unit.BDT: Decimal("0.01"), Unit.ratio: Decimal("0.0001"),
        Unit.probability: Decimal("0.0001"), Unit.percent: Decimal("0.01"),
        Unit.days: Decimal(1)}
# Every kind of number the copilot states (template key = the claim id's second part).
TEMPLATES = (
    "cash.closing_balance", "cash.lowest_likely_balance", "cash.runway_days",
    "cash.buffer_target", "cash.expected_shortfall", "cash.lead_time_days",
    "cash.breach_probability", "action.gap_reduced", "action.cost",
    "financing.effective_annual_rate", "financing.total_cost", "financing.p_buffer_breach",
    "analysis.net_sales", "analysis.gross_profit", "analysis.gross_margin",
    "analysis.operating_expenses", "analysis.net_cash_flow", "analysis.dso", "analysis.dpo",
    "scenario.lowest_before", "scenario.lowest_after", "scenario.runway_before",
    "scenario.runway_after", "mesh.gross_total", "mesh.net_total", "mesh.cash_saved",
)


@pytest.fixture(scope="module")
def ledger(universe):
    cash_api.clear_cache()
    checker_cache.clear_cache()
    engine, session, store = seeded_store(universe, shops=("sme_hardware",))
    yield store
    session.close()
    engine.dispose()
    cash_api.clear_cache()
    checker_cache.clear_cache()


@pytest.fixture(scope="module")
def run(ledger):
    ctx = ToolContext(ledger, "sme_hardware", NOW)
    for name in ORDER:
        REGISTRY.run(name, ctx, {"sales_change_pct": "-20"}
                     if name == "analysis.scenarios" else None)
    statements = compose(ctx.results, ORDER, "en")
    return ctx, Checker(ctx, ctx.results), {s.claim.id.split(":")[1]: s for s in statements}


def tampered(item: Statement, value: Decimal) -> tuple:
    figure = item.figure.model_copy(update={"value": value})
    text = item.claim.text.replace(render(item.claim.value, item.claim.unit),
                                   render(value, item.claim.unit))
    return item.claim.model_copy(update={"value": value, "text": text}), figure


def test_the_run_states_every_kind_of_number(run):
    assert set(TEMPLATES) <= set(run[2])


@pytest.mark.parametrize("template", TEMPLATES)
def test_every_stated_number_recomputes_exactly(run, template):
    item = run[2][template]
    check = run[1].check(item.claim, item.figure)
    assert check.status is CheckStatus.verified, check.reason
    assert check.recomputed_value == item.claim.value


@pytest.mark.parametrize("template", TEMPLATES)
def test_an_injected_wrong_number_is_rejected(run, template):
    """The figure and its claim are tampered with consistently: only recomputation can tell."""
    item = run[2][template]
    claim, figure = tampered(item, item.claim.value + STEP[item.claim.unit])
    check = run[1].check(claim, figure)
    assert check.status is CheckStatus.rejected
    assert check.recomputed_value == item.claim.value


def test_text_must_state_the_claimed_value(run):
    item = run[2]["cash.closing_balance"]
    claim = item.claim.model_copy(update={"text": "Cash on hand now: Tk 1,00,000."})
    check = run[1].check(claim, item.figure)
    assert (check.status, check.reason) == (CheckStatus.rejected,
                                            "the text does not state the claimed value")


def test_claim_must_match_its_figure(run):
    item = run[2]["financing.total_cost"]
    claim, _ = tampered(item, item.claim.value * 2)
    check = run[1].check(claim, item.figure)
    assert check.reason == "the claim does not match its figure"
    assert check.recomputed_value == item.figure.value


def test_claim_must_cite_the_figures_facts(run):
    item = run[2]["analysis.gross_margin"]
    claim = item.claim.model_copy(update={"input_fact_ids": ("fact_someone_else",)})
    assert run[1].check(claim, item.figure).reason == \
        "the claim cites other facts than its figure"


def test_unknown_formula_is_unverifiable(run):
    item = run[2]["cash.closing_balance"]
    prov = item.figure.provenance.model_copy(update={"formula_id": "magic.number"})
    figure = item.figure.model_copy(update={"provenance": prov})
    claim = item.claim.model_copy(update={"formula_id": "magic.number"})
    check = run[1].check(claim, figure)
    assert check.status is CheckStatus.unverifiable and "magic.number" in check.reason


def test_a_fit_figure_from_another_forecast_is_unverifiable(run):
    item = run[2]["financing.p_buffer_breach"]
    params = {**item.figure.provenance.parameters, "principal": "1.00"}
    prov = item.figure.provenance.model_copy(update={"parameters": params})
    check = run[1].check(item.claim, item.figure.model_copy(update={"provenance": prov}))
    assert check.status is CheckStatus.unverifiable


# --- SymPy: the code and the published formula must agree --------------------------------

@pytest.mark.parametrize(("metric", "values", "days", "expected"), [
    ("gross_margin", {"net_sales": "1000", "purchases": "750"}, 90, "0.2500"),
    ("gross_profit", {"net_sales": "1000", "purchases": "750"}, 90, "250.00"),
    ("net_sales", {"cash_sales": "600", "credit_sales": "400.50"}, 90, "1000.50"),
    ("dso", {"receivables": "300", "credit_sales": "900"}, 90, "30.0"),
    ("closing_balance", {"opening_balance": "100", "cash_in": "50", "cash_out": "70"}, 1,
     "80.00"),
])
def test_published_formula_evaluates_like_the_code(metric, values, days, expected):
    definition = METRICS.get(metric)
    assert formula_expression(definition) is not None  # prose comments are stripped
    decimals = {k: Decimal(v) for k, v in values.items()}
    period = Period(start=NOW.date(), end=NOW.date())
    assert symbolic_value(definition, decimals, days) == Decimal(expected)
    if days == 1:
        assert definition.compute_derived(decimals, period) == Decimal(expected)


def test_code_that_drifts_from_its_formula_is_rejected(run, monkeypatch):
    honest = METRICS.get("gross_margin")
    drifted = MetricDefinition(  # same id and expression, wrong code (divides by purchases)
        honest.metric, honest.formula_id, honest.version, honest.expression, honest.unit,
        inputs=honest.inputs, from_inputs=lambda v, _p: (v["net_sales"] - v["purchases"])
        / v["purchases"])
    checker = Checker(run[0], run[0].results)
    monkeypatch.setitem(checker._by_formula, honest.formula_id, drifted)
    item = run[2]["analysis.gross_margin"]
    check = checker.check(item.claim, item.figure)
    assert check.status is CheckStatus.rejected and "published formula" in check.reason


# --- narration ----------------------------------------------------------------------------

def test_numbers_in_reads_grouping_bangla_digits_and_skips_names():
    text = "Startup financing (Circular 02, 9 Jul 2025): Tk ১,২৩,৪৫৬.৫০ at 4.07%."
    assert numbers_in(text, ["Startup financing (Circular 02, 9 Jul 2025)"]) == {
        Decimal("123456.5"), Decimal("4.07")}


def test_a_narrated_number_must_come_from_a_verified_claim(run):
    items = [run[2]["cash.closing_balance"], run[2]["financing.effective_annual_rate"]]
    value = render(items[0].claim.value, Unit.BDT)
    rate = render(items[1].claim.value, Unit.percent)
    assert unverified_numbers(f"You hold Tk {value}; the loan costs {rate} a year.",
                              items) == set()
    assert unverified_numbers(f"You hold Tk {value}; borrow Tk 50,000 today.",
                              items) == {Decimal(50000)}


# --- logging ------------------------------------------------------------------------------

def test_removed_claims_are_logged_without_personal_data(run, ledger):
    item = run[2]["cash.expected_shortfall"]
    claim, figure = tampered(item, item.claim.value + 1)
    check = run[1].check(claim, figure)
    count = log_rejections([check], {claim.id: claim}, tenant_id="sme_hardware",
                           recommendation_id="rec_test", now=NOW, session=ledger.session)
    ledger.session.flush()
    rows = ledger.session.scalars(select(RejectedClaimRow).where(
        RejectedClaimRow.recommendation_id == "rec_test")).all()
    assert count == 1 and len(rows) == 1
    assert (rows[0].status, rows[0].claimed, rows[0].recomputed) == (
        "rejected", str(claim.value), str(item.claim.value))
    assert rows[0].formula_id == "cash.expected_shortfall"
