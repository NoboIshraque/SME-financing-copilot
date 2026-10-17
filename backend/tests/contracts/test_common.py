from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from app.contracts import Currency, Money, Period, Tier
from app.contracts.common import quantize_money


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("10", Decimal("10.00")),
        ("10.005", Decimal("10.01")),  # half-up, not banker's rounding
        ("10.004", Decimal("10.00")),
        ("-3.335", Decimal("-3.34")),
        (1250, Decimal("1250.00")),
        (Decimal("0.1"), Decimal("0.10")),
        (" 42.5 ", Decimal("42.50")),
    ],
)
def test_money_is_quantized_to_two_places_half_up(raw, expected):
    assert Money.of(raw).amount == expected
    assert Money.of(raw).amount.as_tuple().exponent == -2


@pytest.mark.parametrize("bad", [10.5, True, "abc", "NaN", "Infinity", ""])
def test_money_rejects_floats_bools_and_non_numbers(bad):
    with pytest.raises(ValidationError):
        Money.of(bad)


def test_money_arithmetic_and_comparison():
    a, b = Money.of("100.10"), Money.of("0.90")
    assert (a + b).amount == Decimal("101.00")
    assert (a - b).amount == Decimal("99.20")
    assert (-a).amount == Decimal("-100.10")
    assert b < a and a >= b and a.scale(3).amount == Decimal("300.30")


def test_money_refuses_mixed_currencies_and_float_scaling():
    with pytest.raises(ValueError, match="currency mismatch"):
        Money.of(1) + Money.of(1, Currency.USD)
    with pytest.raises(ValueError):
        Money.of(1).scale(1.5)


@given(st.decimals(min_value=-10**9, max_value=10**9, places=2, allow_nan=False),
       st.decimals(min_value=-10**9, max_value=10**9, places=2, allow_nan=False))
def test_money_addition_is_exact_for_two_place_amounts(x, y):
    assert (Money.of(x) + Money.of(y)).amount == x + y


@given(st.decimals(min_value=-10**6, max_value=10**6, allow_nan=False, allow_infinity=False))
def test_quantize_never_moves_more_than_half_a_paisa(x):
    assert abs(quantize_money(x) - x) <= Decimal("0.005")


def test_money_is_immutable():
    money = Money.of(5)
    with pytest.raises(ValidationError):
        money.amount = Decimal(6)  # type: ignore[misc]


def test_period_rejects_end_before_start_and_counts_days():
    with pytest.raises(ValidationError, match="before start"):
        Period(start=date(2026, 9, 30), end=date(2026, 9, 1))
    september = Period(start=date(2026, 9, 1), end=date(2026, 9, 30))
    assert september.days == 30
    assert september.contains(date(2026, 9, 15)) and not september.contains(date(2026, 10, 1))


@pytest.mark.parametrize(
    ("tier", "needs_approval", "allowed"),
    [
        (Tier.READ, False, True),
        (Tier.SUGGEST, False, True),
        (Tier.DRAFT, False, True),
        (Tier.EXECUTE, True, True),
        (Tier.DENY, False, False),
    ],
)
def test_tier_semantics(tier, needs_approval, allowed):
    assert tier.needs_owner_approval is needs_approval
    assert tier.allowed is allowed
