"""Fact ledger API (WP-01 milestone 4).

    GET /api/facts/{metric}?tenant_id=&start=&end=&granularity=&entity=   -> Fact
    GET /api/explain/{figure_id}                                          -> Explanation

Lookups are exact. When no fact is stored yet and the metric is registered, it is computed from
the ledger on the spot (`compute=false` turns that off). Errors are `ApiError` bodies.

Until WP-11 lands, the tenant comes from the query string and the caller's role from
`caller_role` below; WP-11 replaces that dependency with the authenticated principal.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.contracts import ApiError, Explanation, Fact, Granularity, Period, Role
from app.facts import FactNotFound, FactStore
from app.facts.provenance import compute as compute_fact
from app.facts.provenance import explain as explain_figure
from app.facts.registry import NotComputable, UnknownMetric
from app.main import get_session

router = APIRouter(tags=["facts"])


def caller_role(request: Request) -> Role:
    """Stub until WP-11: the owner in demo mode, otherwise the least-privileged viewer
    (source rows masked)."""
    return Role.owner if request.app.state.settings.demo_mode else Role.lender_viewer


def _error(status: int, code: str, message_key: str, **detail: str) -> JSONResponse:
    body = ApiError(code=code, message_key=message_key, detail=detail)
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"))


@router.get("/facts/{metric}", response_model=Fact)
def get_fact(
    metric: str,
    tenant_id: str,
    start: date,
    end: date,
    granularity: Granularity = Granularity.month,
    entity: str | None = None,
    compute: bool = True,
    session: Session = Depends(get_session),
) -> Fact | JSONResponse:
    if end < start:
        return _error(422, "invalid_period", "error.invalid_period")
    period = Period(start=start, end=end, granularity=granularity)
    store = FactStore(session)
    try:
        return store.get(tenant_id, metric, period, entity or None)
    except FactNotFound:
        if not compute:
            return _error(404, "fact_not_found", "error.fact_not_found", metric=metric)
    try:
        return compute_fact(store, tenant_id, metric, period, entity or None)
    except UnknownMetric:
        return _error(404, "unknown_metric", "error.unknown_metric", metric=metric)
    except NotComputable as exc:
        return _error(422, "not_computable", "error.not_computable", metric=metric,
                      reason=str(exc))


@router.get("/explain/{figure_id}", response_model=Explanation)
def get_explanation(
    figure_id: str,
    role: Role = Depends(caller_role),
    session: Session = Depends(get_session),
) -> Explanation | JSONResponse:
    try:
        return explain_figure(FactStore(session), figure_id, role)
    except FactNotFound:
        return _error(404, "figure_not_found", "error.figure_not_found", figure_id=figure_id)
