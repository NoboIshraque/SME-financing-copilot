"""Recurring sales model (WP-04 milestone 1).

expected sales(day) = level x weekday factor x month-end factor x festival factor

Every part is estimated from the tenant's own sales history up to `as_of`, never later rows:
the weekday and month-end factors from the last 26 weeks, the level from the last 8 weeks
(de-seasonalised, so it follows the trend), and festival factors from every earlier occurrence
of the same festival. A factor without evidence stays at 1: no effect is assumed rather than
guessed. The observed/expected ratios on past plain days (oldest first, weekday and month-end
included) are kept for the Monte Carlo noise.
"""

from __future__ import annotations

import calendar as _calendar
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from app.contracts import Direction, Transaction, TxCategory
from app.engines.cash.calendar import Festival, festival_offsets

ONE, ZERO = Decimal(1), Decimal(0)
FACTOR = Decimal("0.0001")
HISTORY_DAYS = 182
LEVEL_DAYS = 56
MONTH_END_DAYS = 3
BASE_WINDOW = (-40, -11)  # festival factors compare against this stretch before each festival


def is_month_end(day: date) -> bool:
    return day.day > _calendar.monthrange(day.year, day.month)[1] - MONTH_END_DAYS


def _mean(values: Sequence[Decimal]) -> Decimal | None:
    return sum(values, ZERO) / Decimal(len(values)) if values else None


def daily_sales(transactions: Iterable[Transaction], start: date, end: date
                ) -> dict[date, Decimal]:
    """Sales inflows per day (every day of [start, end], zero when nothing was sold)."""
    totals = {start + timedelta(days=i): ZERO for i in range((end - start).days + 1)}
    for txn in transactions:
        if (txn.category is TxCategory.sales and txn.direction is Direction.inflow
                and start <= txn.day <= end):
            totals[txn.day] += txn.amount.amount
    return totals


@dataclass(frozen=True)
class SalesModel:
    level: Decimal
    weekday: tuple[Decimal, ...]  # Monday first
    month_end: Decimal
    festival: Mapping[tuple[str, int], Decimal]
    residuals: tuple[Decimal, ...]
    festivals: tuple[Festival, ...] = field(default=())
    history_days: int = 0
    # Festivals never seen in the history borrow their family's factors ("eid_ul_fitr" from
    # "eid_ul_adha"): the shop's own Eid run-up is better evidence than no effect at all.
    family: Mapping[tuple[str, int], Decimal] = field(default_factory=dict)

    def festival_factor(self, name: str, offset: int) -> Decimal:
        if (name, offset) in self.festival:
            return self.festival[(name, offset)]
        return self.family.get((festival_family(name), offset), ONE)

    def expected(self, day: date) -> Decimal:
        value = self.level * self.weekday[day.weekday()]
        if is_month_end(day):
            value *= self.month_end
        for name, offset in festival_offsets(day, self.festivals):
            value *= self.festival_factor(name, offset)
        return value


def festival_family(name: str) -> str:
    return name.split("_", 1)[0]


def no_sales(festivals: Sequence[Festival] = ()) -> SalesModel:
    return SalesModel(level=ZERO, weekday=(ONE,) * 7, month_end=ONE, festival={}, residuals=(),
                      festivals=tuple(festivals), history_days=0)


def fit_sales(transactions: Sequence[Transaction], as_of: date,
              festivals: Sequence[Festival]) -> SalesModel:
    """Estimate the sales model from transactions on or before `as_of` only."""
    sale_days = [t.day for t in transactions if t.category is TxCategory.sales
                 and t.direction is Direction.inflow and t.day <= as_of]
    if not sale_days:
        return no_sales(festivals)
    first = min(sale_days)
    totals = daily_sales(transactions, first, as_of)
    start = max(first, as_of - timedelta(days=HISTORY_DAYS - 1))
    recent = [d for d in totals if d >= start]
    plain = [d for d in recent if not festival_offsets(d, festivals)]
    mean = _mean([totals[d] for d in plain])
    if not mean:
        return no_sales(festivals)

    weekday = []
    for w in range(7):
        avg = _mean([totals[d] for d in plain if d.weekday() == w])
        weekday.append((avg / mean).quantize(FACTOR) if avg is not None else ONE)

    def ratio(day: date, base: Decimal) -> Decimal | None:
        expected = base * weekday[day.weekday()]
        return totals[day] / expected if expected > 0 else None

    ends = [r for d in plain if is_month_end(d) and (r := ratio(d, mean)) is not None]
    others = [r for d in plain if not is_month_end(d) and (r := ratio(d, mean)) is not None]
    end_mean, other_mean = _mean(ends), _mean(others)
    month_end = (end_mean / other_mean).quantize(FACTOR) if end_mean and other_mean else ONE

    def deseasonalised(day: date) -> Decimal | None:
        factor = weekday[day.weekday()] * (month_end if is_month_end(day) else ONE)
        return totals[day] / factor if factor > 0 else None

    level_days = [d for d in plain if d > as_of - timedelta(days=LEVEL_DAYS)]
    level = _mean([v for d in level_days if (v := deseasonalised(d)) is not None]) or mean

    by_offset: dict[tuple[str, int], list[Decimal]] = {}
    for festival in festivals:
        base_days = [festival.day + timedelta(days=k)
                     for k in range(BASE_WINDOW[0], BASE_WINDOW[1] + 1)]
        base = _mean([v for d in base_days if d in totals and not festival_offsets(d, festivals)
                      and (v := deseasonalised(d)) is not None])
        if not base:
            continue
        for d in totals:
            for name, offset in festival_offsets(d, (festival,)):
                if (v := deseasonalised(d)) is not None:
                    by_offset.setdefault((name, offset), []).append(v / base)
    festival_factors = {key: (sum(vals, ZERO) / len(vals)).quantize(FACTOR)
                        for key, vals in by_offset.items()}
    by_family: dict[tuple[str, int], list[Decimal]] = {}
    for (name, offset), vals in by_offset.items():
        by_family.setdefault((festival_family(name), offset), []).extend(vals)
    family_factors = {key: (sum(vals, ZERO) / len(vals)).quantize(FACTOR)
                      for key, vals in by_family.items()}

    def residual(day: date) -> Decimal | None:
        expected = mean * weekday[day.weekday()] * (month_end if is_month_end(day) else ONE)
        return totals[day] / expected if expected > 0 else None

    residuals = tuple(r for d in plain if (r := residual(d)) is not None)
    return SalesModel(level=level.quantize(Decimal("0.01")), weekday=tuple(weekday),
                      month_end=month_end, festival=festival_factors, residuals=residuals,
                      festivals=tuple(festivals), history_days=len(totals),
                      family=family_factors)
