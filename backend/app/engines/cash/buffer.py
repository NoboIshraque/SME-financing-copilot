"""Cash buffer target, surplus sweep and the forecast's headline figures (WP-04 m6; FEATURES Q1).

Buffer target: the cash cushion that covers the deepest dip in 19 of 20 simulated paths. A
path's dip is how far it falls below the likely (P50) balance at its worst; the target is the
95th percentile of those dips (nearest rank: the 950th of 1,000). Keeping the likely balance at
or above the target therefore keeps the business out of the red in 19 of 20 paths. It measures
uncertainty, not wealth: planned swings (salaries, owner draws) are already in the likely line,
and moving today's balance up or down leaves the target unchanged.

Surplus sweep: on day t, the amount that can be set aside for good with the balance staying at
or above the buffer for the rest of the horizon in 19 of 20 paths = the 5th percentile of the
lowest balance from day t to the end, minus the buffer, rounded down to Tk 1,000. Checked
weekly (days 1, 8, 15, ...) and only while at least 5 weeks of forecast remain, so the end of the
horizon never makes a sweep look safer than it is. The plan is cumulative: each week adds what
became safe since the last sweep; the first increment is offered as an EXECUTE card (money
moves only with the owner's approval). There is nothing to sweep while a gap is ahead.

Headline figures (the Today screen): runway = days until the likely (P50) balance first falls
below the buffer (the horizon when it never does), and the lowest likely balance.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import ROUND_FLOOR, Decimal
from zoneinfo import ZoneInfo

import numpy as np

from app.contracts import (
    ActionCard,
    ActionType,
    Figure,
    LeverKind,
    Money,
    SmoothingLever,
    Tier,
    Unit,
)
from app.engines.cash.figures import NO_EVIDENCE, Evidence, make_figure
from app.engines.cash.simulate import Simulation, from_paisa, rank, to_paisa

COVER_PERCENT = 95
SWEEP_PERCENT = 5
SWEEP_EVERY_DAYS = 7
SWEEP_LOOKAHEAD_DAYS = 35
SWEEP_STEP = Decimal(1000)
COVERAGE = "19 of 20 paths"
DHAKA = ZoneInfo("Asia/Dhaka")
ZERO = Decimal(0)


def deepest_dips(sim: Simulation) -> np.ndarray:
    """Per path, how far it falls below the likely (P50) balance at its worst, in paisa (0 for
    a path that never goes below the likely line)."""
    return np.maximum((sim.percentile(50)[None, :] - sim.balances).max(axis=1), 0)


def buffer_target(sim: Simulation) -> Decimal:
    dips = np.sort(deepest_dips(sim))
    return from_paisa(dips[rank(sim.paths, COVER_PERCENT) - 1])


def target_figure(sim: Simulation, evidence: Evidence = NO_EVIDENCE) -> Figure:
    return make_figure(sim, "cash.buffer_target", "cash.buffer_target", buffer_target(sim),
                       Unit.BDT, evidence, params={"coverage": COVERAGE,
                                                   "percentile": COVER_PERCENT})


# ---------------------------------------------------------------- surplus sweep


@dataclass(frozen=True)
class Sweep:
    day: date
    safe: Decimal  # total that can have been set aside by this day
    increment: Decimal  # what this day adds to the earlier sweeps


def sweep_plan(sim: Simulation, buffer: Decimal) -> tuple[Sweep, ...]:
    """Weekly sweeps that keep the balance at or above `buffer` in 19 of 20 paths."""
    horizon = sim.baseline.horizon
    floor = to_paisa(buffer)
    plan, swept = [], ZERO
    for t in range(1, horizon - SWEEP_LOOKAHEAD_DAYS + 2, SWEEP_EVERY_DAYS):
        lows = np.sort(sim.balances[:, t - 1:].min(axis=1))
        spare = from_paisa(max(int(lows[rank(sim.paths, SWEEP_PERCENT) - 1]) - floor, 0))
        safe = (spare / SWEEP_STEP).to_integral_value(rounding=ROUND_FLOOR) * SWEEP_STEP
        if safe > swept:
            plan.append(Sweep(sim.baseline.as_of + timedelta(days=t), safe, safe - swept))
            swept = safe
    return tuple(plan)


def sweep_lever(sim: Simulation, buffer: Decimal, evidence: Evidence = NO_EVIDENCE
                ) -> SmoothingLever | None:
    """The first sweep of the plan as an approval card, or None when nothing is spare."""
    plan = sweep_plan(sim, buffer)
    if not plan:
        return None
    first = plan[0]
    base = sim.baseline
    params = {"buffer": buffer, "sweep_day": first.day, "percentile": SWEEP_PERCENT,
              "coverage": COVERAGE}
    impact = make_figure(sim, "cash.sweepable_surplus", "action.surplus_sweep_amount",
                         first.increment, Unit.BDT, evidence, params=params)
    cost = make_figure(sim, "cash.lever_cost", "action.cost", ZERO, Unit.BDT, evidence,
                       params={"lever": "surplus_sweep"})
    key = f"{base.tenant_id}|{base.as_of}|sweep|{first.day}|{first.increment}"
    card = ActionCard(
        id="act_" + hashlib.sha256(key.encode()).hexdigest()[:20],
        title_key="action.surplus_sweep", action_type=ActionType.move_money, tier=Tier.EXECUTE,
        payload={"amount": str(first.increment), "on": first.day.isoformat(),
                 "to": "reserve", "buffer": str(buffer),
                 "plan": [{"on": s.day.isoformat(), "amount": str(s.increment)} for s in plan]},
        impact=impact, cost=cost,
        expires_at=datetime.combine(first.day + timedelta(days=1), time(0), DHAKA))
    return SmoothingLever(kind=LeverKind.surplus_sweep, gap_reduction=Money.zero(),
                          cost=Money.zero(), action=card)


# ---------------------------------------------------------------- headline figures


def runway_days(sim: Simulation, buffer: Decimal) -> int:
    below = np.nonzero(sim.percentile(50) < to_paisa(buffer))[0]
    return int(below[0]) + 1 if len(below) else sim.baseline.horizon


def headline_figures(sim: Simulation, buffer: Decimal, evidence: Evidence = NO_EVIDENCE
                     ) -> tuple[Figure, ...]:
    """Buffer target, runway and lowest likely balance (the closing balance comes from the fact
    ledger, WP-01)."""
    params = {"buffer": buffer}
    return (
        target_figure(sim, evidence),
        make_figure(sim, "cash.runway_days", "cash.runway_days",
                    Decimal(runway_days(sim, buffer)), Unit.days, evidence, params=params),
        make_figure(sim, "cash.forecast_p50_min", "cash.lowest_likely_balance",
                    from_paisa(sim.percentile(50).min()), Unit.BDT, evidence),
    )
