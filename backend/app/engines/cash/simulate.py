"""Monte Carlo cash paths: P10/P50/P90 balance per day and P(balance < buffer) (WP-04 m2).

Each of `PATHS` (1,000) paths replays the forecast horizon with its uncertain parts sampled:

- sales        expected sales x a noise ratio. The ratios are the shop's own observed/expected
               sales on past plain days (`SalesModel.residuals`, scaled to average 1), taken in
               blocks of 28 consecutive days (circular block bootstrap), so a slow fortnight
               stays slow instead of averaging out day by day.
- collections  each open invoice is paid on one of the days its customer's history still
               allows (`DelayTable.possible_days`). One draw per customer and path sets how late
               that customer is on all their invoices (a slow payer is slow everywhere).
               Credit sales not yet invoiced: the invoicing of past days (last 91 days, in
               28-day blocks), each paid after an issue-to-payment delay seen in the history.
- costs        cash purchases, running costs and bills not yet issued: the actual spending and
               billing of past days (last 91 days, in 28-day blocks), so repairs, fines and
               other one-off shocks recur as often, and as large, as they did, while weekly
               buying keeps its weekly rhythm. New bills are paid after a delay from history.
- known        obligations and open bills are certain: their dates and amounts are on record.

Every part has the baseline's expectation (`baseline.py`), so the paths are centred on it.

Exact and reproducible: amounts are integer paisa, ratios integer basis points, and the random
generator (NumPy PCG64 from `SEED` unless told otherwise) only ever draws integers.
Percentiles are nearest-rank order statistics (P10 = the 100th lowest of 1,000 balances), so
P10 <= P50 <= P90 holds by construction. Row order and party names do not affect a draw.
`draw` makes every random choice once; `run` assembles a `Scenario` (what-if, smoothing lever)
on the same draws, so the difference between two runs is the change, never luck (common random
numbers).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

import numpy as np

from app.contracts import ForecastBand, ForecastPoint, Money
from app.engines.cash.baseline import RUN_RATE_DAYS, Baseline, FlowKind

PATHS = 1000
SEED = 20261020
BLOCK_DAYS = 28
BP = 10_000  # ratios are integers in basis points (1/10,000)
QUANTILE_SCALE = 10**12  # resolution of the per-customer lateness draw
NEVER = -1  # no payment the evidence supports (later than ever before, or no history)
PAISA = Decimal(100)
CENT = Decimal("0.01")
PROBABILITY = Decimal("0.0001")
ZERO = Decimal(0)
FORMULA_BAND = "cash.forecast_band"
FORMULA_P_BELOW = "cash.p_below_buffer"


def to_paisa(amount: Decimal) -> int:
    return int((amount * PAISA).to_integral_value(rounding=ROUND_HALF_UP))


def from_paisa(paisa: int | np.integer) -> Decimal:
    return (Decimal(int(paisa)) / PAISA).quantize(CENT)


def _percent_bp(percent: Decimal) -> int:
    """1 + percent/100 in basis points (percent rounded to 2 dp)."""
    return int(((Decimal(100) + percent) * 100).to_integral_value(rounding=ROUND_HALF_UP))


def _scale(paisa: np.ndarray, *ratios_bp: np.ndarray | int) -> np.ndarray:
    """paisa x ratio / BP for each ratio in turn, rounded half-up to the paisa after each (all
    values are non-negative; one ratio at a time keeps every product far inside int64)."""
    out = paisa.astype(np.int64)
    for ratio in ratios_bp:
        if not isinstance(ratio, np.ndarray) and ratio == BP:
            continue
        out = (out * ratio + BP // 2) // BP
    return out


def rank(paths: int, percent: int) -> int:
    """1-based nearest-rank position of a percentile: ceil(percent / 100 x paths)."""
    return max(1, -(-percent * paths // 100))


# ---------------------------------------------------------------- scenario


@dataclass(frozen=True)
class InvoiceChange:
    """Replaces how one open invoice is collected: fixed receipts, then `remainder` on the day
    its customer's draw says (an advance: half now, half later; an early-pay discount: 98% now,
    nothing later; netted: nothing)."""

    receipts: tuple[tuple[date, Decimal], ...] = ()
    remainder: Decimal = ZERO


@dataclass(frozen=True)
class Scenario:
    """Changes replayed on the same draws. Percentages are percent (Decimal("-20") = -20%)."""

    name: str = "baseline"
    sales_change_pct: Decimal = ZERO  # sales and credit sales not yet invoiced
    cost_change_pct: Decimal = ZERO  # purchases, running costs and bills not yet issued
    collection_delay_days: int = 0  # every customer payment moves this many days later
    flows: tuple[tuple[date, Decimal], ...] = ()  # extra signed flows: + in, - out
    bill_payments: Mapping[str, tuple[tuple[date, Decimal], ...]] = field(default_factory=dict)
    invoice_changes: Mapping[str, InvoiceChange] = field(default_factory=dict)
    # (first day, last day, percent, days later): that share of the purchases made in those
    # days (cash and on credit) is made the given number of days later instead
    defer_purchases: tuple[tuple[date, date, Decimal, int], ...] = ()

    def __post_init__(self) -> None:
        if not Decimal(-100) <= self.sales_change_pct <= Decimal(500):
            raise ValueError("sales_change_pct must be between -100 and 500")
        if not Decimal(-100) <= self.cost_change_pct <= Decimal(500):
            raise ValueError("cost_change_pct must be between -100 and 500")
        if not 0 <= self.collection_delay_days <= 366:
            raise ValueError("collection_delay_days must be between 0 and 366")
        for first, last, percent, days in self.defer_purchases:
            if first > last or not Decimal(0) <= percent <= Decimal(100) or days < 1:
                raise ValueError("a deferral needs first <= last, 0-100 percent, days >= 1")


BASE = Scenario()


# ---------------------------------------------------------------- draws


@dataclass(frozen=True)
class Draws:
    seed: int
    paths: int
    invoice_ids: tuple[str, ...]  # columns of invoice_day, sorted
    sales_ratio: np.ndarray  # (paths, H) basis points
    invoice_day: np.ndarray  # (paths, n) payment day as days after as_of, or NEVER
    new_invoice: np.ndarray  # (paths, H) paisa invoiced on each forecast day
    new_invoice_delay: np.ndarray  # (paths, H) days from issue to payment, or NEVER
    new_bill: np.ndarray
    new_bill_delay: np.ndarray
    purchase: np.ndarray  # (paths, H) paisa of cash purchases
    running: np.ndarray  # (paths, H) paisa of other running costs


def _ratios_bp(residuals: tuple[Decimal, ...]) -> np.ndarray:
    mean = sum(residuals, ZERO) / len(residuals) if residuals else ZERO
    if mean <= 0:
        return np.array([BP], dtype=np.int64)
    return np.array([int((r / mean * BP).to_integral_value(rounding=ROUND_HALF_UP))
                     for r in residuals], dtype=np.int64)


def _history_paisa(baseline: Baseline, *kinds: FlowKind) -> np.ndarray:
    """Daily totals over the run-rate window (zeros where nothing is on record)."""
    out = np.zeros(RUN_RATE_DAYS, dtype=np.int64)
    for kind in kinds:
        for i, amount in enumerate(baseline.history(kind)):
            out[i] += to_paisa(amount)
    return out


def _blocks(rng: np.random.Generator, length: int, shape: tuple[int, int]) -> np.ndarray:
    """Indices into a history of `length` days: circular blocks of BLOCK_DAYS consecutive days
    from random starts, so weekly purchases and monthly draws keep their rhythm."""
    paths, horizon = shape
    count = -(-horizon // BLOCK_DAYS)
    starts = rng.integers(0, length, size=(paths, count))
    index = (starts[:, :, None] + np.arange(BLOCK_DAYS)) % length
    return index.reshape(paths, count * BLOCK_DAYS)[:, :horizon]


def _delays(values: tuple[int, ...], rng: np.random.Generator, shape: tuple[int, int]
            ) -> np.ndarray:
    if not values:
        return np.full(shape, NEVER, dtype=np.int64)
    return np.array(values, dtype=np.int64)[rng.integers(0, len(values), size=shape)]


def _customer_order(baseline: Baseline) -> list[str]:
    """Customers by what they owe (most first), then first issue date: an order that renaming
    parties or reordering rows cannot change (ties fall back to the token)."""
    owed: dict[str, Decimal] = {}
    first: dict[str, date] = {}
    for inv, amount in baseline.open_invoices:
        token = inv.counterparty_token
        owed[token] = owed.get(token, ZERO) + amount
        first[token] = min(first.get(token, inv.issue_date), inv.issue_date)
    return sorted(owed, key=lambda t: (-owed[t], first[t], t))


def draw(baseline: Baseline, seed: int = SEED, paths: int = PATHS) -> Draws:
    """Every random choice for `paths` paths over the baseline's horizon, from `seed` alone."""
    if paths < 1:
        raise ValueError("paths must be at least 1")
    horizon = baseline.horizon
    shape = (paths, horizon)
    streams = [np.random.Generator(np.random.PCG64(s))
               for s in np.random.SeedSequence(seed).spawn(5)]
    sales_rng, customer_rng, invoice_rng, spend_rng, delay_rng = streams

    ratios = _ratios_bp(baseline.sales.residuals)
    sales_ratio = ratios[_blocks(sales_rng, len(ratios), shape)]

    customers = _customer_order(baseline)
    lateness = customer_rng.integers(0, QUANTILE_SCALE, size=(paths, max(len(customers), 1)))
    column = {token: i for i, token in enumerate(customers)}
    invoices = sorted(baseline.open_invoices, key=lambda pair: pair[0].id)
    invoice_day = np.full((paths, len(invoices)), NEVER, dtype=np.int64)
    for j, (inv, _owed) in enumerate(invoices):
        days = [(d - baseline.as_of).days
                for d in baseline.invoice_delays.possible_days(inv, baseline.as_of)]
        if days:
            pick = lateness[:, column[inv.counterparty_token]] * len(days) // QUANTILE_SCALE
            invoice_day[:, j] = np.array(days, dtype=np.int64)[pick]

    invoiced = _history_paisa(baseline, FlowKind.new_invoices)
    new_invoice = invoiced[_blocks(invoice_rng, len(invoiced), shape)]
    new_invoice_delay = _delays(baseline.invoice_delays.issue_to_paid, delay_rng, shape)
    # Bills and cash spending replay the same past days, so a heavy buying week is heavy in both.
    spend_days = _blocks(spend_rng, RUN_RATE_DAYS, shape)
    new_bill = _history_paisa(baseline, FlowKind.new_bills)[spend_days]
    new_bill_delay = _delays(baseline.bill_delays.issue_to_paid, delay_rng, shape)
    purchase = _history_paisa(baseline, FlowKind.purchases)[spend_days]
    running = _history_paisa(baseline, FlowKind.running_cost)[spend_days]

    return Draws(seed=seed, paths=paths, invoice_ids=tuple(inv.id for inv, _o in invoices),
                 sales_ratio=sales_ratio, invoice_day=invoice_day, new_invoice=new_invoice,
                 new_invoice_delay=new_invoice_delay, new_bill=new_bill,
                 new_bill_delay=new_bill_delay, purchase=purchase, running=running)


