from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.contracts import DataMode, FormulaRef, Granularity, Period, Principal, Role, Unit
from app.db import init_db, make_engine, session_factory
from app.facts import FactNotFound, FactStore, LedgerConflict, ProvenanceIncomplete
from app.facts.masking import mask_value, role_masker, set_masker
from app.facts.provenance import (
    combined_data_mode,
    compute,
    explain,
    explain_rows,
    record_computed,
    record_figure,
)
from app.facts.registry import REGISTRY, MetricDefinition, NotComputable, cite
from app.facts.seed import load_sme_into
from tests.facts.helpers import SEP, T, invoice, month, raw_fact, txn
from tests.facts.sample import (
    EXPECTED_SEP,
    INITIAL,
    LENDER,
    OWNER,
    STRANGER,
    TRANSACTIONS,
    load_sample,
)

INITIAL_ROW = f"fact:{INITIAL.id}"


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
    expected = {r for f in inputs for r in f.provenance.source_row_ids}
    assert set(fact.provenance.source_row_ids) == expected
    assert INITIAL_ROW in expected  # reaches the initial balance itself


def test_rows_are_cited_by_record_id_and_kept_once(store: FactStore):
    load_sample(store)
    fact = compute(store, T, "opening_balance", SEP)
    assert fact.provenance.input_fact_ids == (INITIAL.id,)
    assert fact.provenance.source_row_ids == (INITIAL_ROW, "txn:tenant_a-T7")
    assert fact.source_refs == ()  # rows live in provenance only


def test_recomputing_unchanged_data_returns_the_same_fact(store: FactStore):
    load_sample(store)
    first = compute(store, T, "dso", SEP)
    assert compute(store, T, "dso", SEP) == first
    assert len(store.facts(T, "dso")) == 1


def test_a_current_fact_is_served_without_recomputing(store: FactStore):
    load_sample(store)
    calls = []
    base = REGISTRY.get("cash_in")

    def counting(data):
        calls.append(1)
        return base.from_ledger(data)

    reg = REGISTRY.copy()
    reg._definitions[("cash_in", 1)] = MetricDefinition(
        "cash_in", base.formula_id, 1, base.expression, base.unit, from_ledger=counting)
    compute(store, T, "cash_in", SEP, registry=reg)
    compute(store, T, "cash_in", SEP, registry=reg)
    store.add_transactions([txn(60, date(2026, 9, 21), 5)])
    compute(store, T, "cash_in", SEP, registry=reg)
    assert len(calls) == 2  # once at first, once after the ledger changed


def test_new_rows_make_the_next_compute_current(store: FactStore):
    load_sample(store)
    old = compute(store, T, "cash_in", SEP)
    store.add_transactions([txn(50, date(2026, 9, 20), 100)])
    assert not store.is_current(old)
    new = compute(store, T, "cash_in", SEP)
    assert (old.value, new.value) == (Decimal("1500.00"), Decimal("1600.00"))
    assert store.get_fact(old.id).value == Decimal("1500.00")
    assert store.get(T, "cash_in", SEP) == new


def test_data_returning_to_an_earlier_state_serves_the_earlier_fact_again(store: FactStore):
    load_sample(store)
    sale = TRANSACTIONS[0]
    first = compute(store, T, "cash_in", SEP)
    store.add_transactions([sale.model_copy(update={"amount": sale.amount.scale(2)})])
    changed = compute(store, T, "cash_in", SEP)
    store.add_transactions([sale])
    again = compute(store, T, "cash_in", SEP)
    assert (first.value, changed.value) == (Decimal("1500.00"), Decimal("2500.00"))
    assert again.id == first.id
    assert store.get(T, "cash_in", SEP).value == Decimal("1500.00")


def test_metric_with_no_source_rows_abstains(store: FactStore):
    store.add_transactions([txn(1, date(2026, 9, 2), 100)])
    with pytest.raises(NotComputable, match="no source rows") as err:
        compute(store, T, "cash_out", SEP)
    assert err.value.reason_key == "facts.no_source_rows"
    with pytest.raises(FactNotFound):
        store.get(T, "cash_out", SEP)


