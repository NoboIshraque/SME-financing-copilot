"""Self-service shops for the hosted demo: judges sign up their own shop and enter its numbers.

    POST /api/onboarding/signup        {business_name, email, password} -> SessionView (public,
                                       demo mode only; signs the new owner in)
    GET  /api/onboarding/profile       -> ShopProfile (what the owner has entered)
    POST /api/onboarding/profile       ShopProfile -> ShopProfile (owner or accountant)
    GET  /api/onboarding/template.csv  an example ledger in the format the upload screen reads

A self-signup shop is a new tenant marked `live`: its data is whatever the owner enters, never
synthetic. The engines need two things the ledger upload cannot give: the cash balance on the
day the records start (`initial_balance`) and the shop facts lenders check (business age, trade
licence, e-TIN, staff). The owner types them here; each is stored as a raw fact whose source is
the owner's entry. Sign-up is refused outside demo mode, capped at MAX_SHOPS shops, and rate
limited (bucket `signup` in `app/security/web.py`).
"""

from __future__ import annotations

import csv
import io
import secrets
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.contracts import DataMode, Fact, Granularity, Period, Principal, Role, Unit
from app.facts import FactStore
from app.facts.seed import INITIAL_BALANCE, PROFILE_FACTS
from app.facts.store import fact_id
from app.main import get_session
from app.security.accounts import AccountProblem, Accounts
from app.security.audit import AuditLog
from app.security.clock import Clock
from app.security.deps import get_clock, require
from app.security.errors import ProblemRoute, SecurityProblem
from app.security.models import TenantRow
from app.security.roles import Permission
from app.security.schemas import SessionView
from app.security.sessions import COOKIE_NAME, SessionStore, Stage, cookie_attributes, lifetime

router = APIRouter(prefix="/onboarding", tags=["onboarding"], route_class=ProblemRoute)

SHOP_PREFIX = "shop-"
MAX_SHOPS = 500
NO_STORE = {"Cache-Control": "no-store"}


class SignupBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    business_name: str = Field(min_length=2, max_length=80)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class ShopProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    opening_balance: Decimal | None = Field(default=None, ge=0, le=Decimal("1e12"),
                                            decimal_places=2)
    opening_date: date | None = None
    business_age_months: int | None = Field(default=None, ge=0, le=1200)
    trade_licence: bool | None = None
    etin_registered: bool | None = None
    staff_count: int | None = Field(default=None, ge=0, le=100_000)


def _owner_fact(tenant_id: str, metric: str, value: Decimal, unit: Unit, day: date) -> Fact:
    period = Period(start=day, end=day, granularity=Granularity.day)
    ref = f"owner-entry#{metric}"
    return Fact(id=fact_id(tenant_id, metric, period, None, 0, value, (ref,)),
                tenant_id=tenant_id, metric=metric, value=value, unit=unit, period=period,
                source_refs=(ref,), data_mode=DataMode.live)


@router.post("/signup", response_model=SessionView, status_code=201)
def signup(body: SignupBody, request: Request, response: Response,
           db: Session = Depends(get_session),
           clock: Clock = Depends(get_clock)) -> SessionView | JSONResponse:
    settings = request.app.state.settings
    if not settings.demo_mode:
        return SecurityProblem(404, "not_found", "error.not_found").response()
    shops = db.scalar(select(func.count()).select_from(TenantRow)
                      .where(TenantRow.id.startswith(SHOP_PREFIX)))
    if (shops or 0) >= MAX_SHOPS:
        return SecurityProblem(403, "signup_closed", "error.signup_closed").response()
    now = clock()
    accounts = Accounts(db, settings)
    tenant_id = SHOP_PREFIX + secrets.token_hex(6)
    accounts.ensure_tenant(tenant_id, body.business_name.strip(), DataMode.live, now)
    try:
        user = accounts.create_user(email=body.email, password=body.password,
                                    tenant_id=tenant_id, role=Role.owner,
                                    display_name=body.business_name.strip(), now=now)
    except AccountProblem as problem:
        db.rollback()
        return SecurityProblem(422, problem.code, problem.message_key,
                               **problem.detail).response()
    token, _row = SessionStore(db).issue(user.id, Stage.active, now)
    response.set_cookie(COOKIE_NAME, token, max_age=int(lifetime(Stage.active).total_seconds()),
                        **cookie_attributes(settings))  # type: ignore[arg-type]
    response.headers.update(NO_STORE)
    AuditLog(db).append(tenant_id, actor=user.id, action="auth.signup", now=now)
    return accounts.session_view(user)