# ---------------------------------------------------------------- assembly


@dataclass(frozen=True)
class Simulation:
    baseline: Baseline
    scenario: Scenario
    seed: int
    balances: np.ndarray  # (paths, H) int64 paisa, end of each day

    @property
    def paths(self) -> int:
        return int(self.balances.shape[0])

    def percentile(self, percent: int) -> np.ndarray:
        """Nearest-rank percentile of the end-of-day balance, per day (paisa)."""
        ordered = np.sort(self.balances, axis=0)
        return ordered[rank(self.paths, percent) - 1]

    def p_below(self, buffer: Decimal) -> list[Decimal]:
        """Per day: share of paths whose end-of-day balance is below `buffer`."""
        counts = (self.balances < to_paisa(buffer)).sum(axis=0)
        return [self._share(int(c)) for c in counts]

    def p_dip(self, buffer: Decimal, first: int, last: int) -> Decimal:
        """Share of paths below `buffer` on at least one day from day `first` to day `last`
        (1 = the day after as_of)."""
        if not 1 <= first <= last:
            raise ValueError("window must satisfy 1 <= first <= last")
        last = min(last, self.balances.shape[1])
        if first > last:
            return ZERO
        lows = self.balances[:, first - 1:last].min(axis=1)
        return self._share(int((lows < to_paisa(buffer)).sum()))

    def _share(self, count: int) -> Decimal:
        return (Decimal(count) / Decimal(self.paths)).quantize(PROBABILITY, ROUND_HALF_UP)

    def band(self, buffer: Decimal, now: datetime) -> ForecastBand:
        p10, p50, p90 = (self.percentile(q) for q in (10, 50, 90))
        below = self.p_below(buffer)
        points = tuple(
            ForecastPoint(day=day, p10=Money.of(from_paisa(p10[t])),
                          p50=Money.of(from_paisa(p50[t])), p90=Money.of(from_paisa(p90[t])),
                          p_below_buffer=below[t])
            for t, day in enumerate(self.baseline.days))
        return ForecastBand(
            tenant_id=self.baseline.tenant_id, as_of=self.baseline.as_of,
            horizon_days=self.baseline.horizon, paths=self.paths, seed=self.seed,
            opening_balance=Money.of(self.baseline.opening_balance), buffer=Money.of(buffer),
            points=points, data_mode=self.baseline.data_mode, generated_at=now)


