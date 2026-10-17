"""Repayment fit against the cash forecast (WP-06 milestone 4).

WP-04 publishes, per day, the P10/P50/P90 balance. We approximate each day's balance as
normal with mean P50 and spread (P90 - P10) / 2.5631 (the 10-90 range of a normal), add the
option's cumulative cash flows up to that day, and report the highest daily probability of
falling below the buffer. That is a lower bound on the chance of any breach and is labelled as
an approximation wherever it is shown.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from math import erf, sqrt

from app.contracts import ForecastBand
from app.engines.financing.cost import CostResult

Z_10_90 = Decimal("2.5631")  # P90 - P10 of a standard normal
FORMULA_ID = "financing.fit.max_daily_breach_probability"


def _normal_cdf(z: float) -> float:
    return 0.5 * (1 + erf(z / sqrt(2)))


def cumulative_by_day(cost: CostResult, start: date) -> dict[date, Decimal]:
    """Running sum of the option's cash flows, by calendar day (fractional days round half-up)."""
    running = Decimal(0)
    by_day: dict[date, Decimal] = {}
    for flow in sorted(cost.flows, key=lambda f: f.day):
        offset = int(flow.day.to_integral_value(rounding=ROUND_HALF_UP))
        running += flow.amount
        by_day[start + timedelta(days=offset)] = running
    return by_day


def breach_probability(cost: CostResult, start: date, band: ForecastBand) -> Decimal:
    steps = sorted(cumulative_by_day(cost, start).items())
    worst = 0.0
    for point in band.points:
        effect = Decimal(0)
        for day, total in steps:
            if day <= point.day:
                effect = total
        mean = point.p50.amount + effect
        spread = (point.p90.amount - point.p10.amount) / Z_10_90
        gap = band.buffer.amount - mean
        certain = 1.0 if gap > 0 else 0.0
        p = _normal_cdf(float(gap / spread)) if spread > 0 else certain
        worst = max(worst, p)
    return Decimal(str(round(worst, 4)))


def baseline_breach(band: ForecastBand) -> Decimal:
    """Breach probability with no new financing (for 'does this option help?')."""
    worst = max((p.p_below_buffer for p in band.points), default=Decimal(0))
    return worst