def _profile(store: FactStore, tenant_id: str, today: date) -> ShopProfile:
    initial = store.facts(tenant_id, INITIAL_BALANCE)
    values: dict[str, object] = {}
    if initial:
        values["opening_balance"] = initial[-1].value
        values["opening_date"] = initial[-1].period.start
    for metric in PROFILE_FACTS:
        fact = store.latest(tenant_id, metric, today)
        if fact is None:
            continue
        values[metric] = bool(fact.value) if metric in ("trade_licence", "etin_registered") \
            else int(fact.value)
    return ShopProfile(**values)


@router.get("/profile", response_model=ShopProfile)
def get_profile(principal: Principal = Depends(require(Permission.ledger_read)),
                db: Session = Depends(get_session),
                clock: Clock = Depends(get_clock)) -> ShopProfile:
    return _profile(FactStore(db), principal.tenant_id, clock().date())


@router.post("/profile", response_model=ShopProfile)
def save_profile(body: ShopProfile,
                 principal: Principal = Depends(require(Permission.ingest_upload)),
                 db: Session = Depends(get_session),
                 clock: Clock = Depends(get_clock)) -> ShopProfile | JSONResponse:
    if principal.role not in (Role.owner, Role.accountant):
        return SecurityProblem(403, "forbidden", "error.forbidden", reason="role").response()
    today = clock().date()
    if (body.opening_balance is None) != (body.opening_date is None):
        return SecurityProblem(422, "opening_needs_both", "error.opening_needs_both").response()
    if body.opening_date is not None and body.opening_date > today:
        return SecurityProblem(422, "date_in_future", "error.date_in_future").response()
    store = FactStore(db)
    if body.opening_balance is not None and body.opening_date is not None:
        store.put_fact(_owner_fact(principal.tenant_id, INITIAL_BALANCE,
                                   body.opening_balance.quantize(Decimal("0.01")), Unit.BDT,
                                   body.opening_date))
    for metric in PROFILE_FACTS:
        raw = getattr(body, metric)
        if raw is not None:
            store.put_fact(_owner_fact(principal.tenant_id, metric, Decimal(int(raw)),
                                       Unit.count, today))
    AuditLog(db).append(principal.tenant_id, actor=principal.user_id,
                        action="shop.profile_saved", now=clock())
    return _profile(store, principal.tenant_id, today)


TEMPLATE_DAYS = 120


def template_rows(today: date) -> list[list[str]]:
    """An example ledger ending yesterday: daily sales in, weekly supplier and monthly rent out.
    Clearly an example; the owner replaces it with their own records."""
    rows = [["date", "type", "amount", "party", "category", "channel", "ref"]]
    start = today - timedelta(days=TEMPLATE_DAYS)
    for n in range(TEMPLATE_DAYS):
        day = start + timedelta(days=n)
        sales = 9000 + 1500 * (day.weekday() in (3, 4)) + 37 * (n % 9)
        rows.append([day.isoformat(), "in", f"{sales}.00", "Walk-in customers", "sales",
                     "cash", f"EX-S{n:03d}"])
        if day.weekday() == 5:
            rows.append([day.isoformat(), "out", "52000.00", "Example Supplier", "purchase",
                         "bank", f"EX-P{n:03d}"])
        if day.day == 1:
            rows.append([day.isoformat(), "out", "18000.00", "Landlord", "rent", "bank",
                         f"EX-R{n:03d}"])
    return rows


@router.get("/template.csv")
def template(clock: Clock = Depends(get_clock),
             _principal: Principal = Depends(require(Permission.ingest_upload))) -> Response:
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerows(template_rows(clock().date()))
    return Response(buffer.getvalue(), media_type="text/csv", headers={
        "Content-Disposition": 'attachment; filename="decisionguard-ledger-example.csv"'})
