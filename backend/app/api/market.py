"""Market API (WP-09, FEATURES N3): public Dhaka retail prices and price alerts.

    GET /api/market/prices   -> [WatchItem]   latest TCB price, baseline, change, 6-week history
    GET /api/market/alerts   -> [MarketAlert] moves past +/-5% of the baseline
    POST /api/market/vendors/rank {commodity, quantity}
                             -> [VendorRank]     suppliers by landed cost per unit
    POST /api/market/negotiate {commodity, quantity, offer_price, payment_days}
                             -> NegotiationPlan  walk-away, target, script (N19)

Shapes follow `web/src/api/types.ts` (WatchItem, MarketAlert), plus a few fields the web may
show: `published_on` (the TCB list's date; the screen says "published on", never "live"),
`baseline_basis` ("median_4w", or "previous" when fewer than 4 points fall in the 4 weeks
before the latest) and `baseline_points`. Prices come only from the TCB lists saved under
`data/public/prices/tcb/` (source, URL and date on every point); with no list saved the API
abstains with 422 `not_enough_data` (`missing: price_snapshot`). A commodity with only one
point has no baseline and is left out rather than shown with a made-up one.

Negotiation prices a sale against today's TCB price for the item (the shop's cash price) and
the shop's cost of money: the lowest effective APR among the WP-06 financing options it passes
eligibility for, for a working-capital need the size of the deal over max(payment_days, 30) days.
With no eligible option, or no TCB price for the item, it abstains with 422 `not_enough_data`
(`missing: eligible_financing` / `market_price`). The answer also carries `cost_of_money` (that
APR as a Figure) and `market_price` (the TCB point used).

Vendor ranking (demo shops only): the shop's main ledger suppliers, labelled "Supplier N" (stable
per shop), with generated quotes (`data_mode: synthetic`, `source: "ledger_supplier"`) around
today's TCB price, ranked by landed cost at the same cost of money; reliability is the share of
each supplier's bills the shop settled on time. A shop whose ledger is not synthetic (a
self-service shop) has no quotes on record: 422 `not_enough_data` (`missing: supplier_quote`).

The caller is the signed-in principal with `ledger:read`. Prices are public, the same for every
shop. Alert figures are recorded in the caller's tenant ledger (formula + figure, no raw fact,
so the shop's ledger revision does not move) so `/api/explain/{figure_id}` opens them.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api import financing as financing_api
from app.contracts import (
    ApiError,
    DataMode,
    EligibilityStatus,
    Figure,
    FinancingNeed,
    FormulaRef,
    Money,
    PricePoint,
    PriceSource,
    Principal,
    Provenance,
    Unit,
    VendorQuote,
)
from app.engines.analysis.ledger import NotEnoughData
from app.engines.analysis.store import records
from app.engines.financing.catalogue import load_catalogue
from app.engines.financing.ranking import match as rank_options
from app.engines.market import negotiate as negotiate_mod
from app.engines.market import tcb, vendors, watch
from app.facts import FactStore
from app.facts.provenance import combined_data_mode
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


class NegotiationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    commodity: str = Field(max_length=40)
    quantity: str = Field(max_length=20)
    offer_price: Money
    payment_days: int = Field(ge=0, le=180)


class VendorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    commodity: str = Field(max_length=40)
    quantity: str = Field(max_length=20)


class VendorRank(BaseModel):
    rank: int
    vendor_label: str
    quote: VendorQuote
    landed_cost: Figure
    breakdown: list[Figure]
    source: Literal["ledger_supplier"] = "ledger_supplier"


class NegotiationStep(BaseModel):
    text_key: str
    figures: list[Figure]


class NegotiationPlan(BaseModel):
    walk_away: Figure
    target: Figure
    steps: list[NegotiationStep]
    cost_of_money: Figure
    market_price: PricePoint


@lru_cache(maxsize=4)
def _cached(directory: str, stamp: tuple[tuple[str, int], ...]) -> tuple[tcb.Observation, ...]:
    return tuple(tcb.load_directory(Path(directory)))


def observations(directory: Path | None = None) -> tuple[tcb.Observation, ...]:
    """Every saved TCB point, re-read only when a file in the folder changes."""
    folder = directory or PRICE_DIR
    files = sorted(folder.glob("*.xlsx")) if folder.is_dir() else []
    stamp = tuple((f.name, f.stat().st_mtime_ns) for f in files)
    return _cached(str(folder), stamp) if files else ()


def _abstain(missing: str = "price_snapshot") -> JSONResponse:
    body = ApiError(code="not_enough_data", message_key="error.not_enough_data",
                    detail={"missing": missing})
    return JSONResponse(status_code=422, content=body.model_dump(mode="json"))


def _invalid(what: str) -> JSONResponse:
    body = ApiError(code=f"invalid_{what}", message_key=f"error.invalid_{what}")
    return JSONResponse(status_code=422, content=body.model_dump(mode="json"))


def _quantity(raw: str) -> Decimal | None:
    try:
        value = Decimal(raw.strip())
    except InvalidOperation:
        return None
    return value if value.is_finite() and value > 0 else None


def _record(store: FactStore, tenant_id: str, figure: Figure,
            expressions: dict[str, str]) -> Figure:
    """Record the formula and the figure in the tenant ledger, so /api/explain opens it."""
    formula_id = figure.provenance.formula_id
    store.put_formula(FormulaRef(formula_id=formula_id, version=1,
                                 expression=expressions[formula_id]))
    return store.put_figure(tenant_id, figure.model_copy(
        update={"id": f"{tenant_id}:{figure.id}"}))


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
        recorded = _record(store, principal.tenant_id, figure, watch.EXPRESSIONS)
        point = row.latest.point
        found.append(MarketAlert(
            id=f"mk-{point.commodity}-{point.observed_on.isoformat()}",
            commodity=point.commodity, direction="rise" if figure.value > 0 else "drop",
            change=recorded, observed_on=point.observed_on, source=point.source,
            source_url=point.source_url, published_on=row.latest.published_on))
    return found


COST_OF_MONEY = "market.cost_of_money"
COST_OF_MONEY_EXPRESSION = ("lowest effective APR among the financing options the shop passes "
                            "eligibility for (WP-06)")


def cost_of_money(session: Session, tenant_id: str, amount: Money, days: int,
                  as_of: date) -> tuple[Decimal, str, DataMode] | None:
    """(best eligible effective APR in percent, product id, data mode), or None if none passes."""
    products = load_catalogue()
    facts, modes = financing_api._facts(FactStore(session), tenant_id, products, as_of)
    need = FinancingNeed(tenant_id=tenant_id, amount=amount, needed_by=as_of,
                         tenor_days=max(days, 30))
    eligible = [c.option for c in rank_options(need, products, facts, start=as_of)
                if c.option.eligibility.status is EligibilityStatus.pass_]
    if not eligible:
        return None
    best = min(eligible, key=lambda option: (option.effective_apr, option.product.id))
    mode = combined_data_mode([*modes, best.product.data_mode]) if modes \
        else best.product.data_mode
    return best.effective_apr, best.product.id, mode


@router.post("/negotiate", response_model=NegotiationPlan)
def negotiate(body: NegotiationBody,
              principal: Principal = Depends(require(Permission.ledger_read)),
              clock: Clock = Depends(get_clock),
              session: Session = Depends(get_session)) -> NegotiationPlan | JSONResponse:
    quantity = _quantity(body.quantity)
    if quantity is None:
        return _invalid("quantity")
    if body.offer_price.amount <= 0:
        return _invalid("offer")
    rows = _rows(clock)
    if rows is None:
        return _abstain()
    row = next((r for r in rows if r.commodity == body.commodity), None)
    if row is None:
        return _abstain("market_price")
    as_of = clock().astimezone(DHAKA).date()
    deal = Money.of((body.offer_price.amount * quantity).quantize(Decimal("0.01")))
    found = cost_of_money(session, principal.tenant_id, deal, body.payment_days, as_of)
    if found is None:
        return _abstain("eligible_financing")
    apr, product_id, money_mode = found
    mode = combined_data_mode([money_mode, row.latest.point.data_mode])
    plan = negotiate_mod.plan(market=row.latest.point, market_ref=row.latest.ref,
                              offer=body.offer_price.amount, quantity=quantity,
                              payment_days=body.payment_days, apr_percent=apr,
                              apr_ref=f"financing:{product_id}", data_mode=mode)
    store = FactStore(session)
    expressions = {**negotiate_mod.EXPRESSIONS, COST_OF_MONEY: COST_OF_MONEY_EXPRESSION}

    def record(fig: Figure) -> Figure:
        return _record(store, principal.tenant_id, fig, expressions)

    apr_figure = Figure(
        id=f"market:cost_of_money:{product_id}:{deal.amount}:{max(body.payment_days, 30)}:"
           f"{as_of.isoformat()}",
        label_key="market.cost_of_money", value=apr, unit=Unit.percent, data_mode=money_mode,
        provenance=Provenance(formula_id=COST_OF_MONEY, formula_version=1,
                              source_row_ids=(f"financing:{product_id}",),
                              parameters={"product_id": product_id,
                                          "amount": str(deal.amount),
                                          "tenor_days": str(max(body.payment_days, 30))}))
    return NegotiationPlan(
        walk_away=record(plan.walk_away), target=record(plan.target),
        steps=[NegotiationStep(text_key=step.text_key,
                               figures=[record(fig) for fig in step.figures])
               for step in plan.steps],
        cost_of_money=record(apr_figure), market_price=row.latest.point)


@router.post("/vendors/rank", response_model=list[VendorRank])
def rank_vendors(body: VendorBody,
                 principal: Principal = Depends(require(Permission.ledger_read)),
                 clock: Clock = Depends(get_clock),
                 session: Session = Depends(get_session)) -> list[VendorRank] | JSONResponse:
    quantity = _quantity(body.quantity)
    if quantity is None:
        return _invalid("quantity")
    rows = _rows(clock)
    if rows is None:
        return _abstain()
    row = next((r for r in rows if r.commodity == body.commodity), None)
    if row is None:
        return _abstain("market_price")
    store = FactStore(session)
    try:
        bills = records(store, principal.tenant_id).bills
    except NotEnoughData:
        bills = ()
    if not bills or any(bill.data_mode is not DataMode.synthetic for bill in bills):
        return _abstain("supplier_quote")  # quotes are generated only for the demo shops
    as_of = clock().astimezone(DHAKA).date()
    point = row.latest.point
    deal = Money.of((point.price.amount * quantity).quantize(Decimal("0.01")))
    found = cost_of_money(session, principal.tenant_id, deal, 30, as_of)
    if found is None:
        return _abstain("eligible_financing")
    apr, product_id, money_mode = found
    labels = {token: f"Supplier {i}" for i, token in
              enumerate(sorted({b.counterparty_token for b in bills}), start=1)}
    quotes = vendors.synthetic_quotes(principal.tenant_id, vendors.main_suppliers(bills),
                                      point.commodity, point.unit, point.price, bills, as_of)
    ranked = vendors.rank(quotes, labels, quantity, apr, f"financing:{product_id}",
                          combined_data_mode([money_mode, DataMode.synthetic]))

    def record(fig: Figure) -> Figure:
        return _record(store, principal.tenant_id, fig, vendors.EXPRESSIONS)

    return [VendorRank(rank=r.rank, vendor_label=r.label, quote=r.quote,
                       landed_cost=record(r.landed_cost),
                       breakdown=[record(f) for f in r.breakdown]) for r in ranked]
