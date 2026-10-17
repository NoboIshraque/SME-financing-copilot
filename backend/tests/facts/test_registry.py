from datetime import date
from decimal import Decimal

import pytest

from app.contracts import Period, Unit
from app.facts.registry import (
    REGISTRY,
    LedgerInputs,
    MetricDefinition,
    NotComputable,
    UnknownMetric,
    build_default_registry,
    outstanding_at,
)
from tests.facts.helpers import SEP, invoice
from tests.facts.sample import BILLS, EXPECTED_SEP, INITIAL, INVOICES, TRANSACTIONS

LEDGER = LedgerInputs(
    period=SEP,
    transactions=tuple(t for t in TRANSACTIONS if t.day <= SEP.end),
    invoices=INVOICES,
    bills=BILLS,
    initial_balance=INITIAL,
)
LEDGER_METRICS = [m for m in REGISTRY.metrics() if REGISTRY.get(m).from_ledger is not None]


@pytest.mark.parametrize("metric", LEDGER_METRICS)
def test_ledger_metric_matches_hand_computed_value(metric: str):
    assert REGISTRY.get(metric).compute_ledger(LEDGER).value == EXPECTED_SEP[metric]


@pytest.mark.parametrize(
    ("metric", "inputs", "period", "expected"),
    [
        ("net_sales", {"cash_sales": "1000", "credit_sales": "2000"}, SEP, "3000.00"),
        ("net_cash_flow", {"cash_in": "100", "cash_out": "250.55"}, SEP, "-150.55"),
        ("closing_balance", {"opening_balance": "10400", "cash_in": "1500", "cash_out": "650"},
         SEP, "11250.00"),
        ("gross_profit", {"net_sales": "3000", "purchases": "3500"}, SEP, "-500.00"),
        ("gross_margin", {"net_sales": "3000", "purchases": "2000"}, SEP, "0.3333"),
        ("gross_margin", {"net_sales": "3", "purchases": "1"}, SEP, "0.6667"),
        ("dso", {"receivables": "2500", "net_sales": "3000"}, SEP, "25.0"),
        ("dso", {"receivables": "1000", "net_sales": "3000"},
         Period(start=date(2026, 2, 1), end=date(2026, 2, 28)), "9.3"),
        ("dpo", {"payables": "1200", "purchases": "1500"}, SEP, "24.0"),
    ],
    ids=["net-sales", "negative-net-flow", "closing", "gross-loss", "margin-round-down",
         "margin-round-half-up", "dso-30-days", "dso-28-day-month", "dpo"],
)
def test_derived_metric_matches_hand_computed_value(metric, inputs, period, expected):
    values = {k: Decimal(v) for k, v in inputs.items()}
    assert REGISTRY.get(metric).compute_derived(values, period) == Decimal(expected)


@pytest.mark.parametrize(
    ("metric", "inputs"),
    [
        ("gross_margin", {"net_sales": "0", "purchases": "10"}),
        ("dso", {"receivables": "10", "net_sales": "0"}),
        ("dpo", {"payables": "10", "purchases": "0"}),
    ],
)
def test_zero_denominator_abstains_instead_of_guessing(metric, inputs):
    with pytest.raises(NotComputable, match="denominator"):
        REGISTRY.get(metric).compute_derived({k: Decimal(v) for k, v in inputs.items()}, SEP)


def test_missing_input_abstains():
    with pytest.raises(NotComputable, match="missing"):
        REGISTRY.get("dso").compute_derived({"receivables": Decimal(1)}, SEP)


def test_opening_balance_needs_an_initial_balance():
    data = LedgerInputs(period=SEP, transactions=LEDGER.transactions)
    with pytest.raises(NotComputable, match="initial_balance"):
        REGISTRY.get("opening_balance").compute_ledger(data)