def _day_index(baseline: Baseline, day: date) -> int:
    offset = (day - baseline.as_of).days
    if offset < 1:
        raise ValueError(f"{day} is not after as_of {baseline.as_of}")
    return offset - 1  # may be >= horizon: after the forecast window


def _add(vector: np.ndarray, index: int, paisa: int) -> None:
    if index < vector.shape[0]:
        vector[index] += paisa


def _scatter(out: np.ndarray, amount: np.ndarray, delay: np.ndarray, shift: int) -> None:
    """Add amount[p, k] on day k + delay[p, k] + shift of path p (when inside the horizon)."""
    paths, horizon = amount.shape
    day = np.arange(horizon)[None, :] + delay + shift
    keep = (delay != NEVER) & (day < horizon) & (amount != 0)
    rows = np.broadcast_to(np.arange(paths)[:, None], amount.shape)[keep]
    np.add.at(out, (rows, day[keep]), amount[keep])


def _known(baseline: Baseline, scenario: Scenario) -> np.ndarray:
    """Certain flows per day (paisa): obligations, open bills, the scenario's own flows."""
    known = np.zeros(baseline.horizon, dtype=np.int64)
    for flow in baseline.flows:
        if flow.kind is FlowKind.obligation:
            known[_day_index(baseline, flow.day)] -= to_paisa(flow.amount)
    bill_ids = {ob.bill.id for ob in baseline.open_bills}
    if unknown := set(scenario.bill_payments) - bill_ids:
        raise ValueError(f"no open bill {sorted(unknown)}")
    for ob in baseline.open_bills:
        payments = scenario.bill_payments.get(ob.bill.id, ((ob.pay_day, ob.owed),))
        for day, amount in payments:
            _add(known, _day_index(baseline, day), -to_paisa(amount))
    for change in scenario.invoice_changes.values():
        for day, amount in change.receipts:
            _add(known, _day_index(baseline, day), to_paisa(amount))
    for day, amount in scenario.flows:
        _add(known, _day_index(baseline, day), to_paisa(amount))
    return known


