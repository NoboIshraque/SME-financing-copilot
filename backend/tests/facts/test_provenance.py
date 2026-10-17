from datetime import date, timedelta
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.contracts import DataMode, Granularity, Period, Role, TxCategory, Unit
from app.db import init_db, make_engine, session_factory
from app.facts import FactNotFound, FactStore, LedgerConflict
from app.facts.masking import role_masker, set_masker
from app.facts.provenance import combined_data_mode, compute, explain, record_figure
from app.facts.registry import REGISTRY, MetricDefinition, NotComputable
from app.facts.seed import load_sme_into
from tests.facts.helpers import SEP, T, invoice, month, txn
from tests.facts.sample import EXPECTED_SEP, INITIAL, load_sample


def test_every_metric_computed_through_the_store_matches_the_hand_values(store: FactStore):
    load_sample(store)
    got = {m: compute(store, T, m, SEP).value for m in REGISTRY.metrics()}
    assert got == EXPECTED_SEP


def test_closing_balance_reconciles_with_the_synthetic_ledger(store: FactStore, universe):
    sme = universe.smes["sme_pharmacy"]
    load_sme_into(store, sme, universe.start)
    fact = compute(store, sme.id, "closing_balance", month(2026, 9))
    assert fact.value == sme.balance_on(date(2026, 9, 30)).amount
    assert fact.data_mode is DataMode.synthetic


def test_derived_fact_links_its_inputs_and_the_closure_of_their_rows(store: FactStore):
    load_sample(store)
    fact = compute(store, T, "closing_balance", SEP)
    inputs = [store.get_fact(i) for i in fact.provenance.input_fact_ids]
    assert [f.metric for f in inputs] == ["opening_balance", "cash_in", "cash_out"]
    assert fact.provenance.formula_id == "cash.closing_balance"
    expected_rows = {r for f in inputs for r in f.provenance.source_row_ids}
    assert set(fact.provenance.source_row_ids) == expected_rows
    assert "profile.json#L1" in expected_rows  # reaches the initial balance's source


def test_opening_balance_cites_the_initial_balance_fact(store: FactStore):
    load_sample(store)
    fact = compute(store, T, "opening_balance", SEP)
    assert fact.provenance.input_fact_ids == (INITIAL.id,)
    assert fact.provenance.source_row_ids == ("profile.json#L1", "bkash.csv#L7")


def test_recomputing_unchanged_data_returns_the_same_fact(store: FactStore):
    load_sample(store)
    first = compute(store, T, "dso", SEP)
    again = compute(store, T, "dso", SEP)
    assert again == first
    assert len(store.facts(T, "dso")) == 1


def test_changed_data_adds_a_new_fact_and_keeps_the_old_one(store: FactStore):
    load_sample(store)
    old = compute(store, T, "cash_in", SEP)
    store.add_transactions([txn(50, date(2026, 9, 20), 100)])
    new = compute(store, T, "cash_in", SEP)
    assert (old.value, new.value) == (Decimal("1500.00"), Decimal("1600.00"))
    assert store.get_fact(old.id).value == Decimal("1500.00")
    assert store.get(T, "cash_in", SEP) == new


def test_metric_with_no_source_rows_abstains(store: FactStore):
    store.add_transactions([txn(1, date(2026, 9, 2), 100)])
    with pytest.raises(NotComputable, match="no source rows"):
        compute(store, T, "cash_out", SEP)
    with pytest.raises(FactNotFound):
        store.get(T, "cash_out", SEP)


def test_entity_scoped_metric_only_reads_that_counterparty(store: FactStore):
    other = invoice(2, date(2026, 9, 5), 900).model_copy(
        update={"counterparty_token": "PARTY_0000000002"})
    store.add_invoices([invoice(1, date(2026, 9, 3), 400), other])
    fact = compute(store, T, "receivables", SEP, "PARTY_0000000002")
    assert fact.value == Decimal("900.00")
    assert fact.entity_token == "PARTY_0000000002"
    assert fact.provenance.source_row_ids == (other.source_ref,)


def test_balance_metrics_refuse_an_entity(store: FactStore):
    load_sample(store)
    with pytest.raises(NotComputable, match="per counterparty"):
        compute(store, T, "closing_balance", SEP, "PARTY_0000000001")


def test_a_new_formula_version_does_not_rewrite_old_figures(store: FactStore):
    load_sample(store)
    v1 = compute(store, T, "net_sales", SEP)
    fig = record_figure(store, v1, "sales.net_sales")
    reg = REGISTRY.copy()
    reg.register(MetricDefinition(
        "net_sales", "sales.net_sales", 2, "cash_sales only", Unit.BDT,
        inputs=("cash_sales", "credit_sales"), from_inputs=lambda v, _p: v["cash_sales"]))
    v2 = compute(store, T, "net_sales", SEP, registry=reg)

    assert v2.value == Decimal("1000.00") and v2.id != v1.id
    assert store.get_fact(v1.id) == v1
    old = explain(store, fig.id, Role.owner)
    assert (old.value, old.formula.version, old.formula.expression) == (
        Decimal("3000.00"), 1, "cash_sales + credit_sales (no returns or discounts are recorded)")
    assert explain(store, v2.id, Role.owner).formula.expression == "cash_sales only"


