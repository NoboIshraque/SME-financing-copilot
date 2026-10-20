"""Watchlist baseline and alert threshold (WP-09 milestone 2)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.contracts import DataMode, Money, PricePoint, PriceSource
from app.engines.market.tcb import Observation
from app.engines.market.watch import alerts, baseline, change_figure, watchlist

LATEST = date(2026, 10, 19)


def obs(price: str, days_before: int, commodity: str = "sugar") -> Observation:
    day = LATEST - timedelta(days=days_before)
    point = PricePoint(commodity=commodity, unit="kg", price=Money.of(price), market="Dhaka",
                       source=PriceSource.tcb, source_url="https://tcb.gov.bd/x",
                       observed_on=day, data_mode=DataMode.public)
    return Observation(point, f"tcb:{day}.xlsx#r1:today", day)


def series(latest: str, *earlier: tuple[str, int]) -> list[Observation]:
    return [*(obs(p, d) for p, d in sorted(earlier, key=lambda e: -e[1])), obs(latest, 0)]


def test_the_baseline_is_the_median_of_the_four_weeks_before_the_latest_point():
    found = baseline(series("130", ("100", 7), ("104", 14), ("90", 21), ("120", 28), ("500", 29)))
    assert found.basis == "median_4w"
    assert found.price.amount == Decimal("102.00")  # median of 100, 104, 90, 120; day 29 is out
    assert len(found.refs) == 4


def test_with_fewer_than_four_points_the_baseline_is_the_previous_point():
    found = baseline(series("130", ("100", 14), ("110", 7), ("90", 35)))
    assert (found.basis, found.price.amount) == ("previous", Decimal("110.00"))


def test_a_single_point_has_no_baseline_and_no_alert():
    rows = watchlist([obs("130", 0)], LATEST)
    assert rows[0].baseline is None and change_figure(rows[0]) is None and alerts(rows) == []


@pytest.mark.parametrize("latest, alerted", [
    ("105.00", False),  # exactly +5%: not past the threshold
    ("105.04", False),  # +5.04% shows as 5.0%: the shown figure decides
    ("105.06", True),
    ("95.00", False),   # exactly -5%
    ("94.94", True),
    ("100.00", False),
])
def test_alert_threshold_is_strictly_past_five_percent_as_shown(latest, alerted):
    rows = watchlist(series(latest, ("100", 3), ("100", 6), ("100", 9), ("100", 12)), LATEST)
    assert bool(alerts(rows)) is alerted


def test_the_alert_figure_carries_formula_baseline_and_every_source_row():
    rows = watchlist(series("117.50", ("105", 2), ("105", 4), ("105", 6), ("105", 8)), LATEST)
    [(row, figure)] = alerts(rows)
    assert figure.value == Decimal("11.9") and figure.unit.value == "percent"
    assert figure.provenance.formula_id == "market.change_vs_4w_median"
    assert figure.provenance.parameters["baseline"] == "105.00"
    assert len(figure.provenance.source_row_ids) == 5
    assert figure.data_mode is DataMode.public


def test_an_alert_on_the_previous_point_says_so_in_its_provenance():
    rows = watchlist(series("90", ("100", 7)), LATEST)
    [(_, figure)] = alerts(rows)
    assert figure.provenance.formula_id == "market.change_vs_previous"
    assert figure.provenance.parameters["baseline_basis"] == "previous"


def test_points_after_the_as_of_date_are_ignored():
    rows = watchlist(series("200", ("100", 7)), LATEST - timedelta(days=1))
    assert rows[0].latest.point.price.amount == Decimal("100.00")


def test_biggest_move_comes_first():
    data = [*series("120", ("100", 7)),
            obs("100", 7, "onion"), obs("70", 0, "onion")]
    assert [row.commodity for row, _ in alerts(watchlist(data, LATEST))] == ["onion", "sugar"]
