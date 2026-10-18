from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import numpy as np
import pytest

from app.contracts import (
    ActionCard,
    ActionType,
    Alert,
    AlertTier,
    CashGap,
    DataMode,
    DriverKind,
    GapDriver,
    LeadingIndicator,
    Money,
    Tier,
)
from app.engines.cash.alerts import (
    CHANNELS,
    SentAlert,
    build_alerts,
    deliver,
    tier_gap,
)
from app.engines.cash.baseline import forecast_baseline
from app.engines.cash.gaps import Gap, Signal, find_gaps
from app.engines.cash.simulate import BASE, Simulation
from tests.cash.helpers import AS_OF, T

D = Decimal
NOW = datetime(2026, 9, 30, 18, 0, tzinfo=UTC)
BUFFER = D(5000)


def _sim(dips, paths=100, horizon=91):
    """Hand-written paths: Tk 9,000 every day, Tk 1,000 on the dip days given per path group.
    `dips` = [(number of paths, (days...)), ...]."""
    rows = []
    for count, days in dips:
        rows += [[1000 if day in days else 9000 for day in range(1, horizon + 1)]] * count
    rows += [[9000] * horizon] * (paths - len(rows))
    base = forecast_baseline(T, AS_OF, D(9000), [], [], [], [], [], horizon=horizon)
    return Simulation(baseline=base, scenario=BASE, seed=0,
                      balances=np.array(rows, dtype=np.int64) * 100)


def _alerts(sim, signals=(), fixes=None):
    return build_alerts(sim, find_gaps(sim, BUFFER), signals, NOW, fixes)


@pytest.mark.parametrize(
    ("dips", "tier"),
    [
        ([(21, (7,))], AlertTier.critical),
        ([(20, (7,)), (6, (8,))], None),
        ([(21, (8,))], AlertTier.warning),
        ([(61, (21,))], AlertTier.critical),
        ([(60, (21,))], AlertTier.warning),
        ([(51, (30,))], AlertTier.warning),
        ([(50, (30,))], AlertTier.watch),
        ([(21, (90,))], AlertTier.watch),
        ([(21, (91,))], None),
    ],
    ids=["21pct-within-7", "20pct-within-7-and-6pct-on-day-8", "21pct-within-8-21",
         "61pct-within-21", "60pct-within-21", "51pct-within-22-45", "50pct-within-22-45",
         "21pct-on-day-90", "21pct-on-day-91-is-past-the-watch-window"],
)
def test_alert_tier_boundaries(dips, tier):
    alerts = _alerts(_sim(dips))
    assert [a.tier for a in alerts] == ([tier] if tier else [])


def test_a_gap_that_fires_no_trigger_still_shows_as_a_gap():
    sim = _sim([(20, (7,)), (6, (8,))])
    (gap,) = find_gaps(sim, BUFFER)
    assert tier_gap(sim, gap).tier is None and gap.gap.probability == D("0.26")


def test_the_trigger_that_fired_is_named():
    sim = _sim([(61, (21,))])
    (gap,) = find_gaps(sim, BUFFER)
    assert tier_gap(sim, gap).reason_key == "alert.trigger.critical_1_21"


def _payroll(day):
    return Signal(LeadingIndicator.payroll_or_emi_at_risk, (), "tenant_a:OBL-2", "PARTY_staff",
                  day)


def test_a_missed_payroll_projected_inside_a_gap_makes_it_critical():
    sim = _sim([(30, (31,))])  # alone this is a Watch
    (alert,) = _alerts(sim, [_payroll(date(2026, 10, 31))])
    assert (alert.tier, alert.title_key) == (AlertTier.critical, "alert.payroll_at_risk")
    assert alert.indicators == (LeadingIndicator.payroll_or_emi_at_risk,)


def test_payroll_at_risk_outside_any_gap_is_a_critical_indicator_alert():
    (alert,) = _alerts(_sim([]), [_payroll(date(2026, 10, 31))])
    assert alert.gap is None and alert.tier is AlertTier.critical
    assert alert.dedupe_key == "indicators:payroll_or_emi_at_risk"


