"""Scenarios (WP-07 milestone 4): decisions compared under uncertainty."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

import pytest

from app.contracts import (
    DataMode,
    FinancingProduct,
    Frequency,
    Money,
    ObligationKind,
    ProductKind,
    RateBasis,
    RateType,
    RecurringObligation,
)
from app.engines.analysis.ledger import NotEnoughData
from app.engines.analysis.scenarios import (
    Assumptions,
    Shift,
    choose,
    compare_decisions,
    macro_states,
    prepare,
)
from app.engines.cash.calendar import load_festivals
from app.engines.financing.catalogue import load_catalogue
from tests.analysis.helpers import T, invoice, ledger, out, txn, universe_ledger

D = Decimal
NOW = datetime(2026, 3, 1, 18, 0, tzinfo=UTC)
FESTIVALS = load_festivals()
CALM = Assumptions(sales_sd_pct=D(0), input_price_sd_pct=D(0), delay_days=(0,),
                   delay_weights_pct=(100,), rate_pp_max=D(0), shock_probability_pct=D(0))
LOAN = FinancingProduct(id="test-wc", provider="Test Bank", name="Working capital",
                        kind=ProductKind.working_capital, rate_type=RateType.reducing_balance,
                        nominal_rate_pa=D(12), rate_basis=RateBasis.modelled, is_modelled=True,
                        data_mode=DataMode.synthetic)
NANO = LOAN.model_copy(update={"id": "test-nano", "kind": ProductKind.nano_loan})  # pays today


def _rent():
    return RecurringObligation(id=f"{T}:OBL-rent", tenant_id=T, kind=ObligationKind.rent,
                               counterparty_token="PARTY_land000001", amount=Money.of(2000),
                               frequency=Frequency.monthly, day_of_period=5,
                               start_date=date(2026, 1, 1), source_ref="obligations.csv#L2",
                               data_mode=DataMode.synthetic)


def _shop(extra=(), invoices=()):
    """Sales of exactly 1,000 every day from 1 January to 1 March, rent 2,000 on the 5th:
    a world without noise, so every path is the same and outcomes can be worked by hand."""
    sales = [txn(date(2026, 1, 1) + timedelta(days=n), 1000) for n in range(60)]
    rent = [out(date(2026, m, 5), 2000, "rent") for m in (1, 2)]
    return ledger([*sales, *rent, *extra], invoices, obligations=[_rent()])


def _inputs(shop=None, buffer="0", seed=20261020, **kw):
    return prepare(shop or _shop(), FESTIVALS, D(buffer), NOW, seed, **kw)


# opening on 2 March: 10,000 + 60 x 1,000 - 2 x 2,000 = 66,000. The 91 days to 31 May bring
# 91 x 1,000 of sales and rent on 5 March, 5 April and 5 May: 66,000 + 91,000 - 6,000.
QUIET_END = D("151000.00")


def test_a_calm_world_by_hand():
    result = compare_decisions(_inputs(), ["do_nothing"], CALM)
    scenario = result.outcome("do_nothing").scenario
    assert scenario.expected_outcome.amount == QUIET_END
    assert scenario.worst_5pct_outcome.amount == QUIET_END
    assert scenario.p_buffer_breach == 0
    assert (scenario.paths, scenario.seed) == (1000, 20261020)
    assert scenario.id == "sc_do_nothing" and scenario.name_key == "decision.do_nothing"


@pytest.mark.scenario
@pytest.mark.parametrize(("shift", "assumptions", "end"), [
    (Shift(name="sales_minus_10", sales_change_pct=D(-10)), CALM, "141900.00"),  # 91 x 900
    (Shift(name="bill", flows=((date(2026, 3, 9), D(-4000)),)), CALM, "147000.00"),
    (Shift(), replace(CALM, shock_probability_pct=D(100)), "150000.00"),  # half a month's rent
])
def test_shifts_and_shocks_by_hand(shift, assumptions, end):
    result = compare_decisions(_inputs(), ["do_nothing"], assumptions, shift)
    assert result.outcome("do_nothing").scenario.expected_outcome.amount == D(end)


def test_the_same_seed_gives_the_same_comparison(universe):
    shop = universe_ledger(universe, "sme_grocery")
    first = compare_decisions(_inputs(shop, buffer="300000"))
    again = compare_decisions(_inputs(shop, buffer="300000"))
    assert first.scenarios == again.scenarios
    assert [f.id for o in first.outcomes for f in o.figures] == \
        [f.id for o in again.outcomes for f in o.figures]
    other = compare_decisions(_inputs(shop, buffer="300000", seed=7))
    plain, moved = (c.outcome("do_nothing").scenario for c in (first, other))
    assert moved.expected_outcome != plain.expected_outcome
    assert {s.seed for s in other.scenarios} == {7}


def test_moving_cash_inside_the_horizon_changes_no_outcome():
    """Common random numbers: delaying purchases a week changes when cash leaves, not how much
    by the end, on exactly the same paths."""
    shop = _shop([out(date(2026, 2, 1) + timedelta(days=n), 300, "purchase") for n in range(28)])
    result = compare_decisions(_inputs(shop), ["do_nothing", "delay_purchase"])
    plain, delayed = (result.outcome(n).scenario for n in ("do_nothing", "delay_purchase"))
    assert delayed.expected_outcome == plain.expected_outcome
    assert delayed.worst_5pct_outcome == plain.worst_5pct_outcome


def test_a_loan_costs_its_interest_and_reduces_the_breach_risk():
    # buffer 80,000: the quiet shop starts at 66,000, so it is short until mid-March
    result = compare_decisions(_inputs(buffer="80000", products=[NANO]),
                               ["do_nothing", "take_loan"], CALM)
    loan, plain = result.outcome("take_loan"), result.outcome("do_nothing")
    assert loan.scenario.assumptions["loan_amount"] == D(13000)  # 80,000 - 67,000 on 2 March
    # outcome nets the instalment due after the horizon: exactly the interest is lost
    assert loan.scenario.expected_outcome.amount == \
        plain.scenario.expected_outcome.amount - loan.decision.cost
    assert loan.decision.cost > 0
    assert plain.scenario.p_buffer_breach == 1 > loan.scenario.p_buffer_breach
    assert result.choice == "take_loan"
    assert result.reason_keys[0] == "scenario.reason.lowest_breach_risk"


def test_higher_rates_make_the_loan_dearer():
    inputs = _inputs(buffer="80000", products=[NANO])
    calm = compare_decisions(inputs, ["take_loan"], CALM).outcome("take_loan")
    dearer = compare_decisions(inputs, ["take_loan"], CALM,
                               Shift(name="rates_plus_2pp", rate_pp=D(2))).outcome("take_loan")
    assert dearer.scenario.expected_outcome < calm.scenario.expected_outcome


def test_an_early_payment_discount_costs_two_percent():
    paid = invoice("I-0", date(2026, 1, 1), date(2026, 1, 15), 5000, paid=5000,
                   paid_date=date(2026, 1, 20))  # customers pay 5 days late
    shop = _shop(invoices=[paid, invoice("I-1", date(2026, 2, 20), date(2026, 3, 10), 8000)])
    result = compare_decisions(_inputs(shop), ["offer_discount"], CALM)
    discount = result.outcome("offer_discount")
    assert discount.decision.cost == D("160.00")
    assert discount.decision.details["invoice_id"] == f"{T}:I-1"
    assert discount.figures[4].value == D("160.00")


@pytest.mark.scenario
@pytest.mark.parametrize(("names", "kwargs", "skipped"), [
    (["take_loan"], {"products": [LOAN]}, "scenario.skip.no_shortfall"),  # buffer 0
    (["take_loan"], {"buffer": "80000"}, "scenario.skip.no_catalogue"),
    (["offer_discount"], {}, "scenario.skip.no_open_invoice"),
    (["retime_supplier"], {}, "scenario.skip.no_early_bills"),
    (["delay_purchase"], {}, "scenario.skip.no_purchases"),
    (["net_via_mesh"], {}, "scenario.skip.no_mesh"),
])
def test_a_decision_that_does_not_apply_is_skipped(names, kwargs, skipped):
    result = compare_decisions(_inputs(**kwargs), ["do_nothing", *names], CALM)
    assert result.skipped == ((names[0], skipped),)
    assert [o.decision.name for o in result.outcomes] == ["do_nothing"]


def test_nothing_to_compare_or_an_unknown_decision():
    with pytest.raises(NotEnoughData, match="offer_discount"):
        compare_decisions(_inputs(), ["offer_discount"], CALM)
    with pytest.raises(ValueError, match="unknown decisions"):
        compare_decisions(_inputs(), ["buy_lottery_ticket"], CALM)


@pytest.mark.scenario
@pytest.mark.parametrize(("rows", "best", "reason"), [
    # (P(breach), risk-adjusted outcome, cost) per decision, in menu order
    ([("0.30", 900, 0), ("0.10", 800, 50)], 1, "lowest_breach_risk"),  # safety first
    ([("0.13", 900, 0), ("0.10", 800, 50)], 0, "breach_risk_within_tolerance"),  # 3 points
    ([("0.10", 900, 0), ("0.10", 900, 20)], 0, "lowest_breach_risk"),  # cheaper wins a tie
    ([("0.10", 900, 5), ("0.10", 900, 5)], 0, "lowest_breach_risk"),  # then menu order
])
def test_the_risk_adjusted_choice(rows, best, reason):
    index, reasons = choose([(D(p), D(r), D(c)) for p, r, c in rows])
    assert index == best
    assert reasons == (f"scenario.reason.{reason}", "scenario.reason.best_risk_adjusted_outcome")


def test_latin_hypercube_states_hit_their_shares_exactly():
    states = macro_states(_inputs(), Assumptions())
    assert Counter(s.delay_days for s in states) == {0: 28, 7: 8, 14: 4}
    assert sum(1 for s in states if s.shock_day is not None) == 4  # 10% of 40
    assert sum(s.sales_change_pct for s in states) == 0  # symmetric strata around no change
    assert all(D(0) <= s.rate_pp <= D(2) for s in states)
    assert {s.shock_amount for s in states if s.shock_day} == {D("1000.00")}
    assert macro_states(_inputs(), Assumptions()) == states
    assert macro_states(_inputs(seed=8), Assumptions()) != states


def test_every_number_is_a_figure_with_its_parameters():
    result = compare_decisions(_inputs(buffer="80000", products=[LOAN]))
    for outcome in result.outcomes:
        expected, worst, breach, risk, cost = outcome.figures
        s = outcome.scenario
        assert (expected.value, worst.value, breach.value) == (
            s.expected_outcome.amount, s.worst_5pct_outcome.amount, s.p_buffer_breach)
        assert risk.value == outcome.risk_adjusted == \
            ((expected.value + worst.value) / 2).quantize(D("0.01"), ROUND_HALF_UP)
        assert cost.value == outcome.decision.cost
        params = expected.provenance.parameters
        assert params["decision"] == outcome.decision.name and params["seed"] == "20261020"
        assert expected.provenance.input_fact_ids == (result.outcomes[0].figures[0]
                                                      .provenance.input_fact_ids)
        assert s.worst_5pct_outcome <= s.expected_outcome


def test_netting_through_the_mesh_on_the_universe(universe):
    shop = universe_ledger(universe, "sme_garment")
    inputs = prepare(shop, FESTIVALS, D(1420241), NOW, products=load_catalogue(),
                     mesh=universe.mesh_obligations)
    result = compare_decisions(inputs, ["do_nothing", "net_via_mesh"])
    netted, plain = result.outcome("net_via_mesh"), result.outcome("do_nothing")
    assert netted.decision.details["round_id"]
    assert netted.scenario.p_buffer_breach < plain.scenario.p_buffer_breach
    assert netted.scenario.expected_outcome == plain.scenario.expected_outcome  # nets, no cost
