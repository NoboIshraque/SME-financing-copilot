from decimal import Decimal

import pytest
from pydantic import BaseModel

from app.agents import checker as checker_cache
from app.agents import selfloop
from app.agents.tools import (
    BadParameters,
    InsufficientData,
    MissingProvenance,
    Tool,
    ToolContext,
    ToolRegistry,
    ToolResult,
    ToolUnavailable,
    UnknownTool,
    check_provenance,
)
from app.agents.toolset import REGISTRY, build_registry
from app.api import cash as cash_api
from app.contracts import (
    ActionType,
    DataMode,
    EligibilityStatus,
    Figure,
    Money,
    Provenance,
    Tier,
    Unit,
)
from app.facts import REGISTRY as METRICS
from app.llm.deterministic import INTENT_TOOLS
from tests.agents.helpers import NOW, seeded_store

INTERNAL_TOOLS = {"analysis.stability"}  # used by the self-loops, never planned directly


@pytest.fixture(scope="module")
def ledger(universe):
    cash_api.clear_cache()
    checker_cache.clear_cache()
    selfloop.clear_cache()
    engine, session, store = seeded_store(universe)
    yield store
    session.close()
    engine.dispose()
    cash_api.clear_cache()
    checker_cache.clear_cache()
    selfloop.clear_cache()


def ctx(store, tenant="sme_hardware") -> ToolContext:
    return ToolContext(store, tenant, NOW)


@pytest.fixture(scope="module")
def hardware(ledger):
    """One run of every available tool for the hardware shop (it has gaps and is in the
    synthetic debt ring)."""
    context = ctx(ledger)
    for name in ("cash.forecast", "cash.gaps", "financing.match", "analysis.ratios",
                 "mesh.propose"):
        REGISTRY.run(name, context)
    REGISTRY.run("analysis.scenarios", context, {"sales_change_pct": "-20"})
    return context.results


def figure(value="1.00", **prov) -> Figure:
    return Figure(id="f1", label_key="x", value=Decimal(value), unit=Unit.BDT,
                  data_mode=DataMode.synthetic,
                  provenance=Provenance(formula_id="cash.x", formula_version=1, **prov))


# --- registry contract --------------------------------------------------------------------

def test_planner_vocabulary_matches_the_registry():
    planned = {tool for tools in INTENT_TOOLS.values() for tool in tools}
    assert planned == set(REGISTRY.names()) - INTERNAL_TOOLS


@pytest.mark.parametrize("tier", [Tier.EXECUTE, Tier.DENY])
def test_a_tool_can_never_execute(tier):
    with pytest.raises(ValueError, match="tools read, suggest or draft"):
        ToolRegistry([Tool("x.y", "d", "e", tier=tier, run=lambda c, p: None)])


def test_tool_names_are_unique():
    registry = build_registry()
    with pytest.raises(ValueError, match="already registered"):
        registry.register(Tool("cash.gaps", "again", "WP-04"))


def test_unknown_tool(ledger):
    with pytest.raises(UnknownTool):
        REGISTRY.run("bank.transfer", ctx(ledger))


@pytest.mark.parametrize(("name", "params", "field"), [
    ("cash.forecast", {"buffer": "-5"}, "buffer"),
    ("cash.gaps", {"tenant_id": "sme_grocery"}, "tenant_id"),  # tenant comes from the context
    ("analysis.scenarios", {"sales_change_pct": "-150"}, "sales_change_pct"),
    ("financing.match", {"tenor_days": 0}, "tenor_days"),
    ("analysis.ratios", {"window_days": 7}, "window_days"),
    ("mesh.propose", {"allow_new_links": True}, "allow_new_links"),
])
def test_parameters_are_validated_before_the_engine_runs(ledger, name, params, field):
    with pytest.raises(BadParameters) as caught:
        REGISTRY.run(name, ctx(ledger), params)
    assert any(error.startswith(field) for error in caught.value.errors)


