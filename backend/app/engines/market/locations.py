"""Where prices come from, and how far apart two places are (WP-09).

A location is a market with public prices. Bangladesh: Dhaka city (TCB's daily list, collected
in seven Dhaka markets) or one of WFP's monitored markets (monthly, with coordinates from
`wfp_markets_bgd.csv`). China: the national average (NBS, every 10 days, yuan) or Beijing
Xinfadi wholesale market (daily, yuan per jin). The owner picks one; prices, alerts and the
negotiation's market price then come from it, and vendors are ranked by road distance from it.

Distance is the great-circle distance times ROAD_FACTOR (roads are not straight; 1.3 is a
common rule of thumb, stated in every figure that uses it).
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from app.engines.market.tcb import REPO_ROOT

WFP_DIR = REPO_ROOT / "data" / "public" / "prices" / "wfp"
EARTH_RADIUS_KM = 6371.0
ROAD_FACTOR = Decimal("1.3")


@dataclass(frozen=True)
class Location:
    id: str  # "tcb-dhaka", "wfp-<market_id>", "cn-national", "cn-beijing-xinfadi"
    name: str
    division: str
    district: str
    latitude: float
    longitude: float
    source: str  # "tcb" | "wfp" | "nbs" | "xinfadi"
    cadence: str  # "daily" | "10-day" | "monthly"
    country: str = "BD"  # ISO 3166 alpha-2
    currency: str = "BDT"


# TCB collects in Mirpur-6, Mohammadpur, Malibagh, Rampura, Mohakhali, Hatirpool and Agargaon;
# the point is WFP's coordinates for its "Dhaka" market.
DHAKA_CITY = Location("tcb-dhaka", "Dhaka city", "Dhaka", "Dhaka", 23.81, 90.41, "tcb", "daily")
# NBS prices are national averages: the point (Beijing) is only where the list is published.
CHINA_NATIONAL = Location("cn-national", "China (national average)", "China", "China", 39.90,
                          116.40, "nbs", "10-day", "CN", "CNY")
BEIJING_XINFADI = Location("cn-beijing-xinfadi", "Beijing Xinfadi", "Beijing", "Fengtai", 39.80,
                           116.34, "xinfadi", "daily", "CN", "CNY")


def load_wfp_markets(directory: Path = WFP_DIR) -> dict[str, Location]:
    """WFP's market list, keyed by location id. Division-level aggregates are left out."""
    path = directory / "wfp_markets_bgd.csv"
    if not path.exists():
        return {}
    found = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["market_id"].startswith("#") or row["market"].endswith(" Division"):
                continue
            try:
                lat, lon = float(row["latitude"]), float(row["longitude"])
            except ValueError:
                continue
            location = Location(f"wfp-{row['market_id']}", row["market"].strip(),
                                row["admin1"].strip(), row["admin2"].strip(), lat, lon,
                                "wfp", "monthly")
            found[location.id] = location
    return found


def distance_km(a: Location, b: Location) -> Decimal:
    """Road distance estimate: great-circle distance * ROAD_FACTOR, rounded to 1 km."""
    lat1, lon1, lat2, lon2 = map(math.radians, (a.latitude, a.longitude, b.latitude, b.longitude))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    straight = 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))
    return (Decimal(str(round(straight, 3))) * ROAD_FACTOR).quantize(Decimal(1))
