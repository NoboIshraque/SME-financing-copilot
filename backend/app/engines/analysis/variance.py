"""Expected vs reality (WP-07 milestone 3; FEATURES N1).

Every week (and every quarter) the cash forecast is frozen as a `Snapshot`: what WP-04's
baseline, fitted on rows dated up to `as_of` only, expects for each cash-flow line of the next
calendar week (Monday-Sunday) or quarter. When the period is over, `compare` puts the snapshot
next to what happened, line by line:

  cash_sales         till sales                     (WP-04 flow: sales)
  collections        customers paying invoices      (collection, new_invoices)
  other_inflows      loans, owner money, other      (not forecast: expected 0)
  supplier_payments  purchases and supplier bills   (bill, new_bills, purchases)
  fixed_costs        the categories the business's recurring obligations cover (obligation)
  other_costs        every other outflow            (running_cost)
  transfers          between own accounts           (not forecast: expected 0)
  net_cash_flow, closing_balance                    the totals

Lines are ranked by the size of their variance (actual - expected), biggest first; the totals
follow, because they are the sum of the lines, not a cause. Forecast accuracy is
1 - weighted absolute percentage error over the lines. `correction` turns recent checks into a
sales and a cost factor (credibility-weighted towards 1 while there are few checks) and hands
them to WP-04 as a cash `Scenario`, the same shape `/api/cash/whatif` takes.

A snapshot is immutable once stored (`store.py`). One frozen after its period had started is
marked `reconstructed`: it is built only from rows dated up to its `as_of`, but some of them
may have been uploaded later.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any

from app.contracts import (
    DataMode,
    Direction,
    Figure,
    Granularity,
    Period,
    Transaction,
    TxCategory,
    Unit,
    Variance,
)
from app.engines.analysis.figures import make_figure
from app.engines.analysis.ledger import Ledger, NotEnoughData, calendar_period, combined_mode
from app.engines.cash.baseline import (
    OBLIGATION_CATEGORY,
    FlowKind,
    forecast_baseline,
    obligation_days,
)
from app.engines.cash.calendar import Festival
from app.engines.cash.simulate import Scenario
from app.facts.registry import cite

ZERO, ONE, HUNDRED = Decimal(0), Decimal(1), Decimal(100)
CENT = Decimal("0.01")
MIN_HISTORY_DAYS = 56  # the forecaster needs 8 weeks behind it (as WP-04's API)
CREDIBILITY_CHECKS = 4  # after 4 checks a correction carries half its raw weight
MIN_CHECKS = 2  # no correction from a single check
CORRECTION_LIMIT = Decimal("0.5")  # never more than +/-50%
INFLOW_LINES = ("cash_sales", "collections", "other_inflows")
OUTFLOW_LINES = ("supplier_payments", "fixed_costs", "other_costs")
LINES = (*INFLOW_LINES, *OUTFLOW_LINES, "transfers")
TOTALS = ("net_cash_flow", "closing_balance")
SALES_LINES = ("cash_sales", "collections")
COST_LINES = ("supplier_payments", "other_costs")  # fixed costs are known amounts
_FLOW_LINE = {
    FlowKind.sales: "cash_sales", FlowKind.collection: "collections",
    FlowKind.new_invoices: "collections", FlowKind.bill: "supplier_payments",
    FlowKind.new_bills: "supplier_payments", FlowKind.purchases: "supplier_payments",
    FlowKind.obligation: "fixed_costs", FlowKind.running_cost: "other_costs",
}
_PURCHASES = frozenset({TxCategory.purchase, TxCategory.supplier_payment})


class SnapshotKind(StrEnum):
    weekly = "weekly"
    quarterly = "quarterly"

    @property
    def granularity(self) -> Granularity:
        return Granularity.week if self is SnapshotKind.weekly else Granularity.quarter


def target_period(kind: SnapshotKind, as_of: date) -> Period:
    """The calendar week or quarter right after `as_of` (which must end one)."""
    period = calendar_period(as_of + timedelta(days=1), kind.granularity)
    if period.start != as_of + timedelta(days=1):
        raise ValueError(f"a {kind.value} snapshot is frozen on the last day of a "
                         f"{kind.granularity.value}, not on {as_of.isoformat()}")
    return period


def due_dates(kind: SnapshotKind, first_day: date, last_day: date) -> list[date]:
    """Freeze days (the last day of each week or quarter) whose period has a full history
    behind it and has started by `last_day + 1`, oldest first."""
    earliest = first_day + timedelta(days=MIN_HISTORY_DAYS - 1)
    days, period = [], calendar_period(last_day + timedelta(days=1), kind.granularity)
    while True:
        freeze = period.start - timedelta(days=1)
        if freeze < earliest:
            return days[::-1]
        days.append(freeze)
        period = calendar_period(freeze, kind.granularity)


@dataclass(frozen=True)
class Snapshot:
    tenant_id: str
    kind: SnapshotKind
    as_of: date
    period: Period
    opening_balance: Decimal
    expected: Mapping[str, Decimal]  # every line and total
    covered: tuple[str, ...]  # outflow categories the obligations cover (fixed_costs)
    anchor_fact_id: str
    data_mode: DataMode
    frozen_at: datetime
    reconstructed: bool
    formula_version: int = 1
    id: str = field(default="")

    def __post_init__(self) -> None:
        if not self.id:
            object.__setattr__(self, "id", "snap_" + hashlib.sha256(
                json.dumps(self._content(), sort_keys=True).encode()).hexdigest()[:24])

    def _content(self) -> dict[str, Any]:
        return {"tenant_id": self.tenant_id, "kind": self.kind.value,
                "as_of": self.as_of.isoformat(), "start": self.period.start.isoformat(),
                "end": self.period.end.isoformat(),
                "opening_balance": str(self.opening_balance),
                "expected": {k: str(v) for k, v in sorted(self.expected.items())},
                "covered": list(self.covered), "anchor_fact_id": self.anchor_fact_id,
                "data_mode": self.data_mode.value, "formula_version": self.formula_version}

    def payload(self) -> dict[str, Any]:
        return {**self._content(), "id": self.id, "frozen_at": self.frozen_at.isoformat(),
                "reconstructed": self.reconstructed}

    @classmethod
    def from_payload(cls, data: Mapping[str, Any]) -> Snapshot:
        kind = SnapshotKind(data["kind"])
        snapshot = cls(
            tenant_id=data["tenant_id"], kind=kind, as_of=date.fromisoformat(data["as_of"]),
            period=Period(start=date.fromisoformat(data["start"]),
                          end=date.fromisoformat(data["end"]), granularity=kind.granularity),
            opening_balance=Decimal(data["opening_balance"]),
            expected={k: Decimal(v) for k, v in data["expected"].items()},
            covered=tuple(data["covered"]), anchor_fact_id=data["anchor_fact_id"],
            data_mode=DataMode(data["data_mode"]),
            frozen_at=datetime.fromisoformat(data["frozen_at"]),
            reconstructed=bool(data["reconstructed"]),
            formula_version=int(data["formula_version"]))
        if snapshot.id != data["id"]:
            raise ValueError(f"snapshot {data['id']} does not match its content")
        return snapshot


def _covered(ledger: Ledger, as_of: date, end: date) -> tuple[str, ...]:
    """The outflow categories WP-04 takes from the obligations instead of a run rate (the
    same rule as `forecast_baseline`)."""
    found = {OBLIGATION_CATEGORY[o.kind].value for o in ledger.obligations
             if obligation_days(o, as_of + timedelta(days=1), end) or o.end_date is None
             or o.end_date >= as_of}
    return tuple(sorted(found))


def freeze(ledger: Ledger, kind: SnapshotKind, as_of: date, festivals: Sequence[Festival],
           now: datetime, today: date) -> Snapshot:
    """What the forecast made on `as_of` expects for the next week or quarter. `today` is the
    Dhaka date of `now`: a snapshot frozen after its period started is `reconstructed`."""
    period = target_period(kind, as_of)
    known = [t for t in ledger.transactions if t.day <= as_of]
    if not known or (as_of - min(t.day for t in known)).days + 1 < MIN_HISTORY_DAYS:
        raise NotEnoughData(f"8 weeks of transactions before {as_of.isoformat()}")
    if ledger.as_of < as_of:
        raise NotEnoughData(f"transactions up to {as_of.isoformat()}")
    opening, _rows = ledger.cash_at_start(as_of + timedelta(days=1))
    baseline = forecast_baseline(ledger.tenant_id, as_of, opening, known, ledger.invoices,
                                 ledger.bills, ledger.obligations, festivals,
                                 horizon=period.days)
    expected = dict.fromkeys(LINES, ZERO)
    for flow in baseline.flows:
        expected[_FLOW_LINE[flow.kind]] += flow.amount
    expected = {k: v.quantize(CENT, ROUND_HALF_UP) for k, v in expected.items()}
    net = sum((expected[k] for k in INFLOW_LINES), ZERO) - \
        sum((expected[k] for k in OUTFLOW_LINES), ZERO) + expected["transfers"]
    expected["net_cash_flow"] = net
    expected["closing_balance"] = opening + net
    return Snapshot(tenant_id=ledger.tenant_id, kind=kind, as_of=as_of, period=period,
                    opening_balance=opening, expected=expected,
                    covered=_covered(ledger, as_of, period.end),
                    anchor_fact_id=ledger.anchor.id, data_mode=baseline.data_mode,
                    frozen_at=now, reconstructed=today > period.start)


def actual_line(txn: Transaction, covered: Iterable[str]) -> str:
    """The snapshot line a transaction belongs to (mirrors how WP-04 forecasts it)."""
    if txn.category is TxCategory.transfer:
        return "transfers"
    if txn.category in _PURCHASES:
        return "supplier_payments"  # a supplier's refund counts against what was paid
    if txn.direction is Direction.inflow:
        return {TxCategory.sales: "cash_sales", TxCategory.collection: "collections"}.get(
            txn.category, "other_inflows")
    return "fixed_costs" if txn.category.value in set(covered) else "other_costs"


def _signed(line: str, txn: Transaction) -> Decimal:
    """A transaction's amount in its line's own direction (outflow lines count money out)."""
    natural = Direction.outflow if line in OUTFLOW_LINES else Direction.inflow
    return txn.amount.amount if txn.direction is natural else -txn.amount.amount


def favourable(metric: str, difference: Decimal) -> bool:
    """More money in, or less money out, than expected (or exactly as expected)."""
    return difference <= 0 if metric in OUTFLOW_LINES else difference >= 0


@dataclass(frozen=True)
class VarianceReport:
    snapshot: Snapshot
    variances: tuple[Variance, ...]  # lines by size of variance, then the totals
    accuracy: Figure | None  # None when nothing happened in the period
    figures: Mapping[str, tuple[Figure, Figure]]  # metric -> (expected, actual)
    actual: Mapping[str, Decimal]

    @property
    def period(self) -> Period:
        return self.snapshot.period

    def get(self, metric: str) -> Variance:
        return next(v for v in self.variances if v.metric == metric)


def compare(snapshot: Snapshot, ledger: Ledger) -> VarianceReport:
    """The snapshot next to what happened in its period, which must be over."""
    period = snapshot.period
    if ledger.as_of < period.end:
        raise NotEnoughData(f"transactions up to {period.end.isoformat()}")
    if snapshot.tenant_id != ledger.tenant_id:
        raise ValueError("the snapshot belongs to another tenant")
    by_line: dict[str, list[Transaction]] = {line: [] for line in LINES}
    for txn in ledger.between(period.start, period.end):
        by_line[actual_line(txn, snapshot.covered)].append(txn)
    actual = {line: sum((_signed(line, t) for t in rows), ZERO).quantize(CENT)
              for line, rows in by_line.items()}
    closing, before = ledger.cash_at_start(period.end + timedelta(days=1))
    actual["net_cash_flow"] = sum((actual[k] for k in INFLOW_LINES), ZERO) - \
        sum((actual[k] for k in OUTFLOW_LINES), ZERO) + actual["transfers"]
    actual["closing_balance"] = closing

    mode = ledger.data_mode
    params = {"snapshot": snapshot.id, "kind": snapshot.kind.value,
              "as_of": snapshot.as_of.isoformat(), "reconstructed": snapshot.reconstructed}
    figures: dict[str, tuple[Figure, Figure]] = {}
    for metric in (*LINES, *TOTALS):
        if metric == "transfers" and not by_line["transfers"]:
            continue
        if metric in LINES:
            rows = [cite(t) for t in by_line[metric]]
        elif metric == "net_cash_flow":
            rows = [cite(t) for line in LINES for t in by_line[line]]
        else:  # the closing balance: the anchor and every transaction after it
            rows = [cite(t) for t in before]
        expected = make_figure(ledger.tenant_id, snapshot.data_mode, "analysis.variance.expected",
                               f"variance.expected.{metric}", snapshot.expected[metric],
                               Unit.BDT, period, inputs=(ledger.anchor,),
                               rows=(f"snapshot:{snapshot.id}",), params={**params,
                                                                          "line": metric})
        anchored = metric == "closing_balance" or not rows
        real = make_figure(ledger.tenant_id, mode, "analysis.variance.actual",
                           f"variance.actual.{metric}", actual[metric], Unit.BDT, period,
                           inputs=(ledger.anchor,) if anchored else (), rows=rows,
                           params={**params, "line": metric})
        figures[metric] = (expected, real)

    lines = [m for m in LINES if m in figures and
             (snapshot.expected[m] != 0 or actual[m] != 0 or m in SALES_LINES)]
    lines.sort(key=lambda m: (-abs(actual[m] - snapshot.expected[m]), m))
    variances = tuple(
        Variance(metric=m, period=period, expected=snapshot.expected[m], actual=actual[m],
                 unit=Unit.BDT, rank=n)
        for n, m in enumerate([*lines, *TOTALS], start=1))

    weight = sum((abs(actual[m]) for m in LINES), ZERO)
    accuracy = None
    if weight > 0:
        error = sum((abs(actual[m] - snapshot.expected[m]) for m in LINES), ZERO)
        score = max(ZERO, ONE - error / weight) * HUNDRED
        accuracy = make_figure(ledger.tenant_id, mode, "analysis.variance.accuracy",
                               "analysis.forecast_accuracy", score, Unit.percent, period,
                               inputs=[figures[m][i] for m in LINES if m in figures
                                       for i in (0, 1)],
                               params={**params, "method": "1 - weighted absolute "
                                                           "percentage error"})
    return VarianceReport(snapshot=snapshot, variances=variances, accuracy=accuracy,
                          figures=figures, actual=actual)


@dataclass(frozen=True)
class Correction:
    """Factors to feed back into the next forecast (WP-04 `Scenario`)."""

    checks: int
    sales_change_pct: Decimal
    cost_change_pct: Decimal
    applied: bool  # False with fewer than MIN_CHECKS checks: no change
    figures: tuple[Figure, ...] = ()

    def scenario(self) -> Scenario:
        return Scenario(name="variance_correction", sales_change_pct=self.sales_change_pct,
                        cost_change_pct=self.cost_change_pct)


def _factor(reports: Sequence[VarianceReport], lines: Sequence[str]) -> Decimal:
    expected = sum((r.snapshot.expected[m] for r in reports for m in lines), ZERO)
    actual = sum((r.actual[m] for r in reports for m in lines), ZERO)
    if expected <= 0 or actual < 0:
        return ZERO  # no evidence for a change
    weight = Decimal(len(reports)) / Decimal(len(reports) + CREDIBILITY_CHECKS)
    change = weight * (actual / expected - ONE)
    change = max(-CORRECTION_LIMIT, min(CORRECTION_LIMIT, change))
    return (change * HUNDRED).quantize(CENT, ROUND_HALF_UP)


def correction(reports: Sequence[VarianceReport]) -> Correction:
    """Sales and cost corrections from the last checks of one kind, oldest first."""
    if len(reports) < MIN_CHECKS:
        return Correction(checks=len(reports), sales_change_pct=ZERO, cost_change_pct=ZERO,
                          applied=False)
    sales, costs = _factor(reports, SALES_LINES), _factor(reports, COST_LINES)
    last = reports[-1]
    mode = combined_mode(r.snapshot.data_mode for r in reports)
    span = Period(start=reports[0].period.start, end=last.period.end,
                  granularity=last.period.granularity)
    figures = []
    for label, value, lines in (("analysis.sales_correction", sales, SALES_LINES),
                                ("analysis.cost_correction", costs, COST_LINES)):
        inputs = [r.figures[m][i] for r in reports for m in lines if m in r.figures
                  for i in (0, 1)]
        figures.append(make_figure(last.snapshot.tenant_id, mode,
                                   "analysis.variance.correction_pct", label, value,
                                   Unit.percent, span, inputs=inputs,
                                   params={"checks": len(reports), "lines": ",".join(lines)}))
    return Correction(checks=len(reports), sales_change_pct=sales, cost_change_pct=costs,
                      applied=True, figures=tuple(figures))
