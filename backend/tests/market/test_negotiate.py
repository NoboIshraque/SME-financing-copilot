"""Negotiation engine (WP-09 milestone 4, N19): walk-away, target, script with its numbers."""

from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.contracts import DataMode, Money, PricePoint, PriceSource
from app.engines.market.negotiate import plan


def point(mid: str, high: str | None = None) -> PricePoint:
    return PricePoint(commodity="rice_coarse", unit="kg", price=Money.of(mid),
                      low=Money.of(mid) if high else None,
                      high=Money.of(high) if high else None, market="Dhaka",
                      source=PriceSource.tcb, observed_on=date(2026, 10, 19),
                      data_mode=DataMode.public)


def make(offer="62", days=30, apr="10", mid="52.50", high="55", quantity="500"):
    return plan(market=point(mid, high), market_ref="tcb:x#r1:today", offer=Decimal(offer),
                quantity=Decimal(quantity), payment_days=days, apr_percent=Decimal(apr),
                apr_ref="financing:p1", data_mode=DataMode.synthetic)


def figures(result):
    return {f.provenance.formula_id: f.value for step in result.steps for f in step.figures}


def test_walk_away_adds_the_cost_of_waiting_for_the_money_to_the_cash_price():
    # 52.50 * (1 + 0.10 * 30 / 365) = 52.9315... -> rounded up to 52.94
    result = make(offer="50", days=30, apr="10")
    assert result.walk_away.value == Decimal("52.94")
    assert figures(result)["negotiation.credit_cost"] == Decimal("0.43")


def test_a_low_offer_gets_a_counter_halfway_up_to_the_market_ceiling():
    result = make(offer="50", days=30, apr="10")
    # ceiling 55 * (1 + 0.10 * 30 / 365) = 55.4520 -> 55.46; target = 52.94 + 0.5 * 2.52
    assert result.target.value == Decimal("54.20")
    assert figures(result)["negotiation.open"] == Decimal("55.46")


def test_a_good_offer_is_kept_as_the_target():
    result = make(offer="62", days=30, apr="10")
    assert result.target.value == Decimal("62.00")
    assert figures(result)["negotiation.open"] == Decimal("62.00")


def test_cash_on_delivery_has_no_credit_cost_and_no_discount_step():
    result = make(offer="50", days=0)
    assert result.walk_away.value == Decimal("52.50")
    assert [s.text_key for s in result.steps] == [
        "negotiation.step.open_high", "negotiation.step.trade_term", "negotiation.step.walk_away"]


def test_the_discount_for_paying_on_delivery_costs_less_per_month_than_the_loan():
    values = figures(make(days=45, apr="12"))
    assert values["negotiation.discount"] == Decimal("1.18")  # 0.8 * 12 * 45 / 365
    assert values["negotiation.discount_monthly_cost"] < values["negotiation.loan_monthly_cost"]
    assert values["negotiation.loan_monthly_cost"] == Decimal("1.00")


def test_every_figure_cites_the_market_price_and_the_loan_it_used():
    result = make()
    for step in result.steps:
        for fig in step.figures:
            assert fig.provenance.source_row_ids == ("tcb:x#r1:today", "financing:p1")
            assert fig.provenance.parameters["apr_percent"] == "10"
            assert fig.data_mode is DataMode.synthetic


@pytest.mark.parametrize("field, value", [("offer", "0"), ("quantity", "-1"), ("days", -1),
                                          ("apr", "-0.5")])
def test_impossible_inputs_are_refused(field, value):
    with pytest.raises(ValueError):
        make(**{field: value})


@given(mid=st.decimals("1", "100000", places=2), spread=st.decimals("0", "0.5", places=2),
       offer=st.decimals("0.01", "200000", places=2), days=st.integers(0, 180),
       apr=st.decimals("0", "60", places=2))
def test_never_recommends_terms_worse_than_walk_away(mid, spread, offer, days, apr):
    high = (mid * (1 + spread)).quantize(Decimal("0.01"))
    result = make(offer=str(offer), days=days, apr=str(apr), mid=str(mid), high=str(high))
    walk = result.walk_away.value
    assert result.target.value >= walk
    prices = [f.value for s in result.steps for f in s.figures
              if f.label_key in ("negotiation.price", "negotiation.walk_away")]
    assert all(price >= walk for price in prices)
    assert result.target.value >= offer  # never asks for less than the buyer already offers