def test_a_gap_alert_says_what_when_how_much_and_why_with_its_fixes():
    card = ActionCard(id="act-1", title_key="action.retime_payable",
                      action_type=ActionType.retime_payable, tier=Tier.EXECUTE)
    sim = _sim([(40, (9, 10))])
    (alert,) = _alerts(sim, fixes=lambda gap: (card,))
    assert alert.title_key == "alert.gap_ahead" and alert.fixes == (card,)
    assert alert.gap.first_breach_day == date(2026, 10, 9)
    assert alert.gap.expected_shortfall.amount == D(1600)  # 40% of paths x Tk 4,000 short
    assert alert.dedupe_key == "gap:2026-10-09" and alert.data_mode is sim.baseline.data_mode


def test_indicators_about_a_gaps_drivers_ride_on_its_alert_and_the_rest_form_a_watch():
    sim = _sim([(40, (9,))])
    (gap,) = find_gaps(sim, BUFFER)
    late = GapDriver(kind=DriverKind.late_customer, label_key="driver.late_customer",
                     amount=Money.of(800), counterparty_token="PARTY_slow")
    gap = Gap(gap=gap.gap.model_copy(update={"drivers": (late,)}), first=gap.first,
              last=gap.last, peak=gap.peak, worst=gap.worst, buffer=gap.buffer)
    signals = [Signal(LeadingIndicator.top_customer_slowing, (), counterparty_token="PARTY_slow"),
               Signal(LeadingIndicator.dso_rising, ()),
               Signal(LeadingIndicator.top_customer_slowing, (), counterparty_token="PARTY_x")]
    gap_alert, other = build_alerts(sim, [gap], signals, NOW)
    assert gap_alert.indicators == (LeadingIndicator.top_customer_slowing,)
    assert other.gap is None and other.tier is AlertTier.watch
    assert other.indicators == (LeadingIndicator.dso_rising,
                                LeadingIndicator.top_customer_slowing)
    assert other.title_key == "alert.customer_slowing"


def test_alerts_come_highest_tier_first_then_soonest():
    sim = _sim([(30, (40,)), (30, (60,)), (30, (5,))])
    alerts = _alerts(sim, [Signal(LeadingIndicator.stock_building, ())])
    assert [(a.tier, a.gap.first_breach_day if a.gap else None) for a in alerts] == [
        (AlertTier.critical, date(2026, 10, 5)), (AlertTier.watch, date(2026, 11, 9)),
        (AlertTier.watch, date(2026, 11, 29)), (AlertTier.watch, None)]


def test_alert_ids_are_stable_for_the_same_forecast_and_differ_between_gaps():
    sim = _sim([(30, (40,)), (30, (60,))])
    first, again = _alerts(sim), _alerts(sim)
    assert [a.id for a in first] == [a.id for a in again]
    assert len({a.id for a in first}) == 2


# ---------------------------------------------------------------- dedupe and cooldown


def _gap_alert(tier, breach, shortfall, last=None, at=NOW):
    """A gap alert whose gap runs from `breach` to `last` (default: four days later)."""
    last = last or breach + timedelta(days=4)
    cash_gap = CashGap(first_breach_day=breach, lead_time_days=(breach - AS_OF).days,
                       probability=D("0.5"), expected_shortfall=Money.of(shortfall),
                       worst_day=breach)
    gap = Gap(gap=cash_gap, first=(breach - AS_OF).days, last=(last - AS_OF).days,
              peak=0, worst=(breach - AS_OF).days, buffer=BUFFER)
    alert = Alert(id="al", tenant_id=T, tier=tier, title_key="alert.gap_ahead", gap=cash_gap,
                  dedupe_key=f"gap:{breach}", created_at=at, data_mode=DataMode.synthetic)
    return alert, gap


OCT31 = date(2026, 10, 31)


def _sent(tier=AlertTier.warning, breach=OCT31, shortfall=10000, ago=timedelta(0)):
    alert, gap = _gap_alert(tier, breach, shortfall, at=NOW - ago)
    return SentAlert.of(alert, gap, AS_OF)


def test_a_first_alert_is_sent_on_the_tiers_channels():
    for tier in AlertTier:
        alert, gap = _gap_alert(tier, OCT31, 10000)
        decision = deliver(alert, gap, AS_OF, [], NOW)
        assert decision.send and decision.reason_key == "alert.new"
        assert decision.channels == CHANNELS[tier]
        assert decision.pinned is (tier is AlertTier.critical)


