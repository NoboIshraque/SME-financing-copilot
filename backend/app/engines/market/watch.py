"""Watchlist and price alerts (WP-09 milestone 2): latest price vs its recent median.

The baseline is the median of the points in the 4 weeks before the latest one, when there are at
least 4 of them (`median_4w`). With fewer, the baseline is the previous point (`previous`), and
the alert's provenance says so; with no earlier point at all there is no baseline and no alert.
A move strictly past +/-5% of the baseline, as shown (rounded to 0.1%), is an alert.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from statistics import median

from app.contracts import Figure, Money, PricePoint, Provenance, Unit
from app.engines.market.tcb import Observation

WINDOW = timedelta(days=28)
MIN_POINTS = 4
THRESHOLD_PCT = Decimal("5")
HISTORY = timedelta(days=42)
HUNDRED = Decimal(100)

FORMULA_MEDIAN = "market.change_vs_4w_median"
FORMULA_PREVIOUS = "market.change_vs_previous"
EXPRESSIONS = {
    FORMULA_MEDIAN: "(latest - median of the points in the 4 weeks before it) / that median * 100",
    FORMULA_PREVIOUS: "(latest - previous point) / previous point * 100",
}


@dataclass(frozen=True)
class Baseline:
    price: Money
    basis: str  # "median_4w" or "previous"
    refs: tuple[str, ...]  # the observations it was computed from


@dataclass(frozen=True)
class Watch:
    commodity: str
    unit: str
    latest: Observation
    baseline: Baseline | None
    change_pct: Decimal | None
    history: tuple[PricePoint, ...]


def _pct(latest: Decimal, base: Decimal) -> Decimal:
    return ((latest - base) / base * HUNDRED).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def baseline(series: Sequence[Observation]) -> Baseline | None:
    """Baseline for the last observation of a date-sorted series of one commodity."""
    if len(series) < 2:
        return None
    latest = series[-1].point.observed_on
    window = [o for o in series[:-1] if latest - WINDOW <= o.point.observed_on < latest]
    if len(window) >= MIN_POINTS:
        mid = median(o.point.price.amount for o in window)
        return Baseline(Money.of(mid.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
                        "median_4w", tuple(o.ref for o in window))
    previous = series[-2]
    return Baseline(previous.point.price, "previous", (previous.ref,))


def watchlist(observations: Iterable[Observation], as_of: date) -> list[Watch]:
    """One row per commodity: its latest point on or before `as_of`, baseline and change."""
    by_commodity: dict[str, list[Observation]] = defaultdict(list)
    for obs in observations:
        if obs.point.observed_on <= as_of:
            by_commodity[obs.point.commodity].append(obs)
    rows = []
    for commodity in sorted(by_commodity):
        series = sorted(by_commodity[commodity], key=lambda o: o.point.observed_on)
        last = series[-1]
        base = baseline(series)
        change = _pct(last.point.price.amount, base.price.amount) if base else None
        start = last.point.observed_on - HISTORY
        history = tuple(o.point for o in series if o.point.observed_on >= start)
        rows.append(Watch(commodity, last.point.unit, last, base, change, history))
    return rows


def change_figure(watch: Watch) -> Figure | None:
    """The change as a Figure with provenance, or None when there is no baseline."""
    if watch.baseline is None or watch.change_pct is None:
        return None
    point = watch.latest.point
    formula = FORMULA_MEDIAN if watch.baseline.basis == "median_4w" else FORMULA_PREVIOUS
    return Figure(
        id=f"market:{point.commodity}:change:{point.observed_on.isoformat()}",
        label_key="market.change_vs_median" if formula == FORMULA_MEDIAN
        else "market.change_vs_previous",
        value=watch.change_pct, unit=Unit.percent, data_mode=point.data_mode,
        provenance=Provenance(
            formula_id=formula, formula_version=1,
            source_row_ids=(watch.latest.ref, *watch.baseline.refs),
            parameters={"latest": str(point.price.amount),
                        "baseline": str(watch.baseline.price.amount),
                        "baseline_basis": watch.baseline.basis,
                        "baseline_points": str(len(watch.baseline.refs)),
                        "threshold_pct": str(THRESHOLD_PCT),
                        "source": point.source.value,
                        "published_on": watch.latest.published_on.isoformat()}))


def alerts(rows: Iterable[Watch]) -> list[tuple[Watch, Figure]]:
    """Rows whose change is strictly past the threshold, biggest move first."""
    found = []
    for row in rows:
        figure = change_figure(row)
        if figure is not None and abs(figure.value) > THRESHOLD_PCT:
            found.append((row, figure))
    return sorted(found, key=lambda pair: (-abs(pair[1].value), pair[0].commodity))
