"""Cash alerts: tiers, dedupe and cooldown (WP-04 milestone 4; FEATURES Q1).

One alert per gap (`gaps.find_gaps`), tiered with the exact FEATURES Q1 triggers. "P within
a-b days" is the share of paths below the buffer on at least one day from day a to day b
(1 = the day after as_of), counting only the gap's own days:
  Critical  P within 1-7 > 20%, or P within 1-21 > 60%, or a missed payroll/EMI projected
            (a salary or EMI day inside the gap with a likely balance below zero)
  Warning   P within 8-21 > 20%, or P within 22-45 > 50%
  Watch     P within 22-90 > 20%
The highest tier that fires wins; a gap that fires none stays on the gaps screen without an
alert. Leading indicators about the gap's own drivers (its customer is slowing, its salary day
is at risk) ride on the gap's alert; the others form one indicator alert, a Watch (Critical when
payroll or EMI is at risk outside any gap). Every alert says what, when, how much and why
(the gap and its drivers) and carries fixes, cheapest first (smoothing levers, milestone 5).

Delivery (FEATURES Q1): Watch in-app + weekly digest; Warning in-app + email; Critical in-app +
email, pinned to the top of Today.

Alert fatigue (`deliver`): a gap alert repeats an earlier one when their gaps overlap in time;
a repeat is sent again only if it escalates (always sent at once) or the forecast moved
materially (first breach > 3 days or expected shortfall > 10% away from what was last sent),
and never within the cooldown of the last alert sent for that gap (24 h Critical, 3 days
Warning, 7 days Watch). An indicator alert is sent again when its set of indicators changes,
or after 7 days (the weekly digest).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from app.contracts import (
    ActionCard,
    Alert,
    AlertTier,
    DriverKind,
    LeadingIndicator,
)
from app.engines.cash.gaps import Gap, Signal, exceeds
from app.engines.cash.simulate import Simulation, to_paisa

# (tier, first day, last day, threshold): "P within first-last days > threshold"
TRIGGERS: tuple[tuple[AlertTier, int, int, Decimal], ...] = (
    (AlertTier.critical, 1, 7, Decimal("0.20")),
    (AlertTier.critical, 1, 21, Decimal("0.60")),
    (AlertTier.warning, 8, 21, Decimal("0.20")),
    (AlertTier.warning, 22, 45, Decimal("0.50")),
    (AlertTier.watch, 22, 90, Decimal("0.20")),
)
MOVE_DAYS = 3
MOVE_SHARE = Decimal("0.10")
COOLDOWN = {AlertTier.critical: timedelta(hours=24), AlertTier.warning: timedelta(days=3),
            AlertTier.watch: timedelta(days=7)}
DIGEST_EVERY = timedelta(days=7)
CHANNELS = {AlertTier.watch: ("in_app", "weekly_digest"),
            AlertTier.warning: ("in_app", "email"),
            AlertTier.critical: ("in_app", "email")}
INDICATOR_TITLES = {
    LeadingIndicator.payroll_or_emi_at_risk: "alert.payroll_at_risk",
    LeadingIndicator.top_customer_slowing: "alert.customer_slowing",
    LeadingIndicator.dso_rising: "alert.dso_rising",
    LeadingIndicator.stock_building: "alert.stock_building",
    LeadingIndicator.sales_below_seasonal_norm: "alert.sales_below_norm",
}  # first matching indicator names an indicator-only alert
Fixes = Callable[[Gap], tuple[ActionCard, ...]]


@dataclass(frozen=True)
class Tiering:
    tier: AlertTier | None
    reason_key: str | None  # which trigger fired, e.g. "alert.trigger.critical_1_7"


def window_counts(sim: Simulation, buffer: Decimal, gap: Gap, first: int, last: int) -> int:
    """Paths below `buffer` on at least one day of [first, last] that is also a gap day."""
    lo, hi = max(first, gap.first), min(last, gap.last, sim.baseline.horizon)
    if lo > hi:
        return 0
    return int((sim.balances[:, lo - 1:hi].min(axis=1) < to_paisa(buffer)).sum())


def tier_gap(sim: Simulation, gap: Gap, payroll: Sequence[Signal] = ()) -> Tiering:
    if any(s.day is not None and _in_gap(sim, gap, s.day) for s in payroll):
        return Tiering(AlertTier.critical, "alert.trigger.payroll_or_emi")
    for tier, first, last, threshold in TRIGGERS:
        if exceeds(window_counts(sim, gap.buffer, gap, first, last), sim.paths, threshold):
            return Tiering(tier, f"alert.trigger.{tier.value}_{first}_{last}")
    return Tiering(None, None)


def _in_gap(sim: Simulation, gap: Gap, day: date) -> bool:
    return gap.first <= (day - sim.baseline.as_of).days <= gap.last


def _alert_id(tenant: str, as_of: date, key: str) -> str:
    return "al_" + hashlib.sha256(f"{tenant}|{as_of}|{key}".encode()).hexdigest()[:20]


def _related(gap: Gap, sim: Simulation, signal: Signal) -> bool:
    """Is a leading indicator about one of this gap's own drivers?"""
    if signal.indicator is LeadingIndicator.payroll_or_emi_at_risk:
        return signal.day is not None and _in_gap(sim, gap, signal.day)
    if signal.indicator is LeadingIndicator.top_customer_slowing:
        return any(d.kind is DriverKind.late_customer
                   and d.counterparty_token == signal.counterparty_token
                   for d in gap.gap.drivers)
    return False