@pytest.mark.parametrize(("name", "engine"), [
    ("receivables.plan", "WP-05"),
    ("analysis.stability", "WP-07"),
    ("market.prices", "WP-09"),
    ("market.negotiate", "WP-09"),
    ("messaging.draft", "WP-12"),
])
def test_tools_without_an_engine_are_known_but_unavailable(ledger, name, engine):
    assert name in REGISTRY and name not in REGISTRY.names(available_only=True)
    with pytest.raises(ToolUnavailable) as caught:
        REGISTRY.run(name, ctx(ledger))
    assert caught.value.engine.startswith(engine)


@pytest.mark.parametrize(("name", "missing"), [
    ("cash.forecast", "at least 8 weeks of transactions"),
    ("cash.gaps", "at least 8 weeks of transactions"),
    ("analysis.scenarios", "at least 8 weeks of transactions"),
])
def test_short_history_names_exactly_what_is_missing(ledger, name, missing):
    context = ctx(ledger, "short_shop")
    assert context.history_days == 30
    with pytest.raises(InsufficientData) as caught:
        REGISTRY.run(name, context)
    assert caught.value.missing == (missing,)


def test_thirty_days_are_enough_for_ledger_ratios_but_gaps_are_not_guessed(ledger):
    result = REGISTRY.run("analysis.ratios", ctx(ledger, "short_shop"), {"window_days": 28})
    assert result.figure("analysis.net_cash_flow") is not None
    # no invoices on record: credit sales have no source rows, so net sales is not computed
    assert result.figure("analysis.net_sales") is None
    assert "net_sales:facts.no_source_rows" in result.notes


def test_manifest_describes_every_tool_for_the_planner():
    manifest = {row["name"]: row for row in REGISTRY.manifest()}
    assert manifest["cash.gaps"]["params"] == ["buffer", "seed"]
    assert manifest["cash.gaps"]["min_history_days"] == 56
    assert manifest["mesh.propose"]["tier"] == "DRAFT"
    assert manifest["market.prices"]["available"] is False


# --- provenance is enforced ----------------------------------------------------------------

def test_a_figure_that_cites_nothing_is_refused():
    with pytest.raises(MissingProvenance, match="cites nothing"):
        check_provenance(ToolResult("x.y", figures=(figure(),)))


def test_an_empty_result_must_say_why():
    with pytest.raises(MissingProvenance, match="must say why"):
        check_provenance(ToolResult("x.y"))
    check_provenance(ToolResult("x.y", notes=("cash.no_gap",)))


def test_registry_refuses_a_result_from_a_careless_adapter(ledger):
    registry = ToolRegistry([
        Tool("bad.figure", "d", "test", run=lambda c, p: ToolResult("bad.figure",
                                                                     figures=(figure(),))),
        Tool("bad.name", "d", "test", run=lambda c, p: ToolResult("other", notes=("n",))),
    ])
    context = ctx(ledger)
    for name in ("bad.figure", "bad.name"):
        with pytest.raises(MissingProvenance):
            registry.run(name, context)
    assert context.results == {}


def test_every_figure_of_every_tool_cites_facts_or_rows_on_record(ledger, hardware):
    for name, result in hardware.items():
        assert result.all_figures() or result.notes, name
        cited = {f.id for f in result.facts}
        for fig in result.all_figures():
            prov = fig.provenance
            assert prov.formula_id and (prov.input_fact_ids or prov.source_row_ids
                                        or prov.parameters), (name, fig.id)
            assert set(prov.input_fact_ids) <= cited, (name, fig.id)  # the checker has them
            for fact_id in prov.input_fact_ids:
                assert ledger.get_fact(fact_id, "sme_hardware").id == fact_id


# --- the engines behind the tools ----------------------------------------------------------

def test_forecast_figures_are_explainable_and_cite_the_closing_balance(ledger, hardware):
    result = hardware["cash.forecast"]
    labels = [f.label_key for f in result.figures]
    assert labels == ["cash.closing_balance", "cash.buffer_target", "cash.runway_days",
                      "cash.lowest_likely_balance"]
    closing = result.facts[0]
    assert closing.metric == "closing_balance"
    assert {f.metric for f in result.facts[1:]} == {"opening_balance", "cash_in", "cash_out"}
    for fig in result.figures[1:]:
        assert fig.provenance.input_fact_ids == (closing.id,)
        assert ledger.get_figure(fig.id, "sme_hardware")[1] == fig  # /api/explain can open it
    band = result.payload["band"]
    assert band.horizon_days == 91 and band.data_mode is DataMode.synthetic


