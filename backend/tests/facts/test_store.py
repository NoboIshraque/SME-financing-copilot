from datetime import date
from decimal import Decimal

import pytest

from app.contracts import FormulaRef, Granularity, Period, Provenance, TxCategory
from app.db import init_db, make_engine, session_factory
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


# ---------------------------------------------------------------- ledger revision


def test_ledger_revision_moves_only_when_the_ledger_or_a_raw_fact_changes(store: FactStore):
    rows = [txn(1, date(2026, 9, 2), 10), txn(2, date(2026, 9, 3), 20)]
    assert store.revision(T) == 0
    store.add_transactions(rows)
    assert store.revision(T) == 1
    store.add_transactions(rows)  # identical re-upload
    assert store.revision(T) == 1
    store.add_transactions([txn(1, date(2026, 9, 2), 11)])
    assert store.revision(T) == 2
    store.put_fact(raw_fact("initial_balance", "5.00"))
    assert store.revision(T) == 3
    computed = raw_fact("cash_in", "31.00", provenance=Provenance(
        formula_id="cash.cash_in", formula_version=1, source_row_ids=("txn:x",)))
    store.put_fact(computed)
    assert store.revision(T) == 3
    assert store.revision("tenant_b") == 0


def test_bulk_upsert_handles_more_rows_than_one_query_chunk(store: FactStore):
    rows = [txn(n, date(2026, 9, 1 + n % 28), n + 1) for n in range(1000)]
    store.add_transactions(rows)
    store.add_transactions([rows[999].model_copy(update={"amount": rows[0].amount})])
    stored = store.transactions(T)
    assert len(stored) == 1000
    assert {t.id: t.amount.amount for t in stored}[rows[999].id] == Decimal("1.00")


# ---------------------------------------------------------------- concurrent writers


def test_concurrent_insert_of_the_same_fact_is_absorbed(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'race.db'}")
    init_db(engine)
    factory = session_factory(engine)
    fact = raw_fact("net_sales", "1000.00")
    with factory() as first, factory() as second:
        FactStore(first).put_fact(fact)
        first.commit()
        late = FactStore(second)
        real_read, reads = late._fact_payload, []

        def stale_first_read(fact_id):  # it checked before the first writer committed
            reads.append(fact_id)
            return None if len(reads) == 1 else real_read(fact_id)

        late._fact_payload = stale_first_read
        assert late.put_fact(fact) == fact
        assert len(reads) == 2  # the insert lost the race and re-read the stored row
        second.commit()
    with factory() as check:
        assert FactStore(check).facts(T, "net_sales") == [fact]
    engine.dispose()


def test_concurrent_insert_of_the_same_formula_is_absorbed(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'race.db'}")
    init_db(engine)
    factory = session_factory(engine)
    formula = FormulaRef(formula_id="cash.cash_in", version=1, expression="sum")
    with factory() as first, factory() as second:
        FactStore(first).put_formula(formula)
        first.commit()
        real_get = second.get
        calls = []

        def stale_get(*args, **kwargs):
            calls.append(1)
            return None if len(calls) == 1 else real_get(*args, **kwargs)

        second.get = stale_get
        assert FactStore(second).put_formula(formula) == formula
        with pytest.raises(LedgerConflict):
            FactStore(second).put_formula(formula.model_copy(update={"expression": "other"}))
    engine.dispose()


# ---------------------------------------------------------------- tenant scope, latest values


def test_lookups_by_id_can_be_scoped_to_a_tenant(store: FactStore):
    fact = store.put_fact(raw_fact("net_sales", "1000.00"))
    assert store.get_fact(fact.id, tenant_id=T) == fact
    with pytest.raises(FactNotFound):
        store.get_fact(fact.id, tenant_id="tenant_b")


def test_latest_value_known_on_a_day(store: FactStore):
    store.put_fact(raw_fact("staff_count", "3", period=month(2026, 7)))
    store.put_fact(raw_fact("staff_count", "4", period=month(2026, 8)))
    assert store.latest(T, "staff_count", date(2026, 8, 31)).value == Decimal("4")
    assert store.latest(T, "staff_count", date(2026, 8, 30)).value == Decimal("3")
    assert store.latest(T, "staff_count", date(2026, 6, 30)) is None


def test_profile_facts_are_seeded_and_unknown_ones_abstain(store: FactStore, universe):
    sme = universe.smes["sme_grocery"]
    load_sme_into(store, sme, universe.start, universe.as_of)
    snapshot = store.snapshot("sme_grocery", ["business_age_months", "trade_licence",
                                              "etin_registered", "owner_is_woman"],
                              universe.as_of)
    assert snapshot == {"business_age_months": Decimal("74"), "trade_licence": Decimal("1"),
                        "etin_registered": Decimal("1"), "owner_is_woman": None}
    fact = store.latest("sme_grocery", "trade_licence", universe.as_of)
    assert (fact.source_refs, fact.data_mode.value) == (("profile.json#trade_licence",),
                                                        "synthetic")


def test_seeding_twice_changes_nothing(store: FactStore, universe):
    sme = universe.smes["sme_garment"]
    load_sme_into(store, sme, universe.start, universe.as_of)
    revision = store.revision("sme_garment")
    load_sme_into(store, sme, universe.start, universe.as_of)
    assert store.revision("sme_garment") == revision
