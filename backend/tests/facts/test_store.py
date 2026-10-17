from datetime import date
from decimal import Decimal

import pytest

from app.contracts import Granularity, Period, Provenance, TxCategory
from app.facts import FactNotFound, FactStore, LedgerConflict
from app.facts.seed import INITIAL_BALANCE, load_sme_into
from tests.facts.helpers import SEP, T, bill, invoice, month, raw_fact, txn

# ---------------------------------------------------------------- ledger records


def test_transactions_round_trip_exactly(store: FactStore):
    original = [txn(1, date(2026, 9, 2), "1250.50"), txn(2, date(2026, 9, 1), 99, "outflow",
                                                         TxCategory.rent)]
    assert store.add_transactions(original) == 2
    assert store.transactions(T) == [original[1], original[0]]  # oldest first


def test_transactions_are_filtered_by_inclusive_day_range(store: FactStore):
    store.add_transactions([txn(1, date(2026, 8, 31), 1), txn(2, date(2026, 9, 1), 2),
                            txn(3, date(2026, 9, 30), 3), txn(4, date(2026, 10, 1), 4)])
    got = store.transactions(T, SEP.start, SEP.end)
    assert [t.id for t in got] == [f"{T}-T2", f"{T}-T3"]


def test_transactions_are_scoped_to_their_tenant(store: FactStore):
    store.add_transactions([txn(1, date(2026, 9, 2), 10), txn(1, date(2026, 9, 2), 20,
                                                             tenant="tenant_b")])
    assert [t.amount.amount for t in store.transactions(T)] == [Decimal("10.00")]


def test_re_adding_a_transaction_replaces_it_instead_of_duplicating(store: FactStore):
    store.add_transactions([txn(1, date(2026, 9, 2), 10)])
    store.add_transactions([txn(1, date(2026, 9, 2), 15)])
    assert [t.amount.amount for t in store.transactions(T)] == [Decimal("15.00")]


def test_invoices_and_bills_are_kept_apart_and_filtered_by_issue_date(store: FactStore):
    store.add_invoices([invoice(1, date(2026, 9, 1), 500), invoice(2, date(2026, 10, 2), 70)])
    store.add_bills([bill(1, date(2026, 9, 3), 300)])
    assert [i.id for i in store.invoices(T, issued_by=SEP.end)] == [f"{T}:INV-1"]
    assert [b.id for b in store.bills(T)] == [f"{T}:BIL-1"]


def test_synthetic_sme_loads_with_its_initial_balance(store: FactStore, universe):
    sme = universe.smes["sme_grocery"]
    initial = load_sme_into(store, sme, universe.start)
    assert len(store.transactions("sme_grocery")) == len(sme.transactions)
    assert len(store.obligations("sme_grocery")) == len(sme.obligations)
    assert initial.value == sme.opening_total.amount
    assert initial.data_mode.value == "synthetic"
    day = Period(start=universe.start, end=universe.start, granularity=Granularity.day)
    assert store.get("sme_grocery", INITIAL_BALANCE, day) == initial


# ---------------------------------------------------------------- exact lookup


def test_get_returns_the_stored_fact(store: FactStore):
    fact = store.put_fact(raw_fact("net_sales", "1000.00"))
    assert store.get(T, "net_sales", SEP) == fact


@pytest.mark.parametrize(
    "metric",
    ["Net_sales", "net_sales ", " net_sales", "net_sale", "net_sales_2", "netsales"],
    ids=["case", "trailing-space", "leading-space", "prefix", "suffix", "no-underscore"],
)
def test_lookup_never_returns_a_near_miss_metric(store: FactStore, metric: str):
    store.put_fact(raw_fact("net_sales", "1000.00"))
    with pytest.raises(FactNotFound):
        store.get(T, metric, SEP)


@pytest.mark.parametrize(
    "period",
    [
        Period(start=date(2026, 9, 1), end=date(2026, 9, 29)),
        Period(start=date(2026, 9, 2), end=date(2026, 9, 30)),
        Period(start=date(2026, 9, 1), end=date(2026, 9, 30), granularity=Granularity.day),
        month(2026, 8),
    ],
    ids=["end-one-day-short", "start-one-day-late", "other-granularity", "previous-month"],
)
def test_lookup_never_returns_a_near_miss_period(store: FactStore, period: Period):
    store.put_fact(raw_fact("net_sales", "1000.00"))
    with pytest.raises(FactNotFound):
        store.get(T, "net_sales", period)


def test_lookup_distinguishes_entities_and_the_no_entity_fact(store: FactStore):
    total = store.put_fact(raw_fact("receivables", "900.00"))
    one = store.put_fact(raw_fact("receivables", "300.00", entity="PARTY_aaaaaaaaaa"))
    assert store.get(T, "receivables", SEP) == total
    assert store.get(T, "receivables", SEP, "PARTY_aaaaaaaaaa") == one
    with pytest.raises(FactNotFound):
        store.get(T, "receivables", SEP, "PARTY_AAAAAAAAAA")


def test_lookup_never_crosses_tenants(store: FactStore):
    store.put_fact(raw_fact("net_sales", "1000.00", tenant="tenant_b"))
    with pytest.raises(FactNotFound):
        store.get(T, "net_sales", SEP)


def test_empty_entity_token_is_refused_rather_than_matching_the_total(store: FactStore):
    store.put_fact(raw_fact("receivables", "900.00"))
    with pytest.raises(ValueError, match="entity_token"):
        store.get(T, "receivables", SEP, "")


def test_lookup_prefers_the_highest_formula_version_and_can_pin_one(store: FactStore):
    def prov(version: int) -> Provenance:
        return Provenance(formula_id="sales.net_sales", formula_version=version,
                          source_row_ids=("src.csv#L1",))

    v1 = store.put_fact(raw_fact("net_sales", "1000.00", provenance=prov(1)))
    v2 = store.put_fact(raw_fact("net_sales", "1100.00", provenance=prov(2)))
    assert store.get(T, "net_sales", SEP) == v2
    assert store.get(T, "net_sales", SEP, version=1) == v1


# ---------------------------------------------------------------- immutability


def test_putting_the_same_fact_twice_is_idempotent(store: FactStore):
    fact = raw_fact("net_sales", "1000.00")
    store.put_fact(fact)
    store.put_fact(fact)
    assert store.facts(T, "net_sales") == [fact]


def test_a_fact_id_cannot_be_reused_for_different_content(store: FactStore):
    fact = store.put_fact(raw_fact("net_sales", "1000.00"))
    with pytest.raises(LedgerConflict):
        store.put_fact(fact.model_copy(update={"value": Decimal("1.00")}))
    assert store.get_fact(fact.id).value == Decimal("1000.00")


def test_decimal_values_survive_storage_exactly(store: FactStore):
    fact = store.put_fact(raw_fact("dso", "0.1000000000000000055511151231257827"))
    assert store.get_fact(fact.id).value == Decimal("0.1000000000000000055511151231257827")
