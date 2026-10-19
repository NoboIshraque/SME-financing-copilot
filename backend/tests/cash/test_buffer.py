from datetime import UTC, datetime
from decimal import Decimal

import numpy as np
import pytest

from app.contracts import ActionType, LeverKind, Tier, Unit
from app.engines.cash.baseline import forecast_baseline
from app.engines.cash.buffer import (
    buffer_target,
    deepest_dips,
    headline_figures,
    runway_days,
    sweep_lever,
    sweep_plan,
    target_figure,
)
from app.engines.cash.calendar import load_festivals
from app.engines.cash.figures import FORMULAS, Evidence
from app.engines.cash.simulate import BASE, Scenario, Simulation, draw, run
from tests.cash.helpers import AS_OF, T

D = Decimal
NOW = datetime(2026, 9, 30, 18, 0, tzinfo=UTC)


def _paths(rows):
    base = forecast_baseline(T, AS_OF, D(rows[0][0]), [], [], [], [], [], horizon=len(rows[0]))
    return Simulation(baseline=base, scenario=BASE, seed=0,
                      balances=np.array(rows, dtype=np.int64) * 100)


def _shop(universe, sme_id, opening_shift=0, seed=3):
    sme = universe.smes[sme_id]
    opening = sme.balance_on(universe.as_of).amount + opening_shift
    base = forecast_baseline(sme.id, universe.as_of, opening, sme.transactions, sme.invoices,
                             sme.bills, sme.obligations, load_festivals())
    draws = draw(base, seed)
    return run(base, draws), draws


# ---------------------------------------------------------------- buffer target


