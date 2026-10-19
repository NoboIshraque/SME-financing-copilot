"""Expected vs reality (WP-07 milestone 3): snapshots, variances, accuracy, correction."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.contracts import (
    DataMode,
    Frequency,
    Granularity,
    Money,
    ObligationKind,
    Period,
    RecurringObligation,
    TxCategory,
)
from app.db import init_db, make_engine, session_factory
from app.engines.analysis import store
from app.engines.analysis.ledger import NotEnoughData
from app.engines.analysis.models import SnapshotImmutable, SnapshotRow
from app.engines.analysis.variance import (
    Snapshot,
    SnapshotKind,
    VarianceReport,
    compare,
    correction,
    due_dates,
    favourable,
    freeze,
    target_period,
)
from app.engines.cash.baseline import forecast_baseline
from app.engines.cash.calendar import load_festivals
from app.engines.cash.simulate import simulate
from tests.analysis.helpers import T, anchor, ledger, out, txn, universe_ledger

D = Decimal
C = TxCategory
NOW = datetime(2026, 3, 1, 18, 0, tzinfo=UTC)
SUNDAY = date(2026, 3, 1)
WEEK = Period(start=date(2026, 3, 2), end=date(2026, 3, 8), granularity=Granularity.week)
FESTIVALS = load_festivals()


def _rent():
    return RecurringObligation(id=f"{T}:OBL-rent", tenant_id=T, kind=ObligationKind.rent,
                               counterparty_token="PARTY_land000001", amount=Money.of(2000),
                               frequency=Frequency.monthly, day_of_period=5,
                               start_date=date(2026, 1, 1), source_ref="obligations.csv#L2",
                               data_mode=DataMode.synthetic)


def _history(days: int = 60):
    """A shop selling exactly 1,000 a day from 1 January, rent of 2,000 on the 5th."""
    sales = [txn(date(2026, 1, 1) + timedelta(days=n), 1000) for n in range(days)]
    rent = [out(date(2026, m, 5), 2000, C.rent) for m in (1, 2) if date(2026, m, 5) <
            date(2026, 1, 1) + timedelta(days=days)]
    return sales + rent


def _snapshot(**expected) -> Snapshot:
    lines = dict.fromkeys(("cash_sales", "collections", "other_inflows", "supplier_payments",
                           "fixed_costs", "other_costs", "transfers"), D(0))
    lines.update({k: D(v) for k, v in expected.items()})
    net = sum((lines[k] for k in ("cash_sales", "collections", "other_inflows")), D(0)) - \
        sum((lines[k] for k in ("supplier_payments", "fixed_costs", "other_costs")), D(0))
    return Snapshot(tenant_id=T, kind=SnapshotKind.weekly, as_of=SUNDAY, period=WEEK,
                    opening_balance=D(5000), expected={**lines, "net_cash_flow": net,
                                                       "closing_balance": D(5000) + net},
                    covered=("rent",), anchor_fact_id="fact_x", data_mode=DataMode.synthetic,
                    frozen_at=NOW, reconstructed=False)


def _week():
    """What happened in the week of 2-8 March."""
    return [txn(date(2026, 3, 2), 6000), txn(date(2026, 3, 3), 1500, C.collection),
            txn(date(2026, 3, 4), 100, C.owner_topup), out(date(2026, 3, 4), 3600,
                                                           C.supplier_payment),
            out(date(2026, 3, 5), 2000, C.rent), out(date(2026, 3, 8), 300, C.owner_draw)]


@pytest.fixture(scope="module")
def report() -> VarianceReport:
    snapshot = _snapshot(cash_sales=7000, collections=1000, supplier_payments=3000,
                         fixed_costs=2000, other_costs=500)
    return compare(snapshot, ledger(_week(), opening="5000", day=WEEK.start))


@pytest.mark.scenario
@pytest.mark.parametrize(("metric", "expected", "actual", "rank", "good"), [
    ("cash_sales", "7000", "6000", 1, False),  # sold 1,000 less: the biggest miss
    ("supplier_payments", "3000", "3600", 2, False),  # paid suppliers 600 more
    ("collections", "1000", "1500", 3, True),  # customers paid 500 more
    ("other_costs", "500", "300", 4, True),  # the owner drew 200 less
    ("other_inflows", "0", "100", 5, True),  # an owner top-up nobody forecast
    ("fixed_costs", "2000", "2000", 6, True),  # rent as agreed
    ("net_cash_flow", "2500", "1700", 7, False),  # totals come after the lines
    ("closing_balance", "7500", "6700", 8, False),
])
def test_variance_sign_and_rank(report, metric, expected, actual, rank, good):
    variance = report.get(metric)
    assert (variance.expected, variance.actual, variance.rank) == (D(expected), D(actual), rank)
    assert variance.difference == D(actual) - D(expected)
    assert favourable(metric, variance.difference) is good


def test_forecast_accuracy_by_hand(report):
    # |errors| 1,000 + 500 + 100 + 600 + 0 + 200 = 2,400 over |actuals| 13,500
    assert report.accuracy.value == D("82.2")
    assert report.accuracy.provenance.parameters["snapshot"] == report.snapshot.id
    assert report.accuracy.provenance.parameters["method"] == \
        "1 - weighted absolute percentage error"


def test_every_variance_has_an_expected_and_an_actual_figure(report):
    for variance in report.variances:
        expected, actual = report.figures[variance.metric]
        assert (expected.value, actual.value) == (variance.expected, variance.actual)
        assert f"snapshot:{report.snapshot.id}" in expected.provenance.source_row_ids
    closing = report.figures["closing_balance"][1].provenance
    assert closing.input_fact_ids == (anchor("5000", WEEK.start).id,)


def test_nothing_happening_gives_no_accuracy():
    quiet = ledger([txn(date(2026, 3, 9), 1)], opening="5000", day=WEEK.start)
    result = compare(_snapshot(cash_sales=7000), quiet)
    assert result.accuracy is None
    assert result.get("cash_sales").actual == 0


def test_a_week_that_is_not_over_cannot_be_checked():
    with pytest.raises(NotEnoughData, match="up to 2026-03-08"):
        compare(_snapshot(), ledger([txn(date(2026, 3, 7), 1)], day=WEEK.start))


def test_freeze_forecasts_the_next_week_from_the_shop_history():
    snap = freeze(ledger(_history(), obligations=[_rent()]), SnapshotKind.weekly, SUNDAY,
                  FESTIVALS, NOW, SUNDAY)
    assert snap.period == WEEK and not snap.reconstructed
    assert snap.expected["cash_sales"] == D("7000.00")
    assert snap.expected["fixed_costs"] == D("2000.00")  # rent on 5 March
    assert snap.covered == ("rent",)
    assert snap.opening_balance == D(10000) + 60 * D(1000) - 2 * D(2000)
    assert snap.expected["closing_balance"] == snap.opening_balance + \
        snap.expected["net_cash_flow"]


def test_freeze_never_sees_rows_after_its_day():
    shop = ledger(_history(), obligations=[_rent()])
    first = freeze(shop, SnapshotKind.weekly, SUNDAY, FESTIVALS, NOW, SUNDAY)
    later = replace(shop, transactions=(*shop.transactions, txn(date(2026, 3, 2), 99999),
                                        out(date(2026, 3, 3), 5000, C.salary)))
    assert freeze(later, SnapshotKind.weekly, SUNDAY, FESTIVALS, NOW, SUNDAY).id == first.id


def test_a_snapshot_frozen_after_its_week_began_is_marked_reconstructed():
    shop = ledger(_history())
    on_time = freeze(shop, SnapshotKind.weekly, SUNDAY, FESTIVALS, NOW, WEEK.start)
    late = freeze(shop, SnapshotKind.weekly, SUNDAY, FESTIVALS, NOW, date(2026, 3, 3))
    assert not on_time.reconstructed and late.reconstructed
    assert late.id == on_time.id  # the same forecast: only the flag tells them apart


def test_freeze_abstains_without_eight_weeks_or_up_to_date_rows():
    with pytest.raises(NotEnoughData, match="8 weeks"):
        freeze(ledger(_history(50)), SnapshotKind.weekly, date(2026, 2, 15), FESTIVALS, NOW,
               SUNDAY)
    with pytest.raises(NotEnoughData, match="up to 2026-03-01"):
        freeze(ledger(_history(59)), SnapshotKind.weekly, SUNDAY, FESTIVALS, NOW, SUNDAY)


def test_snapshots_are_frozen_on_the_last_day_of_their_period():
    assert target_period(SnapshotKind.quarterly, date(2026, 3, 31)) == Period(
        start=date(2026, 4, 1), end=date(2026, 6, 30), granularity=Granularity.quarter)
    with pytest.raises(ValueError, match="last day of a week"):
        target_period(SnapshotKind.weekly, date(2026, 3, 4))
    weekly = due_dates(SnapshotKind.weekly, date(2026, 1, 1), date(2026, 3, 18))
    assert weekly == [date(2026, 3, 1), date(2026, 3, 8), date(2026, 3, 15)]
    assert all(d.weekday() == 6 for d in weekly)
    assert due_dates(SnapshotKind.quarterly, date(2025, 4, 1), date(2026, 9, 30)) == [
        date(2025, 6, 30), date(2025, 9, 30), date(2025, 12, 31), date(2026, 3, 31),
        date(2026, 6, 30), date(2026, 9, 30)]


def test_a_tampered_payload_is_refused(report):
    payload = report.snapshot.payload()
    assert Snapshot.from_payload(json.loads(json.dumps(payload))) == report.snapshot
    payload["expected"]["cash_sales"] = "6000.00"  # make the forecast look better
    with pytest.raises(ValueError, match="does not match its content"):
        Snapshot.from_payload(payload)


@pytest.fixture
def session() -> Iterator[Session]:
    engine = make_engine("sqlite://")
    init_db(engine)
    with session_factory(engine)() as db:
        yield db
    engine.dispose()


def test_a_stored_snapshot_is_never_replaced(session):
    shop = ledger(_history(), obligations=[_rent()])
    first = store.keep(session, freeze(shop, SnapshotKind.weekly, SUNDAY, FESTIVALS, NOW,
                                       SUNDAY))
    # the ledger changes before the week (a late upload): a new freeze differs ...
    revised = replace(shop, transactions=(*shop.transactions, out(date(2026, 2, 28), 7000,
                                                                  C.purchase)))
    again = freeze(revised, SnapshotKind.weekly, SUNDAY, FESTIVALS, NOW, date(2026, 3, 9))
    assert again.id != first.id
    # ... but the week keeps the forecast that was frozen first
    assert store.keep(session, again) == first
    assert store.history(session, T, SnapshotKind.weekly) == [first]


def test_a_stored_snapshot_cannot_be_edited(session):
    snap = store.keep(session, _snapshot(cash_sales=7000))
    session.commit()
    row = session.query(SnapshotRow).one()
    row.payload = row.payload.replace("7000.00", "6000.00")
    with pytest.raises(SnapshotImmutable, match=snap.id):
        session.flush()


def _check(sales_expected, sales_actual, cost_expected=0, cost_actual=0) -> VarianceReport:
    snap = _snapshot(cash_sales=sales_expected, supplier_payments=cost_expected)
    actual = {**dict.fromkeys(snap.expected, D(0)), "cash_sales": D(sales_actual),
              "supplier_payments": D(cost_actual)}
    return VarianceReport(snapshot=snap, variances=(), accuracy=None, figures={},
                          actual=actual)


@pytest.mark.scenario
@pytest.mark.parametrize(("checks", "ratio", "percent"), [
    (2, "1.2", "6.67"),  # 2 / (2 + 4) of +20%
    (4, "1.2", "10.00"),  # half weight after 4 checks
    (12, "0.8", "-15.00"),  # 12 / 16 of -20%
    (6, "3.0", "50.00"),  # 0.6 x +200% is kept within +50%
])
def test_sales_correction_is_credibility_weighted(checks, ratio, percent):
    fix = correction([_check(1000, D(1000) * D(ratio)) for _ in range(checks)])
    assert fix.applied and fix.checks == checks
    assert fix.sales_change_pct == D(percent)
    assert fix.cost_change_pct == 0  # no cost evidence: no change


def test_one_check_is_not_enough_to_correct_the_forecast():
    fix = correction([_check(1000, 500)])
    assert not fix.applied and fix.sales_change_pct == 0 and fix.figures == ()


def test_the_correction_feeds_back_into_the_cash_forecast():
    fix = correction([_check(1000, 900, 400, 500) for _ in range(4)])
    assert (fix.sales_change_pct, fix.cost_change_pct) == (D("-5.00"), D("12.50"))
    shop = ledger(_history(), obligations=[_rent()])
    base = forecast_baseline(T, SUNDAY, D(66000), shop.transactions, (), (), shop.obligations,
                             FESTIVALS)
    plain = simulate(base, paths=50).percentile(50)[-1]
    corrected = simulate(base, paths=50, scenario=fix.scenario()).percentile(50)[-1]
    assert corrected < plain  # less sales expected: a lower likely balance


@pytest.mark.parametrize("sme_id", ["sme_grocery", "sme_garment"])
def test_weekly_checks_on_the_universe(universe, sme_id):
    shop = universe_ledger(universe, sme_id)
    sme = universe.smes[sme_id]
    sundays = due_dates(SnapshotKind.weekly, universe.start, shop.as_of)[-5:-1]
    reports = [compare(freeze(shop, SnapshotKind.weekly, d, FESTIVALS, NOW, d), shop)
               for d in sundays]
    for result in reports:
        assert result.get("closing_balance").actual == \
            sme.balance_on(result.period.end).amount
        assert [v.rank for v in result.variances] == list(range(1, len(result.variances) + 1))
        assert D(0) <= result.accuracy.value <= D(100)
    assert correction(reports).applied
