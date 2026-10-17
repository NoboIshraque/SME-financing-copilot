"""Load financing catalogues from data/public/financing/*.yaml (WP-06 milestone 1).

Every real loan row must carry `source_url` and `checked_on` (the contract enforces it).
Modelled rows (e.g. the P14 China pack) are labelled `is_modelled: true` and shown as such.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.contracts import DataMode, EligibilityRule, Fee, FinancingProduct, Money

REPO_ROOT = Path(__file__).resolve().parents[4]
CATALOGUE_DIR = REPO_ROOT / "data" / "public" / "financing"


class CatalogueError(ValueError):
    pass


def _money(value: Any) -> Money | None:
    return None if value is None else Money.of(Decimal(str(value)))


def parse_product(row: dict[str, Any], default_mode: DataMode) -> FinancingProduct:
    known = {"id", "provider", "name", "kind", "rate_type", "nominal_rate_pa", "fees",
             "min_amount", "max_amount", "min_tenor_days", "max_tenor_days",
             "collateral_required", "rules", "source_url", "checked_on", "is_modelled",
             "data_mode", "evidence_quote", "notes", "eligibility_text"}
    unknown = set(row) - known
    if unknown:
        raise CatalogueError(f"{row.get('id')}: unknown fields {sorted(unknown)}")
    checked = row.get("checked_on")
    return FinancingProduct(
        id=row["id"],
        provider=row["provider"],
        name=row["name"],
        kind=row["kind"],
        rate_type=row["rate_type"],
        nominal_rate_pa=Decimal(str(row["nominal_rate_pa"])),
        fees=tuple(Fee(**{**f, "value": Decimal(str(f["value"]))}) for f in row.get("fees", [])),
        min_amount=_money(row.get("min_amount")),
        max_amount=_money(row.get("max_amount")),
        min_tenor_days=row.get("min_tenor_days"),
        max_tenor_days=row.get("max_tenor_days"),
        collateral_required=bool(row.get("collateral_required", False)),
        rules=tuple(
            EligibilityRule(**{**r, "threshold": None if r.get("threshold") is None
                               else Decimal(str(r["threshold"]))})
            for r in row.get("rules", [])
        ),
        source_url=row.get("source_url"),
        checked_on=checked if isinstance(checked, date) or checked is None
        else date.fromisoformat(checked),
        is_modelled=bool(row.get("is_modelled", False)),
        data_mode=row.get("data_mode", default_mode),
    )


def load_file(path: Path) -> list[FinancingProduct]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    mode = DataMode(data.get("data_mode", "public"))
    products = [parse_product(row, mode) for row in data["products"]]
    ids = [p.id for p in products]
    if len(ids) != len(set(ids)):
        raise CatalogueError(f"{path.name}: duplicate product ids")
    return products


@lru_cache(maxsize=4)
def load_catalogue(directory: Path = CATALOGUE_DIR, jurisdiction: str = "bd") -> tuple:
    path = directory / f"{jurisdiction}.yaml"
    if not path.exists():
        raise CatalogueError(f"no catalogue for {jurisdiction!r}")
    return tuple(load_file(path))