def test_entity_scoped_metric_only_reads_that_counterparty(store: FactStore):
    other = invoice(2, date(2026, 9, 5), 900).model_copy(
        update={"counterparty_token": "PARTY_0000000002"})
    store.add_invoices([invoice(1, date(2026, 9, 3), 400), other])
    fact = compute(store, T, "receivables", SEP, "PARTY_0000000002")
    assert fact.value == Decimal("900.00")
    assert fact.entity_token == "PARTY_0000000002"
    assert fact.provenance.source_row_ids == (cite(other),)


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
    old = explain(store, fig.id, OWNER)
    assert (old.value, old.formula.version, old.formula.expression) == (
        Decimal("3000.00"), 1, "cash_sales + credit_sales (no returns or discounts are recorded)")
    assert explain(store, v2.id, OWNER).formula.expression == "cash_sales only"


def test_a_recorded_formula_version_cannot_change_its_expression(store: FactStore):
    load_sample(store)
    compute(store, T, "cash_in", SEP)
    store.add_transactions([txn(61, date(2026, 9, 22), 1)])  # force a recompute
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
    got = explain(store, fig.id, OWNER)
    assert got.formula.expression == "receivables / credit_sales * days_in_period"
    assert [(i.metric, i.value) for i in got.inputs] == [
        ("receivables", Decimal("2500.00")), ("credit_sales", Decimal("2000.00"))]
    assert got.value == Decimal("37.5") and got.unit is Unit.days
    assert set(got.source_rows) == {"inv:tenant_a:INV-1", "inv:tenant_a:INV-2"}
    assert got.masked is False


def test_explain_a_raw_fact_points_at_itself(store: FactStore):
    load_sample(store)
    got = explain(store, INITIAL.id, OWNER)
    assert got.formula.formula_id == "raw.source_row"
    assert (got.inputs, got.source_rows) == ((), (INITIAL_ROW,))


def test_figure_of_a_raw_fact_lists_the_fact_as_its_input(store: FactStore):
    load_sample(store)
    got = explain(store, record_figure(store, INITIAL, "cash.initial").id, OWNER)
    assert [i.fact_id for i in got.inputs] == [INITIAL.id]


def test_explain_unknown_id_raises(store: FactStore):
    with pytest.raises(FactNotFound):
        explain(store, "fig_nope", OWNER)


def test_another_tenants_figure_is_reported_as_unknown(store: FactStore):
    load_sample(store)
    fig = record_figure(store, compute(store, T, "cash_in", SEP), "cash.cash_in")
    for figure_id in (fig.id, compute(store, T, "cash_in", SEP).id):
        with pytest.raises(FactNotFound):
            explain(store, figure_id, STRANGER)
        with pytest.raises(FactNotFound):
            explain_rows(store, figure_id, STRANGER)


def _caller(role: Role) -> Principal:
    expiry = datetime(2026, 12, 31, tzinfo=UTC) if role is Role.lender_viewer else None
    return Principal(user_id=f"u-{role.value}", tenant_id=T, role=role, expires_at=expiry)


@pytest.mark.parametrize("role", list(Role))
def test_masking_hook_is_called_for_every_role(store: FactStore, role: Role):
    load_sample(store)
    fact = compute(store, T, "cash_in", SEP)
    calls = []

    def spy(tenant_id, rows, caller):
        calls.append((tenant_id, rows, caller.role))
        return ("hidden",) * len(rows), True

    got = explain(store, fact.id, _caller(role), masker=spy)
    assert calls == [(T, fact.provenance.source_row_ids, role)]
    assert (got.source_rows, got.masked) == (("hidden", "hidden"), True)


def test_installed_masker_is_used_by_default(store: FactStore):
    load_sample(store)
    fact = compute(store, T, "cash_in", SEP)
    previous = set_masker(lambda _t, rows, _c: (tuple(r.upper() for r in rows), True))
    try:
        assert explain(store, fact.id, OWNER).source_rows == ("TXN:TENANT_A-T1", "TXN:TENANT_A-T2")
    finally:
        set_masker(previous)


def test_stub_policy_masks_for_lenders_strangers_and_expired_access():
    rows = ("txn:tenant_a-T1", "txn:tenant_a-T2")
    assert role_masker(T, rows, OWNER) == (rows, False)
    masked, flag = role_masker(T, rows, LENDER)
    assert flag and len(masked) == 2 and not set(masked) & set(rows)
    assert role_masker(T, rows, LENDER)[0] == masked  # stable within a process
    assert role_masker(T, rows, STRANGER)[1] is True
    expired = OWNER.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)})
    assert role_masker(T, rows, expired)[1] is True


def test_masked_references_are_keyed_not_a_plain_hash():
    import hashlib

    plain = "masked:" + hashlib.sha256(f"{T}|txn:tenant_a-T1".encode()).hexdigest()[:16]
    assert mask_value(T, "txn:tenant_a-T1") != plain


