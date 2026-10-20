"""China: NBS 10-day national prices of important production materials (WP-09).

Each release of 国家统计局 "流通领域重要生产资料市场价格变动情况" (saved under
`data/public/prices/nbs/`) gives, for 50 items, this period's national average price in yuan and
its change against the previous period. A release adds a point for its period (dated the 10th,
20th or last day of the month for 上旬/中旬/下旬) and one for the previous period (price minus
change). When two releases give the same period, the release whose own period it is wins.
"""

from __future__ import annotations

import calendar
import html
import re
from collections.abc import Iterable
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.contracts import Currency, DataMode, Money
from app.engines.market.points import MarketPrice
from app.engines.market.tcb import REPO_ROOT, Observation

NBS_DIR = REPO_ROOT / "data" / "public" / "prices" / "nbs"
MARKET = "China (national average)"
CENT = Decimal("0.01")

# NBS item name prefix -> (our item key, unit)
ITEMS: dict[str, tuple[str, str]] = {
    "螺纹钢": ("rebar", "metric_ton"),
    "普通硅酸盐水泥": ("cement", "metric_ton"),
    "浮法平板玻璃": ("float_glass", "metric_ton"),
    "稻米": ("rice_japonica", "metric_ton"),
    "小麦": ("wheat", "metric_ton"),
    "玉米": ("corn", "metric_ton"),
    "大豆": ("soybean", "metric_ton"),
    "白糖": ("sugar_white", "metric_ton"),
    "花生": ("peanut", "metric_ton"),
    "尿素": ("urea", "metric_ton"),
    "柴油": ("diesel", "metric_ton"),
}
_UNITS = {"吨": "metric_ton", "千克": "kg"}
_PERIOD = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*([上中下])旬\s*流通领域")
_NUMBER = r"(-?\d+(?:\.\d+)?)"


def _text(page: str) -> str:
    page = re.sub(r"<(script|style)\b.*?</\1>", " ", page, flags=re.S | re.I)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page)))


def period_end(year: int, month: int, part: str) -> date:
    if part == "上":
        return date(year, month, 10)
    if part == "中":
        return date(year, month, 20)
    return date(year, month, calendar.monthrange(year, month)[1])


def previous_period(day: date) -> date:
    if day.day == 20:
        return day.replace(day=10)
    if day.day == 10:
        last = day.replace(day=1).toordinal() - 1
        return date.fromordinal(last)
    return day.replace(day=20)


class NbsFormatError(ValueError):
    """The page is not an NBS production-materials price release."""


def parse_release(page: str, file_name: str, published_on: date,
                  source_url: str | None = None) -> list[tuple[Observation, bool]]:
    """(observation, is_own_period) for each watched item: this period and the previous one."""
    text = _text(page)
    found = _PERIOD.search(text)
    if found is None:
        raise NbsFormatError("no 'YYYY年M月X旬流通领域…' title")
    day = period_end(int(found.group(1)), int(found.group(2)), found.group(3))
    table = text[found.end():]
    rows = []
    for prefix, (commodity, unit) in ITEMS.items():
        match = re.search(re.escape(prefix) + r"[^吨元]{0,80}?\s(吨|千克)\s"
                          + _NUMBER + r"\s" + _NUMBER + r"\s" + _NUMBER, table)
        if match is None or _UNITS[match.group(1)] != unit:
            continue
        try:
            price, change = Decimal(match.group(2)), Decimal(match.group(3))
        except InvalidOperation:
            continue
        for when, value, own, column in ((day, price, True, "current"),
                                         (previous_period(day), price - change, False,
                                          "previous")):
            if value <= 0:
                continue
            point = MarketPrice(
                commodity=commodity, unit=unit,
                price=Money.of(value.quantize(CENT), Currency.CNY), market=MARKET,
                source="nbs", source_url=source_url, observed_on=when,
                data_mode=DataMode.public)
            rows.append((Observation(point, f"nbs:{file_name}#{commodity}:{column}",
                                     published_on), own))
    return rows


def merge(rows: Iterable[tuple[Observation, bool]]) -> list[Observation]:
    """One observation per (item, period): the release of that period first, then the newest."""
    best: dict[tuple[str, date], tuple[Observation, bool]] = {}
    for obs, own in rows:
        key = (obs.point.commodity, obs.point.observed_on)
        current = best.get(key)
        if current is None or (own, obs.published_on) > (current[1], current[0].published_on):
            best[key] = (obs, own)
    return sorted((obs for obs, _ in best.values()),
                  key=lambda o: (o.point.commodity, o.point.observed_on))


def load_directory(directory: Path = NBS_DIR) -> list[Observation]:
    rows: list[tuple[Observation, bool]] = []
    for path in sorted(directory.glob("t*_*.html")):
        stamp = path.stem[1:9]  # tYYYYMMDD_nnn
        published = date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8]))
        url = f"https://www.stats.gov.cn/sj/zxfb/{stamp[:6]}/{path.name}"
        rows += parse_release(path.read_text(encoding="utf-8", errors="replace"), path.name,
                              published, url)
    return merge(rows)
