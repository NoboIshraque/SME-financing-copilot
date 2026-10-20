"""Vendor ranking by landed cost (WP-09 milestone 3)."""

import random
from datetime import date
from decimal import Decimal

import pytest

from app.contracts import Bill, DataMode, DocumentStatus, Money, VendorQuote
from app.engines.market.vendors import main_suppliers, on_time_rate, rank, synthetic_quotes

DAY = date(2026, 10, 20)


def bill(supplier: str, due: int, paid: int | None, n: int) -> Bill:
    return Bill(id=f"b{n}", tenant_id="t", counterparty_token=supplier, issue_date=date(2026, 9, 1),
                due_date=date(2026, 9, due), amount=Money.of("100"),
                amount_paid=Money.of("100") if paid else Money.zero(),
                status=DocumentStatus.paid if paid else DocumentStatus.open,
                paid_date=date(2026, 9, paid) if paid else None, source_ref="bills.csv#L1",
                data_mode=DataMode.synthetic)


def quote(token: str, price: str, delivery: str = "0", lead: int = 0,
          on_time: str | None = "1") -> VendorQuote:
    return VendorQuote(vendor_token=token, commodity="rice_coarse", unit="kg",
                       unit_price=Money.of(price), delivery_cost=Money.of(delivery),
                       lead_time_days=lead, on_time_rate=Decimal(on_time) if on_time else None,
                       quoted_on=DAY, data_mode=DataMode.synthetic)


def ranked(quotes, quantity="500", apr="10"):
    labels = {q.vendor_token: f"Supplier {q.vendor_token}" for q in quotes}
    return rank(quotes, labels, Decimal(quantity), Decimal(apr), "financing:p", DataMode.synthetic)


def test_on_time_share_counts_settled_bills_paid_by_their_due_date():
    bills = [bill("A", 10, 9, 1), bill("A", 10, 10, 2), bill("A", 10, 12, 3),
             bill("A", 10, None, 4), bill("B", 10, 15, 5)]
    assert on_time_rate(bills, "A") == Decimal("0.67")
    assert on_time_rate(bills, "B") == Decimal("0")
    assert on_time_rate(bills, "C") is None


def test_landed_cost_hand_case():
    # 56 + 400/500 + 56 * (2 + 0.1 * 3) * 10% / 365 + 56 * 0.1 * 5%
    [only] = ranked([quote("A", "56", delivery="400", lead=2, on_time="0.9")])
    parts = {f.label_key: f.value for f in only.breakdown}
    assert parts == {"market.unit_price": Decimal("56.00"),
                     "market.delivery_per_unit": Decimal("0.80"),
                     "market.delay_cost": Decimal("0.04"),
                     "market.reliability_penalty": Decimal("0.28")}
    assert only.landed_cost.value == Decimal("57.12") == sum(parts.values())


def test_a_cheaper_price_can_lose_to_delivery_and_unreliability():
    result = ranked([quote("cheap", "55.50", delivery="900", lead=3, on_time="0.5"),
                     quote("steady", "57.00")])
    assert [r.quote.vendor_token for r in result] == ["steady", "cheap"]
    assert [r.rank for r in result] == [1, 2]


def test_a_supplier_without_history_gets_no_penalty_and_says_so():
    [only] = ranked([quote("new", "50", on_time=None)])
    assert {f.label_key: f.value for f in only.breakdown}["market.reliability_penalty"] == 0
    assert only.landed_cost.provenance.parameters["on_time_rate"] == "no_history"


def test_ranking_is_stable_under_irrelevant_noise():
    base = [quote("A", "56", "400", 2, "0.9"), quote("B", "57"),
            quote("C", "55.5", "900", 3, "0.75"), quote("D", "56.2", "100", 1, "0.95")]
    expected = [r.quote.vendor_token for r in ranked(base)]
    rng = random.Random(7)
    for _ in range(20):
        noisy = [q.model_copy(update={"quoted_on": date(2026, 10, rng.randint(1, 20))})
                 for q in rng.sample(base, len(base))]
        assert [r.quote.vendor_token for r in ranked(noisy)] == expected


def test_equal_landed_costs_rank_by_label():
    assert [r.label for r in ranked([quote("b", "50"), quote("a", "50")])] == [
        "Supplier a", "Supplier b"]


def test_generated_quotes_are_synthetic_repeatable_and_near_the_market_price():
    bills = [bill("S1", 10, 9, 1), bill("S2", 10, 11, 2)]
    first = synthetic_quotes("t", ["S1", "S2"], "rice_coarse", "kg", Money.of("52.50"), bills, DAY)
    again = synthetic_quotes("t", ["S1", "S2"], "rice_coarse", "kg", Money.of("52.50"), bills, DAY)
    assert first == again
    for q in first:
        assert q.data_mode is DataMode.synthetic
        assert Decimal("49.35") <= q.unit_price.amount <= Decimal("54.60")  # -6% .. +4%
    assert [q.on_time_rate for q in first] == [Decimal("1.00"), Decimal("0.00")]


def test_main_suppliers_are_the_ones_with_most_bills():
    bills = [bill("A", 10, 9, i) for i in range(3)] + [bill("B", 10, 9, 9)] + \
        [bill("C", 10, 9, i + 20) for i in range(2)]
    assert main_suppliers(bills, limit=2) == ["A", "C"]


def test_quantity_must_be_positive():
    with pytest.raises(ValueError):
        ranked([quote("A", "50")], quantity="0")