def test_opening_balance_refuses_a_period_before_the_initial_balance():
    data = LedgerInputs(period=Period(start=date(2026, 7, 1), end=date(2026, 7, 31)),
                        initial_balance=INITIAL)
    with pytest.raises(NotComputable, match="before"):
        REGISTRY.get("opening_balance").compute_ledger(data)


def test_ledger_metric_reports_exactly_the_rows_it_used():
    refs = REGISTRY.get("operating_expenses").compute_ledger(LEDGER).source_refs
    assert refs == ("bkash.csv#L4", "bkash.csv#L5")  # rent and salary only


@pytest.mark.parametrize(
    ("day", "expected"),
    [(date(2026, 8, 31), "0"), (date(2026, 9, 3), "1500.00"), (date(2026, 9, 30), "1500.00")],
    ids=["before-issue", "issue-day", "later"],
)
def test_outstanding_follows_the_issue_date(day, expected):
    assert outstanding_at(invoice(9, date(2026, 9, 3), 2000, paid=500), day) == Decimal(expected)


def test_settled_document_counts_in_full_before_its_paid_date():
    doc = invoice(9, date(2026, 8, 1), 700, paid=700, paid_date=date(2026, 9, 10))
    assert outstanding_at(doc, date(2026, 9, 9)) == Decimal("700.00")
    assert outstanding_at(doc, date(2026, 9, 10)) == Decimal("0.00")


# ---------------------------------------------------------------- registry rules


def test_every_default_metric_has_a_hand_checked_expectation():
    assert set(REGISTRY.metrics()) == set(EXPECTED_SEP)


def test_formula_ids_are_unique_and_expressions_present():
    definitions = [REGISTRY.get(m) for m in REGISTRY.metrics()]
    assert len({d.formula_id for d in definitions}) == len(definitions)
    assert all(d.expression.strip() for d in definitions)


@pytest.mark.parametrize("name", ["DSO", "dso ", "ds", "days_sales_outstanding"])
def test_registry_lookup_is_exact(name: str):
    with pytest.raises(UnknownMetric):
        REGISTRY.get(name)


def test_registry_returns_latest_version_and_pins_older_ones():
    reg = build_default_registry()
    v1 = reg.get("net_sales")
    v2 = reg.register(MetricDefinition(
        "net_sales", "sales.net_sales", 2, "cash_sales + credit_sales - 0", Unit.BDT,
        inputs=("cash_sales", "credit_sales"), from_inputs=lambda v, _p: v["cash_sales"]))
    assert reg.get("net_sales") is v2
    assert reg.get("net_sales", 1) is v1
    with pytest.raises(UnknownMetric):
        reg.get("net_sales", 3)


def test_registering_the_same_version_twice_is_refused():
    reg = build_default_registry()
    with pytest.raises(ValueError, match="already registered"):
        reg.register(REGISTRY.get("dso"))


def test_a_metric_cannot_change_its_formula_id():
    reg = build_default_registry()
    with pytest.raises(ValueError, match="already uses"):
        reg.register(MetricDefinition("dso", "receivables.dso_new", 2, "x", Unit.days,
                                      inputs=("receivables",), from_inputs=lambda v, _p: 0))


def test_a_formula_id_cannot_be_shared_by_two_metrics():
    reg = build_default_registry()
    with pytest.raises(ValueError, match="belongs to"):
        reg.register(MetricDefinition("dso_copy", "receivables.dso", 1, "x", Unit.days,
                                      inputs=("receivables",), from_inputs=lambda v, _p: 0))


def test_derived_metric_inputs_must_be_registered():
    reg = build_default_registry()
    with pytest.raises(ValueError, match="not registered"):
        reg.register(MetricDefinition("ebitda", "analysis.ebitda", 1, "x", Unit.BDT,
                                      inputs=("depreciation",), from_inputs=lambda v, _p: 0))


def test_a_definition_needs_exactly_one_compute_function():
    with pytest.raises(ValueError, match="exactly one"):
        MetricDefinition("x", "a.x", 1, "x", Unit.BDT)