@pytest.mark.parametrize(
    ("modes", "expected"),
    [((DataMode.live, DataMode.synthetic), DataMode.synthetic),
     ((DataMode.live, DataMode.public), DataMode.public),
     ((DataMode.live,), DataMode.live)],
)
def test_combined_data_mode_keeps_the_most_cautious_label(modes, expected):
    assert combined_data_mode(modes) is expected


# ---------------------------------------------------------------- the original records


def test_rows_resolve_to_the_original_records_page_by_page(store: FactStore):
    load_sample(store)
    fact = compute(store, T, "closing_balance", SEP)
    first = explain_rows(store, fact.id, OWNER, offset=0, limit=2)
    rest = explain_rows(store, fact.id, OWNER, offset=2, limit=50)
    assert first.total == rest.total == len(fact.provenance.source_row_ids) == 8
    assert [r.kind for r in first.rows] == ["fact", "transaction"]
    assert first.rows[0].record == INITIAL
    assert first.rows[1].record == TRANSACTIONS[6]
    assert len(rest.rows) == 6 and not rest.masked


def test_masked_callers_see_amounts_but_not_who_or_where(store: FactStore):
    load_sample(store)
    fact = compute(store, T, "cash_in", SEP)
    page = explain_rows(store, fact.id, LENDER)
    record = page.rows[0].record
    assert page.masked and page.rows[0].ref.startswith("masked:")
    assert record.amount.amount == Decimal("1000.00")
    assert record.counterparty_token is None and record.source_ref.startswith("masked:")


# ---------------------------------------------------------------- figures from other engines


FORECAST = FormulaRef(formula_id="cash.forecast_p50", version=1,
                      expression="median of 2000 Monte Carlo paths of daily net flow")


def test_another_engine_records_an_explainable_figure(store: FactStore):
    load_sample(store)
    closing = compute(store, T, "closing_balance", SEP)
    figure = record_computed(
        store, tenant_id=T, metric="forecast_balance_p50", value=Decimal("11800.00"),
        unit=Unit.BDT, period=month(2026, 10), formula=FORECAST, inputs=[closing],
        label_key="cash.forecast_p50", parameters={"seed": "20261020", "paths": "2000"})
    got = explain(store, figure.id, OWNER)
    assert got.formula == FORECAST
    assert [i.metric for i in got.inputs] == ["closing_balance"]
    assert set(got.source_rows) == set(closing.provenance.source_row_ids)
    assert store.get(T, "forecast_balance_p50", month(2026, 10)).provenance.parameters == {
        "seed": "20261020", "paths": "2000"}


@pytest.mark.parametrize("case", ["unstored-input", "other-tenant-input", "no-inputs"])
def test_unexplainable_engine_figures_are_refused(store: FactStore, case):
    load_sample(store)
    unstored = raw_fact("cash_in", "1.00", refs=("x.csv#L1",))
    foreign = store.put_fact(raw_fact("cash_in", "2.00", tenant="tenant_b"))
    inputs = {"unstored-input": [unstored], "other-tenant-input": [foreign], "no-inputs": []}
    with pytest.raises(ProvenanceIncomplete):
        record_computed(store, tenant_id=T, metric="forecast_balance_p50", value=Decimal(1),
                        unit=Unit.BDT, period=month(2026, 10), formula=FORECAST,
                        inputs=inputs[case], label_key="cash.forecast_p50")


def test_a_figure_whose_formula_was_never_recorded_is_refused(store: FactStore):
    load_sample(store)
    fact = compute(store, T, "cash_in", SEP)
    orphan = fact.model_copy(update={"provenance": fact.provenance.model_copy(
        update={"formula_id": "cash.never_recorded"})})
    with pytest.raises(ProvenanceIncomplete, match="not recorded"):
        record_figure(store, orphan, "cash.cash_in")


# ---------------------------------------------------------------- property


_rows = st.lists(
    st.tuples(st.integers(0, 59), st.integers(1, 10**7), st.booleans(),
              st.sampled_from(["sales", "purchase", "rent", "collection", "owner_draw"])),
    min_size=1, max_size=25,
)


@pytest.mark.property
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
        got = explain(store, record_figure(store, fact, f"x.{metric}").id, OWNER)
        known = {cite(t) for t in txns} | {INITIAL_ROW}
        assert len(got.source_rows) >= 1
        assert set(got.source_rows) <= known
        for fid in fact.provenance.input_fact_ids:
            assert store.get_fact(fid).tenant_id == T
    engine.dispose()