def test_gaps_come_with_at_most_three_fixes(hardware):
    result = hardware["cash.gaps"]
    gaps = result.payload["gaps"]
    assert len(gaps) == 3
    assert 1 <= len(result.cards) <= 3
    assert {f.label_key for f in result.figures} >= {"cash.expected_shortfall"}


def test_financing_is_sized_to_the_first_gap_and_uses_the_forecast(hardware):
    result = hardware["financing.match"]
    gap = hardware["cash.gaps"].payload["gaps"][0]
    need = result.payload["need"]
    assert (need.amount, need.needed_by) == (gap.expected_shortfall, gap.first_breach_day)
    assert "fit.no_forecast" not in result.notes
    assert all(o.eligibility.status is not EligibilityStatus.fail
               for o in result.payload["options"])
    [card] = result.cards
    assert card.action_type is ActionType.draft_loan_application
    assert card.payload["product_id"] == result.payload["options"][0].product.id


def test_financing_without_a_gap_says_so(ledger):
    context = ctx(ledger, "sme_grocery")
    REGISTRY.run("cash.gaps", context)
    result = REGISTRY.run("financing.match", context)
    assert result.notes == ("financing.no_gap",) and result.figures == ()


def test_financing_needs_an_amount_or_a_gap_analysis(ledger):
    with pytest.raises(InsufficientData, match="amount and date"):
        REGISTRY.run("financing.match", ctx(ledger))


def test_financing_for_an_explicit_need(ledger):
    result = REGISTRY.run("financing.match", ctx(ledger),
                          {"amount": Money.of("50000"), "tenor_days": 180})
    assert result.payload["need"].amount == Money.of("50000")
    assert "fit.no_forecast" in result.notes  # nothing forecast in this run


def test_ratio_figures_recompute_from_their_cited_inputs(hardware):
    result = hardware["analysis.ratios"]
    facts = {f.id: f for f in result.facts}
    checked = 0
    for fact in result.payload["facts"]:
        definition = METRICS.get(fact.metric)
        if definition.from_inputs is None:
            continue
        inputs = {facts[i].metric: facts[i].value for i in fact.provenance.input_fact_ids}
        assert definition.compute_derived(inputs, fact.period) == fact.value
        checked += 1
    assert checked >= 4


def test_a_sales_shock_lowers_the_lowest_likely_balance(hardware):
    payload = hardware["analysis.scenarios"].payload
    before = {f.label_key: f.value for f in payload["before"]}
    after = {f.label_key: f.value for f in payload["after"]}
    assert payload["scenario"].sales_change_pct == Decimal(-20)
    assert after["cash.lowest_likely_balance"] < before["cash.lowest_likely_balance"]
    assert after["cash.runway_days"] <= before["cash.runway_days"]


def test_netting_round_for_a_shop_in_the_debt_ring(hardware):
    result = hardware["mesh.propose"]
    values = {f.label_key: f.value for f in result.figures}
    assert values["mesh.cash_saved"] == values["mesh.gross_total"] - values["mesh.net_total"] > 0
    [card] = result.cards
    assert (card.action_type, card.tier) == (ActionType.propose_netting_round, Tier.DRAFT)
    assert "sme_hardware" in card.payload["participants"]


def test_no_netting_round_outside_the_ring(ledger):
    result = REGISTRY.run("mesh.propose", ctx(ledger, "sme_grocery"))
    assert result.notes == ("mesh.no_cycle",) and result.cards == ()


class _Echo(BaseModel):
    n: int = 1


def test_runner_gets_validated_parameters(ledger):
    seen = []
    registry = ToolRegistry([Tool("t.echo", "d", "test", _Echo,
                                  run=lambda c, p: seen.append(p) or ToolResult(
                                      "t.echo", notes=("ok",)))])
    registry.run("t.echo", ctx(ledger), {"n": "3"})
    assert seen == [_Echo(n=3)]