def run(baseline: Baseline, draws: Draws, scenario: Scenario = BASE) -> Simulation:
    """Assemble the paths of `scenario` from `draws` (made for this baseline)."""
    paths, horizon = draws.sales_ratio.shape
    if horizon != baseline.horizon or len(draws.invoice_ids) != len(baseline.open_invoices):
        raise ValueError("draws were made for a different baseline")
    if unknown := set(scenario.invoice_changes) - set(draws.invoice_ids):
        raise ValueError(f"no open invoice {sorted(unknown)}")
    sales_bp = _percent_bp(scenario.sales_change_pct)
    cost_bp = _percent_bp(scenario.cost_change_pct)
    shift = scenario.collection_delay_days

    expected = np.zeros(horizon, dtype=np.int64)
    for flow in baseline.flows:
        if flow.kind is FlowKind.sales:
            expected[_day_index(baseline, flow.day)] += to_paisa(flow.amount)
    net = _scale(np.broadcast_to(expected, (paths, horizon)), draws.sales_ratio, sales_bp)

    owed = {inv.id: amount for inv, amount in baseline.open_invoices}
    for j, invoice_id in enumerate(draws.invoice_ids):
        change = scenario.invoice_changes.get(invoice_id)
        paisa = to_paisa(change.remainder if change else owed[invoice_id])
        day = draws.invoice_day[:, j]
        hit = (day != NEVER) & (day + shift <= horizon) & (paisa > 0)
        np.add.at(net, (np.nonzero(hit)[0], day[hit] + shift - 1), paisa)
    _scatter(net, _scale(draws.new_invoice, sales_bp), draws.new_invoice_delay, shift)

    purchase = _scale(draws.purchase, cost_bp)
    billed = _scale(draws.new_bill, cost_bp)
    for first, last, percent, days in scenario.defer_purchases:
        lo, hi = _day_index(baseline, first), min(_day_index(baseline, last), horizon - 1)
        for spend in (purchase, billed):
            moved = _scale(spend[:, lo:hi + 1], _percent_bp(percent - 100))
            spend[:, lo:hi + 1] -= moved
            if lo + days < horizon:
                spend[:, lo + days:hi + 1 + days] += moved[:, :horizon - lo - days]
    net -= purchase + _scale(draws.running, cost_bp)
    spent = np.zeros_like(net)
    _scatter(spent, billed, draws.new_bill_delay, 0)
    net -= spent
    net += _known(baseline, scenario)[None, :]

    balances = to_paisa(baseline.opening_balance) + np.cumsum(net, axis=1)
    return Simulation(baseline=baseline, scenario=scenario, seed=draws.seed, balances=balances)


def simulate(baseline: Baseline, seed: int = SEED, paths: int = PATHS,
             scenario: Scenario = BASE) -> Simulation:
    return run(baseline, draw(baseline, seed, paths), scenario)
