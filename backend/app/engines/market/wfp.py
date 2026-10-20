"""WFP Bangladesh market prices (HDX, CC BY-IGO) -> price points per market (WP-09).

WFP's market monitoring publishes retail prices for about 100 markets in all eight divisions,
once a month (dated the 15th). Only rows WFP flags `actual` (observed in that market, not a
division average) and priced in taka are read, for the inputs below. Eggs are priced per piece
here (TCB prices them per hali of 4), so they are a separate item, not converted.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from app.contracts import DataMode, Money
from app.engines.market.locations import WFP_DIR
from app.engines.market.points import MarketPrice
from app.engines.market.tcb import Observation

SOURCE_URL = "https://data.humdata.org/dataset/wfp-food-prices-for-bangladesh"
CENT = Decimal("0.01")

# WFP commodity -> (our item key, unit)
ITEMS: dict[str, tuple[str, str]] = {
    "Rice (coarse)": ("rice_coarse", "kg"),
    "Wheat flour": ("atta_loose", "kg"),
    "Lentils (masur)": ("lentil_masur", "kg"),
    "Oil (soybean, fortified)": ("soybean_oil", "litre"),
    "Oil (palm)": ("palm_oil", "litre"),
    "Sugar": ("sugar", "kg"),
    "Eggs (brown)": ("egg_piece", "piece"),
    "Garlic (imported, China)": ("garlic_imported", "kg"),
    "Chili (green)": ("chili_green", "kg"),
    "Potatoes (Holland, white)": ("potato", "kg"),
    "Onions (imported, China)": ("onion_imported", "kg"),
    "Meat (chicken, broiler)": ("chicken_broiler", "kg"),
}


def parse_rows(rows: list[dict[str, str]]) -> dict[str, list[Observation]]:
    """Observations per location id ("wfp-<market_id>"), one per item and month."""
    found: dict[str, dict[tuple[str, date], Observation]] = defaultdict(dict)
    for row in rows:
        if row.get("date", "").startswith("#") or row.get("pricetype") != "Retail":
            continue
        if row.get("priceflag") != "actual" or row.get("currency") != "BDT":
            continue
        item = ITEMS.get(row.get("commodity", ""))
        if item is None:
            continue
        try:
            price = Decimal(row["price"])
            day = date.fromisoformat(row["date"])
        except (ArithmeticError, ValueError):
            continue
        if price <= 0:
            continue
        commodity, unit = item
        point = MarketPrice(
            commodity=commodity, unit=unit,
            price=Money.of(price.quantize(CENT, rounding=ROUND_HALF_UP)),
            market=row["market"].strip(), source="wfp", source_url=SOURCE_URL,
            observed_on=day, data_mode=DataMode.public)
        ref = f"wfp:{row['market_id']}:{row['commodity_id']}:{day.isoformat()}"
        found[f"wfp-{row['market_id']}"][(commodity, day)] = Observation(point, ref, day)
    return {loc: sorted(obs.values(), key=lambda o: (o.point.commodity, o.point.observed_on))
            for loc, obs in found.items()}


def load_directory(directory: Path = WFP_DIR) -> dict[str, list[Observation]]:
    path = directory / "wfp_food_prices_bgd.csv"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as handle:
        return parse_rows(list(csv.DictReader(handle)))
