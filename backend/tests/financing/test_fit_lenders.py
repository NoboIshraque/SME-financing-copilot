from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.contracts import LicenceStatus, Money
from app.engines.financing.cost import true_cost
from app.engines.financing.fit import baseline_breach, breach_probability, cumulative_by_day
from app.engines.financing.lenders import (
    COLD_START_SCORE,
    LenderEvent,
    build_profile,
    lender_score,
)
from tests.financing.helpers import START, band, product

LOAN = true_cost(product(rate_type="reducing_balance", rate="12"), Money.of(100000), 120)


def test_cumulative_flows_start_with_the_cash_received():
    steps = cumulative_by_day(LOAN, START)
    assert steps[START] == LOAN.flows[0].amount
    assert list(steps.values())[-1] < 0  # repaid more than received by the end


def test_a_comfortable_forecast_has_almost_no_breach():
    assert breach_probability(LOAN, START, band(p50=500000, buffer=50000)) < Decimal("0.01")


def test_a_forecast_dip_below_buffer_shows_up_as_risk():
    # the loan itself adds ~Tk 74k of cash by day 40, so the dip must be deeper than that
    risky = band(p50=200000, buffer=150000, dip=(40, 50, 200000))
    assert breach_probability(LOAN, START, risky) > Decimal("0.9")


def test_cash_from_the_loan_lowers_the_risk_of_a_near_term_dip():
    tight = band(p50=200000, buffer=150000, dip=(3, 10, 80000))
    no_loan = breach_probability(
        true_cost(product(rate_type="none", rate="0"), Money.of(1), 1), START, tight)
    assert breach_probability(LOAN, START, tight) < no_loan


@pytest.mark.property
@given(st.integers(50000, 400000), st.integers(50000, 400000))
def test_breach_probability_rises_with_the_buffer(b1, b2):
    low, high = sorted((b1, b2))
    p_low = breach_probability(LOAN, START, band(buffer=low, days=30))
    p_high = breach_probability(LOAN, START, band(buffer=high, days=30))
    assert p_low <= p_high


def test_baseline_breach_is_the_worst_day_of_the_forecast():
    b = band(days=3)
    worst = b.points[1].model_copy(update={"p_below_buffer": Decimal("0.4")})
    b = b.model_copy(update={"points": (b.points[0], worst, b.points[2])})
    assert baseline_breach(b) == Decimal("0.4")


def events(n, hidden=0, disputed=0, gap="0"):
    return [LenderEvent("L", Decimal(10), Decimal(10) + Decimal(gap), 7, i < hidden,
                        i < disputed) for i in range(n)]


def profile(evts, licence=LicenceStatus.licensed):
    return build_profile("L", "Lender", licence, evts)


def test_profile_summarises_the_track_record():
    p = profile(events(4, hidden=1, disputed=2, gap="1.5"))
    assert (p.events_count, p.hidden_fee_incidents, p.disputes) == (4, 1, 2)
    assert p.quoted_vs_realised_apr_gap == Decimal("1.50")
    assert p.median_disbursal_days == Decimal(7)


def test_other_lenders_events_are_ignored():
    mixed = events(2) + [LenderEvent("other", Decimal(1), Decimal(9), 1, True, True)]
    assert profile(mixed).events_count == 2


def test_no_track_record_gets_the_cold_start_score():
    assert lender_score(profile([])) == COLD_START_SCORE


@pytest.mark.parametrize("licence", [LicenceStatus.not_found, LicenceStatus.revoked])
def test_unlicensed_lenders_score_zero_whatever_their_history(licence):
    assert lender_score(profile(events(10), licence)) == Decimal(0)


def test_unknown_licence_costs_points():
    assert lender_score(profile(events(5), LicenceStatus.unknown)) < lender_score(
        profile(events(5)))


@pytest.mark.property
@given(st.integers(1, 30), st.integers(0, 30), st.integers(0, 30))
def test_score_never_rises_with_more_hidden_fees(n, h1, h2):
    a, b = sorted((min(h1, n), min(h2, n)))
    assert lender_score(profile(events(n, hidden=a))) >= lender_score(profile(events(n, hidden=b)))


@pytest.mark.property
@given(st.integers(0, 20).map(Decimal), st.integers(0, 20).map(Decimal))
def test_score_never_rises_with_a_bigger_quoted_vs_realised_gap(g1, g2):
    a, b = sorted((g1, g2))
    assert lender_score(profile(events(5, gap=str(a)))) >= lender_score(
        profile(events(5, gap=str(b))))
