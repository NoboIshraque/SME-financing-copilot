"""Market API (WP-09, FEATURES N3): public Dhaka retail prices and price alerts.

    GET /api/market/prices   -> [WatchItem]   latest TCB price, baseline, change, 6-week history
    GET /api/market/alerts   -> [MarketAlert] moves past +/-5% of the baseline

Shapes follow `web/src/api/types.ts` (WatchItem, MarketAlert), plus a few fields the web may
show: `published_on` (the TCB list's date; the screen says "published on", never "live"),
`baseline_basis` ("median_4w", or "previous" when fewer than 4 points fall in the 4 weeks
before the latest) and `baseline_points`. Prices come only from the TCB lists saved under
`data/public/prices/tcb/` (source, URL and date on every point); with no list saved the API
abstains with 422 `not_enough_data` (`missing: price_snapshot`). A commodity with only one
point has no baseline and is left out rather than shown with a made-up one.

The caller is the signed-in principal with `ledger:read`. Prices are public, the same for every
shop. Alert figures are recorded in the caller's tenant ledger (formula + figure, no raw fact,
so the shop's ledger revision does not move) so `/api/explain/{figure_id}` opens them.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.contracts import ApiError, Figure, FormulaRef, Money, PricePoint, PriceSource, Principal
from app.engines.market import tcb, watch
from app.facts import FactStore
from app.main import get_session
from app.security.clock import Clock
from app.security.deps import get_clock, require
from app.security.errors import ProblemRoute
from app.security.roles import Permission

router = APIRouter(prefix="/market", tags=["market"], route_class=ProblemRoute)
DHAKA = ZoneInfo("Asia/Dhaka")
PRICE_DIR = tcb.TCB_DIR


class WatchItem(BaseModel):
    commodity: str
    unit: str
    latest: PricePoint
    median_4w: Money
    change_pct: str
    history: list[PricePoint]
    published_on: date
    baseline_basis: Literal["median_4w", "previous"]
    baseline_points: int


class MarketAlert(BaseModel):
    id: str
    commodity: str
    direction: Literal["drop", "rise"]
    change: Figure
    observed_on: date
    source: PriceSource
    source_url: str | None
    published_on: date


@lru_cache(maxsize=4)
def _cached(directory: str, stamp: tuple[tuple[str, int], ...]) -> tuple[tcb.Observation, ...]:
    return tuple(tcb.load_directory(Path(directory)))


def observations(directory: Path | None = None) -> tuple[tcb.Observation, ...]:
    """Every saved TCB point, re-read only when a file in the folder changes."""
    folder = directory or PRICE_DIR
    files = sorted(folder.glob("*.xlsx")) if folder.is_dir() else []
    stamp = tuple((f.name, f.stat().st_mtime_ns) for f in files)
    return _cached(str(folder), stamp) if files else ()


def _abstain() -> JSONResponse:
    body = ApiError(code="not_enough_data", message_key="error.not_enough_data",
                    detail={"missing": "price_snapshot"})
    return JSONResponse(status_code=422, content=body.model_dump(mode="json"))


def _rows(clock: Clock) -> list[watch.Watch] | None:
    found = observations()
    if not found:
        return None
    today = clock().astimezone(DHAKA).date()
    return [row for row in watch.watchlist(found, today) if row.baseline is not None]


@router.get("/prices", response_model=list[WatchItem])
def prices(_principal: Principal = Depends(require(Permission.ledger_read)),
           clock: Clock = Depends(get_clock)) -> list[WatchItem] | JSONResponse:
    rows = _rows(clock)
    if rows is None:
        return _abstain()
    return [WatchItem(commodity=row.commodity, unit=row.unit, latest=row.latest.point,
                      median_4w=row.baseline.price, change_pct=str(row.change_pct),
                      history=list(row.history), published_on=row.latest.published_on,
                      baseline_basis=row.baseline.basis,  # type: ignore[arg-type]
                      baseline_points=len(row.baseline.refs))
            for row in rows if row.baseline is not None]


@router.get("/alerts", response_model=list[MarketAlert])
def alerts(principal: Principal = Depends(require(Permission.ledger_read)),
           clock: Clock = Depends(get_clock),
           session: Session = Depends(get_session)) -> list[MarketAlert] | JSONResponse:
    rows = _rows(clock)
    if rows is None:
        return _abstain()
    store = FactStore(session)
    found = []
    for row, figure in watch.alerts(rows):
        store.put_formula(FormulaRef(formula_id=figure.provenance.formula_id, version=1,
                                     expression=watch.EXPRESSIONS[figure.provenance.formula_id]))
        recorded = store.put_figure(principal.tenant_id, figure.model_copy(
            update={"id": f"{principal.tenant_id}:{figure.id}"}))
        point = row.latest.point
        found.append(MarketAlert(
            id=f"mk-{point.commodity}-{point.observed_on.isoformat()}",
            commodity=point.commodity, direction="rise" if figure.value > 0 else "drop",
            change=recorded, observed_on=point.observed_on, source=point.source,
            source_url=point.source_url, published_on=row.latest.published_on))
    return found