def test_a_dip_is_how_far_a_path_falls_below_the_likely_line_at_its_worst():
    sim = _paths([[100, 100, 100], [90, 80, 120], [110, 130, 70], [100, 90, 110],
                  [95, 120, 100]])  # the likely (P50) balance is 100 on every day
    assert list(deepest_dips(sim) // 100) == [0, 20, 30, 10, 5]
    assert buffer_target(sim) == D(30)  # 95th percentile of five dips: the deepest


@pytest.mark.parametrize("sme_id", ["sme_grocery", "sme_fabric", "sme_garment"])
def test_the_target_covers_the_dip_in_19_of_20_paths(universe, sme_id):
    sim, _draws = _shop(universe, sme_id)
    dips = deepest_dips(sim)
    target = int(buffer_target(sim) * 100)
    assert (dips > target).sum() <= 50 < (dips >= target).sum()


def test_a_likely_balance_kept_above_the_target_stays_out_of_the_red_in_19_of_20_paths(
        universe):
    sim, _draws = _shop(universe, "sme_hardware")
    target = int(buffer_target(sim) * 100)
    lift = target - int(sim.percentile(50).min())  # the likely line now never dips below it
    in_the_red = ((sim.balances + lift).min(axis=1) < 0).sum()
    assert in_the_red <= 50


def test_the_target_does_not_depend_on_todays_balance(universe):
    plain, _ = _shop(universe, "sme_pharmacy")
    richer, _ = _shop(universe, "sme_pharmacy", opening_shift=D(250000))
    assert buffer_target(plain) == buffer_target(richer) > 0


def test_the_target_figure_explains_its_coverage():
    sim = _paths([[100, 100, 100], [90, 80, 120], [110, 130, 70], [100, 90, 110],
                  [95, 120, 100]])
    figure = target_figure(sim, Evidence(("fact_open",)))
    assert (figure.label_key, figure.value, figure.unit) == ("cash.buffer_target", D(30),
                                                             Unit.BDT)
    assert figure.provenance.formula_id == "cash.buffer_target" in FORMULAS
    assert figure.provenance.parameters["coverage"] == "19 of 20 paths"
    assert figure.provenance.input_fact_ids == ("fact_open",)


# ---------------------------------------------------------------- surplus sweep


def test_a_sweep_keeps_the_fifth_lowest_of_100_paths_above_the_buffer():
    flat = [[10000] * 50] * 96
    dip = [[10000] * 29 + [2000] + [10000] * 20]
    four_dips = _paths(dip * 4 + flat)
    five_dips = _paths(dip * 5 + [[10000] * 50] * 95)
    (sweep,) = sweep_plan(four_dips, D(5000))
    assert (sweep.day.isoformat(), sweep.safe, sweep.increment) == ("2026-10-01", D(5000),
                                                                    D(5000))
    assert sweep_plan(five_dips, D(5000)) == ()  # 1 path in 20 would breach: nothing is spare


def test_the_sweep_plan_adds_what_became_safe_each_week():
    sim = _paths([[10000 + 1000 * day for day in range(1, 51)]] * 20)
    plan = sweep_plan(sim, D(5000))
    assert [(s.day.day, s.safe, s.increment) for s in plan] == [
        (1, D(6000), D(6000)), (8, D(13000), D(7000)), (15, D(20000), D(7000))]


def test_amounts_are_rounded_down_to_whole_thousands():
    (sweep,) = sweep_plan(_paths([[7999] * 40] * 20), D(5000))
    assert sweep.safe == D(2000)


def test_no_sweep_is_planned_in_the_last_five_weeks_of_the_horizon(universe):
    sim, _draws = _shop(universe, "sme_garment")
    plan = sweep_plan(sim, buffer_target(sim))
    assert plan and all((s.day - AS_OF).days <= 91 - 35 + 1 for s in plan)


def test_following_the_sweep_plan_keeps_the_buffer_in_19_of_20_paths(universe):
    sim, draws = _shop(universe, "sme_garment")
    target = buffer_target(sim)
    plan = sweep_plan(sim, target)
    swept = run(sim.baseline, draws, Scenario(name="sweep",
                                              flows=tuple((s.day, -s.increment) for s in plan)))
    first = (plan[0].day - AS_OF).days
    breached = (swept.balances[:, first - 1:].min(axis=1) < int(target * 100)).sum()
    assert 0 < sum(s.increment for s in plan) and breached <= 50


def test_the_first_sweep_is_an_approval_card_that_moves_money():
    sim = _paths([[10000 + 1000 * day for day in range(1, 51)]] * 20)
    lever = sweep_lever(sim, D(5000))
    assert lever.kind is LeverKind.surplus_sweep
    assert lever.gap_reduction.amount == 0 and lever.cost.amount == 0
    card = lever.action
    assert (card.action_type, card.tier) == (ActionType.move_money, Tier.EXECUTE)
    assert card.payload["amount"] == "6000" and card.payload["on"] == "2026-10-01"
    assert [p["amount"] for p in card.payload["plan"]] == ["6000", "7000", "7000"]
    assert card.impact.value == D(6000) and card.impact.provenance.formula_id == \
        "cash.sweepable_surplus"


def test_nothing_is_swept_while_a_gap_is_ahead():
    assert sweep_lever(_paths([[6000] * 20 + [4000] * 30] * 20), D(5000)) is None


# ---------------------------------------------------------------- headline figures


@pytest.mark.parametrize(("rows", "runway"),
                         [([[9000, 8000, 4000, 9000]] * 3, 3), ([[9000] * 4] * 3, 4)],
                         ids=["likely-balance-dips-on-day-3", "never-dips-gives-the-horizon"])
def test_runway_is_the_first_day_the_likely_balance_is_below_the_buffer(rows, runway):
    assert runway_days(_paths(rows), D(5000)) == runway


def test_headline_figures_are_the_ones_the_today_screen_reads():
    sim = _paths([[9000, 8000, 4000, 9000], [9500, 7000, 3000, 9000], [9900, 9000, 6000, 9000]])
    figures = {f.label_key: f for f in headline_figures(sim, D(5000))}
    assert set(figures) == {"cash.buffer_target", "cash.runway_days",
                            "cash.lowest_likely_balance"}
    assert figures["cash.runway_days"].value == 3 and figures["cash.runway_days"].unit is \
        Unit.days
    assert figures["cash.lowest_likely_balance"].value == D(4000)
    assert all(f.provenance.formula_id in FORMULAS for f in figures.values())