def test_a_recorded_formula_version_cannot_change_its_expression(store: FactStore):
    load_sample(store)
    compute(store, T, "cash_in", SEP)
    reg = REGISTRY.copy()
    reg._definitions[("cash_in", 1)] = MetricDefinition(
        "cash_in", "cash.cash_in", 1, "something else", Unit.BDT,
        from_ledger=REGISTRY.get("cash_in").from_ledger)
    with pytest.raises(LedgerConflict, match="bump the version"):
        compute(store, T, "cash_in", SEP, registry=reg)


# ---------------------------------------------------------------- explain


def test_explain_a_figure_gives_formula_inputs_and_rows(store: FactStore):
    load_sample(store)
    fig = record_figure(store, compute(store, T, "dso", SEP), "receivables.dso")
    got = explain(store, fig.id, Role.owner)
    assert got.formula.expression == "receivables / net_sales * days_in_period"
    assert [(i.metric, i.value) for i in got.inputs] == [
        ("receivables", Decimal("2500.00")), ("net_sales", Decimal("3000.00"))]
    assert got.value == Decimal("25.0") and got.unit is Unit.days
    assert set(got.source_rows) == {"invoices.csv#L1", "invoices.csv#L2", "invoices.csv#L3",
                                    "bkash.csv#L1"}
    assert got.masked is False


def test_explain_a_raw_fact_points_at_its_source_row(store: FactStore):
    load_sample(store)
    got = explain(store, INITIAL.id, Role.owner)
    assert got.formula.formula_id == "raw.source_row"
    assert got.inputs == () and got.source_rows == ("profile.json#L1",)


def test_figure_of_a_raw_fact_lists_the_fact_as_its_input(store: FactStore):
    load_sample(store)
    got = explain(store, record_figure(store, INITIAL, "cash.initial").id, Role.owner)
    assert [i.fact_id for i in got.inputs] == [INITIAL.id]


def test_explain_unknown_id_raises(store: FactStore):
    with pytest.raises(FactNotFound):
        explain(store, "fig_nope", Role.owner)


@pytest.mark.parametrize("role", list(Role))
def test_masking_hook_is_called_for_every_role(store: FactStore, role: Role):
    load_sample(store)
    fact = compute(store, T, "cash_in", SEP)
    calls = []

    def spy(tenant_id, rows, who):
        calls.append((tenant_id, rows, who))
        return ("hidden",), True

    got = explain(store, fact.id, role, masker=spy)
    assert calls == [(T, fact.provenance.source_row_ids, role)]
    assert (got.source_rows, got.masked) == (("hidden",), True)


def test_installed_masker_is_used_by_default(store: FactStore):
    load_sample(store)
    fact = compute(store, T, "cash_in", SEP)
    previous = set_masker(lambda _t, rows, _r: (tuple(r.upper() for r in rows), True))
    try:
        assert explain(store, fact.id, Role.owner).source_rows == ("BKASH.CSV#L1", "BKASH.CSV#L2")
    finally:
        set_masker(previous)


def test_stub_policy_masks_for_lenders_but_not_for_the_owner():
    rows = ("bkash.csv#L1", "bkash.csv#L2")
    assert role_masker(T, rows, Role.owner) == (rows, False)
    masked, flag = role_masker(T, rows, Role.lender_viewer)
    assert flag and len(masked) == 2 and not set(masked) & set(rows)
    assert role_masker(T, rows, Role.lender_viewer)[0] == masked  # stable


@pytest.mark.parametrize(
    ("modes", "expected"),
    [((DataMode.live, DataMode.synthetic), DataMode.synthetic),
     ((DataMode.live, DataMode.public), DataMode.public),
     ((DataMode.live,), DataMode.live)],
)
def test_combined_data_mode_keeps_the_most_cautious_label(modes, expected):
    assert combined_data_mode(modes) is expected


# ---------------------------------------------------------------- property


_categories = st.sampled_from([TxCategory.sales, TxCategory.purchase, TxCategory.rent,
                               TxCategory.collection, TxCategory.owner_draw])
_rows = st.lists(
    st.tuples(st.integers(0, 59), st.integers(1, 10**7), st.booleans(), _categories),
    min_size=1, max_size=25,
)


@pytest.mark.property
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(rows=_rows, metric=st.sampled_from(REGISTRY.metrics()))
def test_any_computed_figure_resolves_to_source_rows(rows, metric):
    engine = make_engine("sqlite://")
    init_db(engine)
    with session_factory(engine)() as session:
        store = FactStore(session)
        store.put_fact(INITIAL)
        txns = [txn(n, date(2026, 8, 15) + timedelta(days=d), amount,
                    "inflow" if inflow else "outflow", category)
                for n, (d, amount, inflow, category) in enumerate(rows, start=1)]
        store.add_transactions(txns)
        period = Period(start=date(2026, 9, 1), end=date(2026, 9, 30),
                        granularity=Granularity.month)
        try:
            fact = compute(store, T, metric, period)
        except NotComputable:
            return
        got = explain(store, record_figure(store, fact, f"x.{metric}").id, Role.owner)
        known = {t.source_ref for t in txns} | set(INITIAL.source_refs)
        assert len(got.source_rows) >= 1
        assert set(got.source_rows) <= known
        for fid in fact.provenance.input_fact_ids:
            assert store.get_fact(fid).tenant_id == T
    engine.dispose()