def build_alerts(sim: Simulation, gaps: Sequence[Gap], signals: Sequence[Signal],
                 now: datetime, fixes: Fixes | None = None) -> tuple[Alert, ...]:
    """Gap alerts and at most one indicator alert, highest tier first, then soonest."""
    base = sim.baseline
    payroll = [s for s in signals if s.indicator is LeadingIndicator.payroll_or_emi_at_risk]
    used: set[int] = set()
    alerts = []
    for gap in gaps:
        tiering = tier_gap(sim, gap, payroll)
        if tiering.tier is None:
            continue
        mine = [n for n, s in enumerate(signals) if _related(gap, sim, s)]
        used.update(mine)
        key = f"gap:{gap.gap.first_breach_day.isoformat()}"
        title = "alert.payroll_at_risk" if tiering.reason_key == "alert.trigger.payroll_or_emi" \
            else "alert.gap_ahead"
        alerts.append(Alert(
            id=_alert_id(base.tenant_id, base.as_of, key), tenant_id=base.tenant_id,
            tier=tiering.tier, title_key=title, gap=gap.gap,
            indicators=tuple(dict.fromkeys(signals[n].indicator for n in mine)),
            fixes=fixes(gap) if fixes else (), dedupe_key=key, created_at=now,
            data_mode=base.data_mode))
    rest = [s for n, s in enumerate(signals) if n not in used]
    if rest:
        indicators = tuple(dict.fromkeys(s.indicator for s in rest))
        tier = AlertTier.critical if LeadingIndicator.payroll_or_emi_at_risk in indicators \
            else AlertTier.watch
        title = next(t for i, t in INDICATOR_TITLES.items() if i in indicators)
        key = "indicators:" + "+".join(sorted(i.value for i in indicators))
        alerts.append(Alert(
            id=_alert_id(base.tenant_id, base.as_of, key), tenant_id=base.tenant_id, tier=tier,
            title_key=title, indicators=indicators, dedupe_key=key, created_at=now,
            data_mode=base.data_mode))
    alerts.sort(key=lambda a: (-a.tier.rank, a.gap.first_breach_day if a.gap else date.max))
    return tuple(alerts)


# ---------------------------------------------------------------- dedupe and cooldown


@dataclass(frozen=True)
class SentAlert:
    """What was last sent, as the API stores it (one row per alert actually delivered)."""

    dedupe_key: str
    tier: AlertTier
    sent_at: datetime
    first_breach_day: date | None = None
    last_gap_day: date | None = None  # the gap's last risk day
    expected_shortfall: Decimal | None = None

    @classmethod
    def of(cls, alert: Alert, gap: Gap | None, as_of: date) -> SentAlert:
        last = as_of + timedelta(days=gap.last) if gap else None
        return cls(dedupe_key=alert.dedupe_key, tier=alert.tier, sent_at=alert.created_at,
                   first_breach_day=alert.gap.first_breach_day if alert.gap else None,
                   last_gap_day=last,
                   expected_shortfall=alert.gap.expected_shortfall.amount if alert.gap
                   else None)


@dataclass(frozen=True)
class Delivery:
    send: bool
    reason_key: str
    channels: tuple[str, ...] = ()
    pinned: bool = False


def _deliver(alert: Alert, reason: str) -> Delivery:
    return Delivery(True, reason, CHANNELS[alert.tier], alert.tier is AlertTier.critical)


def _moved(alert: Alert, previous: SentAlert) -> bool:
    assert alert.gap is not None and previous.first_breach_day is not None
    days = abs((alert.gap.first_breach_day - previous.first_breach_day).days)
    before = previous.expected_shortfall or Decimal(0)
    change = abs(alert.gap.expected_shortfall.amount - before)
    return days > MOVE_DAYS or change > before * MOVE_SHARE


def deliver(alert: Alert, gap: Gap | None, as_of: date, sent: Sequence[SentAlert],
            now: datetime) -> Delivery:
    """Whether to send `alert` now, given what was already sent for this tenant."""
    if alert.gap is None:
        earlier = [s for s in sent if s.first_breach_day is None]
        if not earlier:
            return _deliver(alert, "alert.new")
        last = max(earlier, key=lambda s: s.sent_at)
        if last.dedupe_key != alert.dedupe_key:
            return _deliver(alert, "alert.indicators_changed")
        if now - last.sent_at >= DIGEST_EVERY:
            return _deliver(alert, "alert.digest_due")
        return Delivery(False, "alert.duplicate")
    first = alert.gap.first_breach_day
    last_day = as_of + timedelta(days=gap.last) if gap else first
    same = [s for s in sent if s.first_breach_day is not None and s.last_gap_day is not None
            and s.first_breach_day <= last_day and first <= s.last_gap_day]
    if not same:
        return _deliver(alert, "alert.new")
    previous = max(same, key=lambda s: s.sent_at)
    if alert.tier.rank > previous.tier.rank:
        return _deliver(alert, "alert.escalated")
    if not _moved(alert, previous):
        return Delivery(False, "alert.duplicate")
    if now - previous.sent_at < COOLDOWN[previous.tier]:
        return Delivery(False, "alert.cooldown")
    return _deliver(alert, "alert.forecast_moved")
