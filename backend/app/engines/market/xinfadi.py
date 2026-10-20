"""China: Beijing Xinfadi wholesale market daily prices (WP-09).

The market's public price list (saved under `data/public/prices/xinfadi/`) has, per day, one row
per item, variety and origin with the lowest, highest and average wholesale price in yuan per
斤 (jin, 500 g). For each watched item the rows of one day become one point: the median of their
averages, with the lowest low and the highest high as the range.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from statistics import median

from app.contracts import Currency, DataMode, Money
from app.engines.market.points import MarketPrice
from app.engines.market.tcb import REPO_ROOT, Observation

XINFADI_DIR = REPO_ROOT / "data" / "public" / "prices" / "xinfadi"
SOURCE_URL = "http://www.xinfadi.com.cn/priceDetail.html"
MARKET = "Beijing Xinfadi"
CENT = Decimal("0.01")

# file -> (our item key, Xinfadi product name, required spec or None for any)
ITEMS: dict[str, tuple[str, str, str | None]] = {
    "potato.json": ("potato", "土豆", ""),
    "garlic.json": ("garlic", "大蒜", "干"),
    "egg.json": ("egg_loose", "散鸡蛋", None),
    "chinese_cabbage.json": ("chinese_cabbage", "大白菜", None),
    "cabbage.json": ("cabbage", "圆白菜", None),
    "carrot.json": ("carrot", "胡萝卜", "洗"),
}


def _decimal(value: object) -> Decimal | None:
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return number if number.is_finite() and number > 0 else None


def parse_answer(answer: dict, file_name: str) -> list[Observation]:
    commodity, name, spec = ITEMS[file_name]
    days: dict[date, list[tuple[Decimal, Decimal, Decimal, int]]] = defaultdict(list)
    for row in answer.get("list", []):
        if row.get("prodName") != name or row.get("unitInfo") != "斤":
            continue
        if spec is not None and (row.get("specInfo") or "") != spec:
            continue
        low, high, avg = (_decimal(row.get(k)) for k in ("lowPrice", "highPrice", "avgPrice"))
        if low is None or high is None or avg is None or not low <= avg <= high:
            continue
        try:
            day = date.fromisoformat(str(row["pubDate"])[:10])
        except (KeyError, ValueError):
            continue
        days[day].append((low, high, avg, int(row.get("id") or 0)))
    found = []
    for day, rows in sorted(days.items()):
        mid = Decimal(median(r[2] for r in rows)).quantize(CENT, rounding=ROUND_HALF_UP)
        point = MarketPrice(
            commodity=commodity, unit="jin", price=Money.of(mid, Currency.CNY),
            low=Money.of(min(r[0] for r in rows).quantize(CENT), Currency.CNY),
            high=Money.of(max(r[1] for r in rows).quantize(CENT), Currency.CNY),
            market=MARKET, source="xinfadi", source_url=SOURCE_URL, observed_on=day,
            data_mode=DataMode.public)
        ids = ",".join(str(r[3]) for r in sorted(rows, key=lambda r: r[3]))
        found.append(Observation(point, f"xinfadi:{file_name}#{day.isoformat()}:{ids}", day))
    return found


def load_directory(directory: Path = XINFADI_DIR) -> list[Observation]:
    found: list[Observation] = []
    for file_name in ITEMS:
        path = directory / file_name
        if path.exists():
            found += parse_answer(json.loads(path.read_text(encoding="utf-8")), file_name)
    return sorted(found, key=lambda o: (o.point.commodity, o.point.observed_on))
