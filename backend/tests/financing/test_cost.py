from decimal import Decimal

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.contracts import Money
from app.engines.financing.cost import (
    CashFlow,
    CostError,
    early_pay_discount_cost,
    effective_annual_rate,
    true_cost,
)
from tests.financing.helpers import product

P = Money.of(100000)

# Effective annual rates (EAR) for Tk 1,00,000, each computed independently with float
# arithmetic (closed-form EMI + bisection) outside the engine.
TABLE = [
    ("reducing 12% / 12 months: (1.01)^12 - 1", dict(rate_type="reducing_balance", rate="12"),
     365, "12.68", "6618.55"),
    ("reducing 9% / 6 months", dict(rate_type="reducing_balance", rate="9"), 183, "9.38",
     "2641.34"),
    ("flat 12% / 12 months", dict(rate_type="flat", rate="12"), 365, "23.70", "12000.00"),
    ("flat 24% MFI style", dict(rate_type="flat", rate="24"), 365, "50.67", "24000.00"),
    ("daily debit 9% / 365 days", dict(rate_type="daily_debit", rate="9"), 365, "19.05",
     "9000.00"),
    ("discount 12% / 1 year: 100/88 - 1", dict(rate_type="discount", rate="12"), 365, "13.64",
     "12000.00"),
    ("discount 10% / 90 days", dict(rate_type="discount", rate="10"), 90, "10.66", "2465.75"),
    ("no interest, no fees", dict(rate_type="none", rate="0"), 30, "0.00", "0.00"),
    ("1% processing fee on 12% reducing", dict(rate_type="reducing_balance", rate="12",
     fees=[dict(name="processing", kind="percent_of_principal", value=Decimal(1))]), 365,
     "14.84", "7618.55"),
    ("Tk 500 fixed fee on 12% reducing", dict(rate_type="reducing_balance", rate="12",
     fees=[dict(name="stamp", kind="fixed", value=Decimal(500))]), 365, "13.75", "7118.55"),
    ("10% compulsory deposit on 24% flat", dict(rate_type="flat", rate="24",
     fees=[dict(name="deposit", kind="compulsory_deposit_percent", value=Decimal(10))]), 365,
     "62.90", "24000.00"),
    ("monthly service fee 0.1% on 12% reducing", dict(rate_type="reducing_balance", rate="12",
     fees=[dict(name="service", kind="percent_of_principal", value=Decimal("0.1"),
                timing="periodic")]), 365, "15.08", "7818.55"),
]


@pytest.mark.parametrize(("name", "spec", "tenor", "ear", "cost"), TABLE, ids=[t[0] for t in TABLE])
def test_effective_rate_matches_hand_calculation(name, spec, tenor, ear, cost):
    result = true_cost(product(**spec), P, tenor)
    assert result.effective_annual_rate == Decimal(ear)
    assert result.total_cost == Money.of(cost)


@pytest.mark.parametrize("rate", ["6", "12", "18", "30"])
def test_monthly_irr_agrees_with_numpy_polynomial_roots(rate):
    """Independent check: solve the EMI polynomial with numpy and annualise."""
    result = true_cost(product(rate_type="flat", rate=rate), P, 365)
    coeffs = [float(f.amount) for f in result.flows]  # cf0 + cf1 x + ... with x = 1/(1+m)
    roots = np.roots(coeffs[::-1])
    x = max(r.real for r in roots if abs(r.imag) < 1e-9 and 0 < r.real < 1)
    monthly = 1 / x - 1
    expected = (1 + monthly) ** 12 - 1
    assert abs(float(result.effective_annual_rate) / 100 - expected) < 0.0001


def test_net_proceeds_reflect_upfront_fees_and_deposit():
    spec = dict(rate_type="flat", rate="24", fees=[
        dict(name="processing", kind="percent_of_principal", value=Decimal(2)),
        dict(name="deposit", kind="compulsory_deposit_percent", value=Decimal(10))])
    assert true_cost(product(**spec), P, 365).net_proceeds == Money.of(88000)


def test_reducing_loan_has_one_instalment_per_month():
    assert len(true_cost(product(), P, 365).instalments) == 12
    assert len(true_cost(product(), P, 20).instalments) == 1  # short tenors round up to 1


@pytest.mark.parametrize(("principal", "tenor"), [(0, 30), (100, 0)])
def test_invalid_inputs_are_refused(principal, tenor):
    with pytest.raises(CostError):
        true_cost(product(), Money.of(principal), tenor)


def test_rate_solver_needs_money_both_ways():
    with pytest.raises(CostError):
        effective_annual_rate([CashFlow(Decimal(0), Decimal(10), "in")])


@pytest.mark.parametrize(("pct", "days", "expected"),
                         [("2", 20, "44.59"), ("1", 30, "13.01"), ("5", 60, "36.62")])
def test_early_pay_discount_annual_cost(pct, days, expected):
    assert early_pay_discount_cost(Decimal(pct), days) == Decimal(expected)


@pytest.mark.parametrize(("pct", "days"), [("0", 10), ("100", 10), ("2", 0)])
def test_early_pay_discount_rejects_nonsense(pct, days):
    with pytest.raises(CostError):
        early_pay_discount_cost(Decimal(pct), days)


rates = st.integers(1, 60).map(Decimal)


@pytest.mark.property
@settings(max_examples=30)  # each example solves several rates
@given(rates, rates, st.sampled_from(["reducing_balance", "flat", "daily_debit", "discount"]))
def test_higher_nominal_rate_never_costs_less(a, b, rate_type):
    low, high = sorted((a, b))
    ear_low = true_cost(product(rate_type=rate_type, rate=str(low)), P, 180).effective_annual_rate
    ear_high = true_cost(product(rate_type=rate_type, rate=str(high)), P, 180).effective_annual_rate
    assert ear_low <= ear_high


@pytest.mark.property
@settings(max_examples=30)  # each example solves several rates
@given(rates, st.integers(1, 5).map(Decimal))
def test_any_fee_raises_the_effective_rate(rate, fee):
    plain = true_cost(product(rate=str(rate)), P, 365).effective_annual_rate
    with_fee = true_cost(product(rate=str(rate), fees=[dict(
        name="f", kind="percent_of_principal", value=fee)]), P, 365).effective_annual_rate
    assert with_fee > plain


@pytest.mark.property
@settings(max_examples=30)  # each example solves several rates
@given(st.integers(2, 60).map(Decimal), st.integers(2, 36))
def test_flat_rate_always_costs_more_than_the_same_reducing_rate(rate, months):
    tenor = months * 30
    flat = true_cost(product(rate_type="flat", rate=str(rate)), P, tenor)
    reducing = true_cost(product(rate_type="reducing_balance", rate=str(rate)), P, tenor)
    assert flat.effective_annual_rate > reducing.effective_annual_rate


@pytest.mark.property
@settings(max_examples=30)  # each example solves several rates
@given(st.integers(1, 50).map(Decimal), st.integers(30, 720))
def test_the_solved_rate_zeroes_present_value(rate, tenor):
    from app.engines.financing.cost import present_value

    result = true_cost(product(rate_type="flat", rate=str(rate)), P, tenor)
    ear = result.effective_annual_rate / 100
    assert abs(present_value(result.flows, ear)) < Decimal(50)  # within rounding of 2 dp EAR