@pytest.mark.parametrize(
    ("breach_shift", "shortfall", "ago", "send", "reason"),
    [
        (2, 10500, timedelta(days=5), False, "alert.duplicate"),
        (3, 11000, timedelta(days=5), False, "alert.duplicate"),
        (4, 10000, timedelta(days=5), True, "alert.forecast_moved"),
        (-4, 10000, timedelta(days=5), True, "alert.forecast_moved"),
        (0, 11001, timedelta(days=5), True, "alert.forecast_moved"),
        (0, 8999, timedelta(days=5), True, "alert.forecast_moved"),
        (4, 10000, timedelta(days=2), False, "alert.cooldown"),
    ],
    ids=["moved-2-days-5pct", "moved-exactly-3-days-10pct", "4-days-later", "4-days-sooner",
         "shortfall-up-over-10pct", "shortfall-down-over-10pct", "moved-but-cooling-down"],
)
def test_a_repeat_is_sent_only_when_the_forecast_moved_materially(breach_shift, shortfall, ago,
                                                                  send, reason):
    alert, gap = _gap_alert(AlertTier.warning, OCT31 + timedelta(days=breach_shift), shortfall)
    decision = deliver(alert, gap, AS_OF, [_sent(ago=ago)], NOW)
    assert (decision.send, decision.reason_key) == (send, reason)


def test_an_escalation_is_sent_at_once_even_while_cooling_down():
    alert, gap = _gap_alert(AlertTier.critical, OCT31, 10000)
    decision = deliver(alert, gap, AS_OF, [_sent(ago=timedelta(minutes=5))], NOW)
    assert (decision.send, decision.reason_key, decision.pinned) == (True, "alert.escalated",
                                                                     True)


@pytest.mark.parametrize(
    ("tier", "cooldown"),
    [(AlertTier.critical, timedelta(hours=24)), (AlertTier.warning, timedelta(days=3)),
     (AlertTier.watch, timedelta(days=7))],
    ids=["critical-24h", "warning-3-days", "watch-7-days"],
)
def test_each_tier_has_its_own_cooldown(tier, cooldown):
    alert, gap = _gap_alert(tier, OCT31 + timedelta(days=4), 10000)  # moved, still overlapping
    just_before = deliver(alert, gap, AS_OF, [_sent(tier, ago=cooldown - timedelta(minutes=1))],
                          NOW)
    at_the_end = deliver(alert, gap, AS_OF, [_sent(tier, ago=cooldown)], NOW)
    assert (just_before.send, at_the_end.send) == (False, True)


def test_a_different_gap_is_new_even_while_another_cools_down():
    alert, gap = _gap_alert(AlertTier.warning, date(2026, 12, 1), 10000)
    decision = deliver(alert, gap, AS_OF, [_sent(ago=timedelta(minutes=5))], NOW)
    assert decision.reason_key == "alert.new"


def test_the_latest_sent_alert_for_a_gap_is_the_one_compared_against():
    alert, gap = _gap_alert(AlertTier.warning, OCT31, 20000)
    history = [_sent(shortfall=10000, ago=timedelta(days=10)),
               _sent(shortfall=20000, ago=timedelta(days=4))]
    assert deliver(alert, gap, AS_OF, history, NOW).reason_key == "alert.duplicate"


def _indicator_alert(*indicators):
    sim = _sim([])
    (alert,) = build_alerts(sim, [], [Signal(i, ()) for i in indicators], NOW)
    return alert


@pytest.mark.parametrize(
    ("previous", "ago", "send", "reason"),
    [((LeadingIndicator.dso_rising,), timedelta(days=3), False, "alert.duplicate"),
     ((LeadingIndicator.dso_rising,), timedelta(days=7), True, "alert.digest_due"),
     ((LeadingIndicator.stock_building,), timedelta(days=1), True,
      "alert.indicators_changed")],
    ids=["same-set-this-week", "same-set-a-week-later", "set-changed"],
)
def test_an_indicator_alert_repeats_weekly_or_when_its_indicators_change(previous, ago, send,
                                                                         reason):
    earlier = _indicator_alert(*previous)
    sent = SentAlert(dedupe_key=earlier.dedupe_key, tier=earlier.tier, sent_at=NOW - ago)
    decision = deliver(_indicator_alert(LeadingIndicator.dso_rising), None, AS_OF, [sent], NOW)
    assert (decision.send, decision.reason_key) == (send, reason)
