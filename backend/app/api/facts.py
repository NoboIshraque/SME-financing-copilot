"""Fact ledger API (WP-01 milestone 4).

    GET /api/facts/{metric}?tenant_id=&start=&end=&granularity=&entity=&compute=   -> Fact
    GET /api/explain/{figure_id}?tenant_id=                                         -> Explanation
    GET /api/explain/{figure_id}/rows?tenant_id=&offset=&limit=                     -> ExplainRows

Lookups are exact and scoped to the caller's tenant: another tenant's figure is reported like
an unknown one. A period must be calendar-aligned for its granularity (one day, seven days, a
calendar month, quarter or year). A stored figure is served only while it is current for the
tenant's ledger; otherwise it is recomputed (with compute=false it is reported as stale).
Source rows are masked for callers who may not see them. Errors are `ApiError` bodies.

The caller is the signed-in principal (WP-11 `current_principal`): without a session every
route answers 401. The tenant always comes from the principal; `tenant_id` in the query is
optional (kept for older clients) and must then name the caller's own tenant, or the answer is
403. A lender viewer sees only the tenant it was granted, with source rows masked.
"""

from __future__ import annotations

import calendar
from datetime import date

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.contracts import (
    ApiError,
    Bill,
    Explanation,
    Fact,
    Granularity,
    Invoice,
    Period,
    Principal,
    Transaction,
)
from app.facts import FactNotFound, FactStore
from app.facts.masking import get_masker
from app.facts.provenance import ProvenanceIncomplete, explain, explain_rows
from app.facts.provenance import compute as compute_fact
from app.facts.registry import REGISTRY, NotComputable
from app.main import get_session
from app.security.deps import current_principal, require
from app.security.errors import ProblemRoute, forbidden
from app.security.roles import Permission

router = APIRouter(tags=["facts"], route_class=ProblemRoute)
MAX_PAGE = 500
_ECHO = 128  # caller-supplied values echoed in error details are cut to this length


class ExplainRow(BaseModel):
    ref: str
    kind: str
    record: Transaction | Invoice | Bill | Fact | None = None


class ExplainRows(BaseModel):
    """A page of a figure's source rows resolved to records (API-local until WP-00 adopts it)."""

    figure_id: str
    total: int
    offset: int
    limit: int
    masked: bool
    rows: list[ExplainRow]


def current_caller(principal: Principal = Depends(current_principal),
                   tenant_id: str | None = None) -> Principal:
    """The signed-in caller. A `tenant_id` in the query must be the caller's own tenant."""
    if tenant_id is not None and tenant_id != principal.tenant_id:
        raise forbidden("tenant")
    return principal


def ledger_reader(principal: Principal = Depends(require(Permission.ledger_read)),
                  tenant_id: str | None = None) -> Principal:
    """`current_caller` for routes that compute ledger figures: needs `ledger:read`, so a
    lender viewer (passport and reports only) is refused. Explain stays open to them, masked."""
    return current_caller(principal, tenant_id)


def _error(status: int, code: str, message_key: str, **detail: str) -> JSONResponse:
    body = ApiError(code=code, message_key=message_key,
                    detail={k: str(v)[:_ECHO] for k, v in detail.items()})
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"))


def _month_end(day: date) -> date:
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


def aligned(period: Period) -> bool:
    """True when the period is one whole unit of its granularity."""
    start, end = period.start, period.end
    match period.granularity:
        case Granularity.day:
            return start == end
        case Granularity.week:
            return (end - start).days == 6
        case Granularity.month:
            return start.day == 1 and end == _month_end(start)
        case Granularity.quarter:
            return (start.day == 1 and start.month in (1, 4, 7, 10)
                    and end == _month_end(date(start.year, start.month + 2, 1)))
        case _:
            return (start.month, start.day) == (1, 1) and end == date(start.year, 12, 31)


def _period(start: str, end: str, granularity: str) -> Period | JSONResponse:
    try:
        period = Period(start=date.fromisoformat(start), end=date.fromisoformat(end),
                        granularity=Granularity(granularity))
    except ValueError:
        return _error(422, "invalid_period", "error.invalid_period")
    if not aligned(period):
        return _error(422, "unaligned_period", "error.unaligned_period", granularity=granularity)
    return period


def _masked(fact: Fact, caller: Principal) -> Fact:
    """The fact with its source rows passed through the masker (always called)."""
    masker = get_masker()
    refs, _ = masker(fact.tenant_id, fact.source_refs, caller)
    update: dict[str, object] = {"source_refs": refs}
    if fact.provenance is not None:
        rows, _ = masker(fact.tenant_id, fact.provenance.source_row_ids, caller)
        update["provenance"] = fact.provenance.model_copy(update={"source_row_ids": rows})
    return fact.model_copy(update=update)


@router.get("/facts/{metric}", response_model=Fact)
def get_fact(
    metric: str,
    start: str = "",
    end: str = "",
    granularity: str = "month",
    entity: str | None = None,
    compute: str = "true",
    caller: Principal = Depends(ledger_reader),
    session: Session = Depends(get_session),
) -> Fact | JSONResponse:
    period = _period(start, end, granularity)
    if isinstance(period, JSONResponse):
        return period
    store = FactStore(session)
    entity = entity or None
    if metric in REGISTRY.metrics() and compute.lower() not in ("false", "0", "no"):
        try:
            fact = compute_fact(store, caller.tenant_id, metric, period, entity)
        except NotComputable as exc:
            return _error(422, "not_computable", "error.not_computable", metric=metric,
                          reason_key=exc.reason_key)
        return _masked(fact, caller)
    try:
        fact = store.get(caller.tenant_id, metric, period, entity)
    except FactNotFound:
        known = metric in REGISTRY.metrics()
        return _error(404, "fact_not_found" if known else "unknown_metric",
                      "error.fact_not_found" if known else "error.unknown_metric",
                      metric=metric)
    if not store.is_current(fact):
        return _error(409, "fact_stale", "error.fact_stale", metric=metric)
    return _masked(fact, caller)


@router.get("/explain/{figure_id}", response_model=Explanation)
def get_explanation(
    figure_id: str,
    caller: Principal = Depends(current_caller),
    session: Session = Depends(get_session),
) -> Explanation | JSONResponse:
    try:
        return explain(FactStore(session), figure_id, caller)
    except FactNotFound:
        return _error(404, "figure_not_found", "error.figure_not_found", figure_id=figure_id)
    except ProvenanceIncomplete:
        return _error(409, "provenance_incomplete", "error.provenance_incomplete",
                      figure_id=figure_id)


@router.get("/explain/{figure_id}/rows", response_model=ExplainRows)
def get_explanation_rows(
    figure_id: str,
    offset: str = "0",
    limit: str = "100",
    caller: Principal = Depends(current_caller),
    session: Session = Depends(get_session),
) -> ExplainRows | JSONResponse:
    try:
        first, size = int(offset), int(limit)
    except ValueError:
        first, size = -1, -1
    if first < 0 or not 1 <= size <= MAX_PAGE:
        return _error(422, "invalid_page", "error.invalid_page", max_limit=str(MAX_PAGE))
    try:
        page = explain_rows(FactStore(session), figure_id, caller, first, size)
    except FactNotFound:
        return _error(404, "figure_not_found", "error.figure_not_found", figure_id=figure_id)
    return ExplainRows(figure_id=page.figure_id, total=page.total, offset=page.offset,
                       limit=size, masked=page.masked,
                       rows=[ExplainRow(ref=r.ref, kind=r.kind, record=r.record)
                             for r in page.rows])
