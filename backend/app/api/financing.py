"""Financing API (WP-06 milestone 8; FEATURES P1, N20, P14).

    POST /api/financing/match              {amount, needed_by, tenor_days, purpose_key?,
                                            jurisdiction?, tenant_id?}     -> MatchResult
    GET  /api/financing/lenders/{lender_id}                                -> LenderProfile
    POST /api/financing/applications       {product_id, ...the need}       -> ActionCard

Shapes follow what the web expects (`web/src/api/types.ts` FinancingMatch): the match answer
carries the lender profile of every provider ranked and the application draft for the best
option that passes eligibility (null when none passes or the caller may not draft).

The caller is the signed-in principal (WP-11) and needs `ledger:read`; the tenant always comes
from the principal. A `tenant_id` in the body is optional and must then be the caller's own
(403 otherwise). `purpose_key` may carry the web's `purpose.` prefix. Eligibility reads the
tenant's typed facts as of today (Dhaka): a fact the ledger does not hold is passed on as
missing, so the rule answers "not on record" instead of guessing. Every number in a response
comes from the WP-06 engines.

Fit uses the tenant's WP-04 cash forecast band (the cash API's cached analysis, default buffer);
when the cash engine abstains (too little history), options are ranked without the fit term and
carry the reason `fit.no_forecast`. Until WP-08 stores verified loans, no lender has a track record:
`lender_events` is the one seam that supplies them. No lender licence registry is loaded yet, so
licence status is reported as `unknown` (never assumed).

Drafting an application is DRAFT tier (`draft_loan_application`: it stays inside DecisionGuard). The
card it returns is `submit_loan_application`, EXECUTE tier (sending it to the lender commits the
business): it goes to the owner through `POST /api/approvals` and needs a step-up code.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api import cash as cash_api
from app.contracts import (
    ActionCard,
    ActionType,
    ApiError,
    DataMode,
    EligibilityStatus,
    FinancingNeed,
    FinancingOption,
    FinancingProduct,
    ForecastBand,
    LenderProfile,
    LicenceStatus,
    Money,
    Principal,
)
from app.engines.financing.application import draft_application
from app.engines.financing.catalogue import load_catalogue, load_unpriced
from app.engines.financing.lenders import LenderEvent, build_profile
from app.engines.financing.ranking import match as rank_options
from app.facts import FactStore
from app.main import get_session
from app.security import policy
from app.security.approvals import issue_cards
from app.security.clock import Clock
from app.security.deps import get_clock, require
from app.security.errors import ProblemRoute, forbidden
from app.security.roles import Permission

router = APIRouter(prefix="/financing", tags=["financing"], route_class=ProblemRoute)

DHAKA = ZoneInfo("Asia/Dhaka")
EXTRA_FACTS = ("collateral_available",)  # read by approval likelihood, not by a product rule
# Most cautious label wins: synthetic data is always labelled synthetic.
_MODE_ORDER = (DataMode.synthetic, DataMode.real_anonymised, DataMode.live, DataMode.public)


class NeedBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str | None = Field(default=None, max_length=128)
    amount: Money
    needed_by: date
    tenor_days: int = Field(ge=1, le=3650)
    purpose_key: str = Field(default="working_capital", max_length=64)
    jurisdiction: Literal["bd", "cn"] = "bd"


class ApplicationBody(NeedBody):
    product_id: str = Field(max_length=128)


class AskTheLender(BaseModel):
    """A real product whose provider publishes no rate: listed, never ranked."""

    id: str
    provider: str
    name: str
    kind: str
    source_url: str
    checked_on: date
    max_amount: Money | None
    notes: str


class MatchResult(BaseModel):
    need: FinancingNeed
    as_of: date
    options: list[FinancingOption]
    lenders: list[LenderProfile]
    application: ActionCard | None
    ask_the_lender: list[AskTheLender]
    facts_missing: list[str]
    data_mode: DataMode


def lender_events() -> tuple[LenderEvent, ...]:
    """Peer-verified lender events (WP-08). None are stored yet."""
    return ()


def _error(status: int, code: str, message_key: str, **detail: str) -> JSONResponse:
    body = ApiError(code=code, message_key=message_key, detail=detail)
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"))


def _today(clock: Clock) -> date:
    return clock().astimezone(DHAKA).date()


def _mode(modes: Iterable[DataMode]) -> DataMode:
    present = set(modes)
    return next((m for m in _MODE_ORDER if m in present), DataMode.public)


def _need(body: NeedBody, principal: Principal) -> FinancingNeed:
    if body.tenant_id is not None and body.tenant_id != principal.tenant_id:
        raise forbidden("tenant")
    return FinancingNeed(tenant_id=principal.tenant_id, amount=body.amount,
                         needed_by=body.needed_by, tenor_days=body.tenor_days,
                         purpose_key=body.purpose_key.removeprefix("purpose."))


def _facts(store: FactStore, tenant_id: str, products: Sequence[FinancingProduct],
           as_of: date) -> tuple[dict[str, Decimal | None], set[DataMode]]:
    metrics = sorted({rule.metric for p in products for rule in p.rules} | set(EXTRA_FACTS))
    values: dict[str, Decimal | None] = {}
    modes: set[DataMode] = set()
    for metric in metrics:
        fact = store.latest(tenant_id, metric, as_of)
        values[metric] = fact.value if fact is not None else None
        if fact is not None:
            modes.add(fact.data_mode)
    return values, modes


def _profile(lender_id: str, events: Sequence[LenderEvent],
             products: Sequence[FinancingProduct]) -> LenderProfile:
    own = [e for e in events if e.lender_id == lender_id]
    # verified loans exist only in the synthetic mesh today
    mode = DataMode.synthetic if own else _mode(p.data_mode for p in products)
    return build_profile(lender_id, lender_id, LicenceStatus.unknown, own, data_mode=mode)


def _profiles(events: Sequence[LenderEvent]) -> dict[str, LenderProfile]:
    """Profiles for lenders with a track record only (the rest rank as cold start)."""
    return {lender: _profile(lender, events, ())
            for lender in sorted({e.lender_id for e in events})}


def _past(need: FinancingNeed, as_of: date) -> JSONResponse | None:
    if need.needed_by >= as_of:
        return None
    return _error(422, "needed_by_in_past", "error.needed_by_in_past", as_of=as_of.isoformat())


def _band(store: FactStore, tenant_id: str, now: datetime) -> ForecastBand | None:
    try:
        analysis = cash_api.analyse(store, tenant_id)
    except cash_api.Abstain:
        return None
    return analysis.plain.band(cash_api.buffer_for(analysis, None), now)


def _rank(need: FinancingNeed, body: NeedBody, as_of: date, session: Session,
          events: Sequence[LenderEvent], now: datetime):
    products = load_catalogue(jurisdiction=body.jurisdiction)
    store = FactStore(session)
    facts, modes = _facts(store, need.tenant_id, products, as_of)
    band = _band(store, need.tenant_id, now)
    candidates = rank_options(need, products, facts, start=need.needed_by, band=band,
                              lenders=_profiles(events))
    if band is not None:
        modes.add(band.data_mode)
    modes |= {p.data_mode for p in products}
    if events:
        modes.add(DataMode.synthetic)
    return facts, candidates, _mode(modes)


@router.post("/match", response_model=MatchResult)
def match(body: NeedBody,
          principal: Principal = Depends(require(Permission.ledger_read)),
          clock: Clock = Depends(get_clock),
          session: Session = Depends(get_session),
          events: tuple[LenderEvent, ...] = Depends(lender_events)) -> MatchResult | JSONResponse:
    as_of, need = _today(clock), _need(body, principal)
    if (problem := _past(need, as_of)) is not None:
        return problem
    facts, candidates, mode = _rank(need, body, as_of, session, events, clock())
    options = [c.option for c in candidates]
    providers = sorted({o.product.provider for o in options})
    lenders = [_profile(provider, events, [o.product for o in options
                                           if o.product.provider == provider])
               for provider in providers]
    best = next((o for o in options if o.eligibility.status is EligibilityStatus.pass_), None)
    may_draft = policy.decide(principal.role, ActionType.draft_loan_application).allowed
    draft = draft_application(best, need, facts, now=clock()) if best and may_draft else None
    unpriced = [AskTheLender(**vars(u)) for u in load_unpriced(jurisdiction=body.jurisdiction)]
    return MatchResult(need=need, as_of=as_of, options=options, lenders=lenders,
                       application=draft, ask_the_lender=unpriced,
                       facts_missing=sorted(m for m, v in facts.items() if v is None),
                       data_mode=mode)


@router.get("/lenders/{lender_id}", response_model=LenderProfile)
def lender(lender_id: str,
           _: Principal = Depends(require(Permission.ledger_read)),
           events: tuple[LenderEvent, ...] = Depends(lender_events)
           ) -> LenderProfile | JSONResponse:
    products = [p for j in ("bd", "cn") for p in load_catalogue(jurisdiction=j)
                if p.provider == lender_id]
    unpriced = [u for u in load_unpriced(jurisdiction="bd") if u.provider == lender_id]
    own = [e for e in events if e.lender_id == lender_id]
    if not (products or unpriced or own):
        return _error(404, "lender_not_found", "error.lender_not_found",
                      lender_id=lender_id[:128])
    return _profile(lender_id, own, products)


@router.post("/applications", response_model=ActionCard, status_code=201)
def application(body: ApplicationBody,
                principal: Principal = Depends(require(Permission.ledger_read)),
                clock: Clock = Depends(get_clock),
                session: Session = Depends(get_session),
                events: tuple[LenderEvent, ...] = Depends(lender_events)
                ) -> ActionCard | JSONResponse:
    if not policy.decide(principal.role, ActionType.draft_loan_application).allowed:
        raise forbidden("tier")
    as_of, need = _today(clock), _need(body, principal)
    if (problem := _past(need, as_of)) is not None:
        return problem
    facts, candidates, _ = _rank(need, body, as_of, session, events, clock())
    chosen = next((c.option for c in candidates if c.option.product.id == body.product_id), None)
    if chosen is None:
        return _error(404, "product_not_found", "error.product_not_found",
                      product_id=body.product_id[:128])
    if chosen.eligibility.status is EligibilityStatus.fail:
        return _error(422, "not_eligible", "error.not_eligible", product_id=body.product_id)
    card = draft_application(chosen, need, facts, now=clock())
    issue_cards(session, principal.tenant_id, (card,), clock())
    return card
