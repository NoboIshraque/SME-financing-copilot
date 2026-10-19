"""Walk-forward backtest of the cash forecaster (WP-04 milestone 7; FEATURES N15, Q3 step 4).

Every `step_days` from the first origin to the last, the forecaster sees only what was known on
that origin day (`known_at`): transactions up to it, documents issued by then, and a payment
only if it was made by then. Disputes and write-offs carry no date, so they are not known at
an origin. Obligations count from their start date. It forecasts `horizon_days` ahead (1,000
seeded paths), and the forecast is scored against what actually happened next:

  MAPE        mean |P50 - actual| / |actual| over every (origin, day) pair, in percent; days
              whose actual balance is under Tk 1,000 are skipped (a percentage of nothing).
              Reported overall and per horizon week, beside the naive forecast ("the balance
              stays where it is"): on the synthetic shops the forecast wins clearly in the
              first weeks, which drive the alerts, and loses late in the horizon, where owner
              draws pull balances back towards a level no run rate anticipates.
  coverage    share of actual balances inside the P10-P90 band (80% if the band is honest)
  gaps        an actual gap episode is a run of days with the actual balance below the
              buffer. An origin flags an episode when one of its forecast gaps that would
              raise an alert (`alerts.tier_gap`) overlaps the episode within 3 days.
  hit rate    flagged episodes / episodes that a forecast could have seen (one starting
              after the first origin and within the horizon of some origin before it)
  lead time   for each flagged episode, days from the earliest origin that flagged it to
              the episode's first day
  unrealised  an alerting forecast gap that overlaps no actual episode within 3 days. Alerts
              are probabilities, so some are expected to pass: calibration compares the mean
              probability the alerting gaps carried with the share of them that happened.

The buffer is fixed for the run: the caller's, or the buffer target of the first origin.
Runnable on the synthetic universe and, through `daily_csv_transactions`, on any daily
inflow/outflow series (the WP-17 public-data export):

    uv run python -m app.engines.cash.backtest --sme sme_grocery
    uv run python -m app.engines.cash.backtest --daily-csv retail_daily.csv --opening 250000
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from app.contracts import (
    Bill,
    Channel,
    DataMode,
    Direction,
    DocumentStatus,
    Invoice,
    Money,
    RecurringObligation,
    Transaction,
    TxCategory,
)
from app.engines.cash.alerts import tier_gap
from app.engines.cash.baseline import Baseline, forecast_baseline
from app.engines.cash.buffer import buffer_target
from app.engines.cash.calendar import Festival, load_festivals
from app.engines.cash.gaps import find_gaps
from app.engines.cash.simulate import PATHS, SEED, from_paisa, simulate, to_paisa

HORIZON_DAYS = 91
STEP_DAYS = 14
MIN_HISTORY_DAYS = 182  # the sales model looks back 26 weeks
MATCH_DAYS = 3
MAPE_FLOOR = Decimal(1000)
DHAKA = ZoneInfo("Asia/Dhaka")
ZERO = Decimal(0)
PERCENT = Decimal("0.01")


# ---------------------------------------------------------------- what was known when


def _as_known(doc: Invoice | Bill, origin: date) -> Invoice | Bill:
    if doc.paid_date is not None and doc.paid_date <= origin:
        return doc
    if doc.status is DocumentStatus.open and doc.amount_paid.amount == 0:
        return doc
    return doc.model_copy(update={"amount_paid": Money.zero(doc.amount.currency),
                                  "status": DocumentStatus.open, "paid_date": None})


def known_at(transactions: Sequence[Transaction], invoices: Sequence[Invoice],
             bills: Sequence[Bill], obligations: Sequence[RecurringObligation], origin: date
             ) -> tuple[list[Transaction], list[Invoice], list[Bill], list[RecurringObligation]]:
    """The ledger exactly as it could have been known at the end of `origin`."""
    return ([t for t in transactions if t.day <= origin],
            [_as_known(i, origin) for i in invoices if i.issue_date <= origin],
            [_as_known(b, origin) for b in bills if b.issue_date <= origin],
            [o for o in obligations if o.start_date <= origin])


def actual_balances(transactions: Sequence[Transaction], initial_balance: Decimal, start: date,
                    end: date) -> dict[date, Decimal]:
    """End-of-day balance across all accounts for every day of [start, end]."""
    net: dict[date, Decimal] = {}
    for txn in transactions:
        net[txn.day] = net.get(txn.day, ZERO) + txn.signed_amount.amount
    running = initial_balance + sum((v for d, v in net.items() if d < start), ZERO)
    out = {}
    day = start
    while day <= end:
        running += net.get(day, ZERO)
        out[day] = running
        day += timedelta(days=1)
    return out


# ---------------------------------------------------------------- results


@dataclass(frozen=True)
class OriginResult:
    origin: date
    opening_balance: Decimal
    mape_percent: Decimal | None
    naive_mape_percent: Decimal | None
    coverage: Decimal | None
    alert_gaps: tuple[tuple[date, date, Decimal], ...]  # (first, last risk day, probability)


@dataclass(frozen=True)
class Episode:
    first: date
    last: date
    flagged_by: date | None  # earliest origin that flagged it

    @property
    def lead_days(self) -> int | None:
        return (self.first - self.flagged_by).days if self.flagged_by else None


@dataclass(frozen=True)
class BacktestReport:
    tenant_id: str
    data_mode: DataMode
    buffer: Decimal
    horizon_days: int
    step_days: int
    paths: int
    seed: int
    origins: tuple[OriginResult, ...]
    episodes: tuple[Episode, ...]  # actual gap episodes a forecast could have seen
    mape_percent: Decimal | None
    naive_mape_percent: Decimal | None
    mape_by_week: tuple[Decimal | None, ...]
    naive_by_week: tuple[Decimal | None, ...]
    coverage: Decimal | None
    alerting_gaps: int
    unrealised_alerts: int
    mean_alert_probability: Decimal | None  # what the alerting gaps said, on average

    @property
    def hit_rate(self) -> Decimal | None:
        if not self.episodes:
            return None
        caught = sum(1 for e in self.episodes if e.flagged_by is not None)
        return (Decimal(caught) / len(self.episodes)).quantize(Decimal("0.0001"))

    @property
    def lead_times(self) -> tuple[int, ...]:
        return tuple(e.lead_days for e in self.episodes if e.lead_days is not None)

    @property
    def median_lead_days(self) -> int | None:
        leads = sorted(self.lead_times)
        return leads[(len(leads) - 1) // 2] if leads else None

    @property
    def realised_share(self) -> Decimal | None:
        """Share of alerting gaps that did happen (compare with mean_alert_probability)."""
        if not self.alerting_gaps:
            return None
        happened = self.alerting_gaps - self.unrealised_alerts
        return (Decimal(happened) / self.alerting_gaps).quantize(Decimal("0.0001"))

    def summary(self) -> dict[str, object]:
        """Plain JSON-friendly numbers (for the evidence report)."""
        def text(value: object) -> object:
            return str(value) if isinstance(value, Decimal | date) else value

        return {
            "tenant_id": self.tenant_id, "data_mode": self.data_mode.value,
            "buffer": str(self.buffer), "horizon_days": self.horizon_days,
            "step_days": self.step_days, "paths": self.paths, "seed": self.seed,
            "origins": len(self.origins), "mape_percent": text(self.mape_percent),
            "naive_mape_percent": text(self.naive_mape_percent),
            "mape_by_week": [text(v) for v in self.mape_by_week],
            "naive_mape_by_week": [text(v) for v in self.naive_by_week],
            "p10_p90_coverage": text(self.coverage), "gap_episodes": len(self.episodes),
            "hit_rate": text(self.hit_rate), "lead_times_days": list(self.lead_times),
            "median_lead_days": self.median_lead_days, "alerting_gaps": self.alerting_gaps,
            "unrealised_alerts": self.unrealised_alerts,
            "mean_alert_probability": text(self.mean_alert_probability),
            "realised_share": text(self.realised_share),
            "per_origin": [{k: [[text(x) for x in g] for g in v] if k == "alert_gaps"
                            else text(v) for k, v in asdict(o).items()} for o in self.origins],
        }


def _mean_percent(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return (sum(values, ZERO) / len(values) * 100).quantize(PERCENT, ROUND_HALF_UP)


def _episodes(actual: dict[date, Decimal], buffer: Decimal) -> list[tuple[date, date]]:
    runs, start, previous = [], None, None
    for day in sorted(actual):
        if actual[day] < buffer:
            start = start or day
        elif start is not None:
            runs.append((start, previous))
            start = None
        previous = day
    if start is not None:
        runs.append((start, previous))
    return runs


def _overlaps(gap: tuple[date, date], episode: tuple[date, date]) -> bool:
    slack = timedelta(days=MATCH_DAYS)
    return gap[0] <= episode[1] + slack and episode[0] - slack <= gap[1]


# ---------------------------------------------------------------- the walk


def backtest(
    tenant_id: str,
    transactions: Sequence[Transaction],
    invoices: Sequence[Invoice],
    bills: Sequence[Bill],
    obligations: Sequence[RecurringObligation],
    festivals: Sequence[Festival],
    initial_balance: Decimal,
    *,
    first_origin: date | None = None,
    last_origin: date | None = None,
    buffer: Decimal | None = None,
    horizon_days: int = HORIZON_DAYS,
    step_days: int = STEP_DAYS,
    paths: int = PATHS,
    seed: int = SEED,
) -> BacktestReport:
    """Walk forward through the ledger; each origin's forecast sees only `known_at(origin)`."""
    if not transactions:
        raise ValueError("a backtest needs transactions")
    days = sorted(t.day for t in transactions)
    start, end = days[0], days[-1]
    first_origin = first_origin or start + timedelta(days=MIN_HISTORY_DAYS - 1)
    last_origin = last_origin or end - timedelta(days=horizon_days)
    if first_origin > last_origin:
        raise ValueError("not enough history: no origin has both a past and a full horizon")
    actual = actual_balances(transactions, initial_balance, start, end)

    def forecast(origin: date) -> Baseline:
        txns, invs, bls, obls = known_at(transactions, invoices, bills, obligations, origin)
        return forecast_baseline(tenant_id, origin, actual[origin], txns, invs, bls, obls,
                                 festivals, horizon=horizon_days)

    results: list[OriginResult] = []
    errors, naive_errors, inside, scored = [], [], 0, 0
    weeks = -(-horizon_days // 7)
    by_week: list[list[Decimal]] = [[] for _ in range(weeks)]
    naive_week: list[list[Decimal]] = [[] for _ in range(weeks)]
    origin = first_origin
    while origin <= last_origin:
        sim = simulate(forecast(origin), seed=seed, paths=paths)
        if buffer is None:
            buffer = buffer_target(sim)
        p10, p50, p90 = (sim.percentile(q) for q in (10, 50, 90))
        mine, naive = [], []
        for t, day in enumerate(sim.baseline.days):
            real = to_paisa(actual[day])
            inside += int(p10[t] <= real <= p90[t])
            scored += 1
            if abs(actual[day]) >= MAPE_FLOOR:
                mine.append(abs(from_paisa(p50[t]) - actual[day]) / abs(actual[day]))
                naive.append(abs(actual[origin] - actual[day]) / abs(actual[day]))
                by_week[t // 7].append(mine[-1])
                naive_week[t // 7].append(naive[-1])
        errors += mine
        naive_errors += naive
        alerting = tuple(
            (origin + timedelta(days=g.first), origin + timedelta(days=g.last), g.gap.probability)
            for g in find_gaps(sim, buffer) if tier_gap(sim, g).tier is not None)
        results.append(OriginResult(
            origin=origin, opening_balance=actual[origin], mape_percent=_mean_percent(mine),
            naive_mape_percent=_mean_percent(naive),
            coverage=(Decimal(sum(int(p10[t] <= to_paisa(actual[d]) <= p90[t])
                                  for t, d in enumerate(sim.baseline.days)))
                      / horizon_days).quantize(Decimal("0.0001")),
            alert_gaps=alerting))
        origin += timedelta(days=step_days)
    assert buffer is not None

    seen_until = results[-1].origin + timedelta(days=horizon_days)
    episodes = []
    for first, last in _episodes(actual, buffer):
        if not (results[0].origin < first <= seen_until):
            continue  # no forecast before it could have seen it
        flags = [r.origin for r in results
                 if r.origin < first and any(_overlaps(g[:2], (first, last))
                                             for g in r.alert_gaps)]
        episodes.append(Episode(first, last, min(flags) if flags else None))
    actual_runs = _episodes(actual, buffer)
    alerts = [g for r in results for g in r.alert_gaps]
    unrealised = sum(1 for g in alerts if not any(_overlaps(g[:2], run) for run in actual_runs))
    mean_p = None
    if alerts:
        mean_p = (sum((g[2] for g in alerts), ZERO) / len(alerts)).quantize(Decimal("0.0001"))
    modes = {t.data_mode for t in transactions}
    mode = next((m for m in (DataMode.synthetic, DataMode.real_anonymised, DataMode.public,
                             DataMode.live) if m in modes), DataMode.live)
    return BacktestReport(
        tenant_id=tenant_id, data_mode=mode, buffer=buffer, horizon_days=horizon_days,
        step_days=step_days, paths=paths, seed=seed, origins=tuple(results),
        episodes=tuple(episodes), mape_percent=_mean_percent(errors),
        naive_mape_percent=_mean_percent(naive_errors),
        mape_by_week=tuple(_mean_percent(w) for w in by_week),
        naive_by_week=tuple(_mean_percent(w) for w in naive_week),
        coverage=(Decimal(inside) / scored).quantize(Decimal("0.0001")) if scored else None,
        alerting_gaps=len(alerts), unrealised_alerts=unrealised, mean_alert_probability=mean_p)


# ---------------------------------------------------------------- inputs and CLI


def daily_csv_transactions(text: str, tenant_id: str, data_mode: DataMode = DataMode.public,
                           source: str = "daily.csv") -> list[Transaction]:
    """Rows of `date,inflow,outflow` (daily totals, e.g. the WP-17 public retail series) as
    sales inflows and purchase outflows."""
    out = []
    for line, row in enumerate(csv.DictReader(io.StringIO(text)), start=2):
        day = date.fromisoformat(row["date"].strip())
        for column, direction, category in (("inflow", Direction.inflow, TxCategory.sales),
                                            ("outflow", Direction.outflow, TxCategory.purchase)):
            amount = Decimal(row.get(column, "0").strip() or "0")
            if amount > 0:
                out.append(Transaction(
                    id=f"{tenant_id}-{day.isoformat()}-{column}", tenant_id=tenant_id,
                    occurred_at=datetime.combine(day, time(12), DHAKA),
                    amount=Money.of(amount), direction=direction, channel=Channel.other,
                    category=category, source_ref=f"{source}#L{line}", data_mode=data_mode))
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Walk-forward backtest of the cash forecast")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--sme", help="a synthetic SME id, e.g. sme_grocery")
    group.add_argument("--daily-csv", type=Path, help="date,inflow,outflow daily totals")
    parser.add_argument("--opening", default="0", help="balance before the first row")
    parser.add_argument("--buffer", default=None)
    parser.add_argument("--step-days", type=int, default=STEP_DAYS)
    parser.add_argument("--paths", type=int, default=PATHS)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    buffer = Decimal(args.buffer) if args.buffer else None
    if args.sme:
        from app.synthetic import load_universe

        sme = load_universe().smes[args.sme]
        report = backtest(sme.id, sme.transactions, sme.invoices, sme.bills, sme.obligations,
                          load_festivals(), sme.opening_total.amount, buffer=buffer,
                          step_days=args.step_days, paths=args.paths)
    else:
        tenant = args.daily_csv.stem
        txns = daily_csv_transactions(args.daily_csv.read_text(encoding="utf-8"), tenant,
                                      source=args.daily_csv.name)
        report = backtest(tenant, txns, [], [], [], load_festivals(), Decimal(args.opening),
                          buffer=buffer, step_days=args.step_days, paths=args.paths)
    text = json.dumps(report.summary(), indent=2)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    else:
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
