"""Auth API (WP-11 milestone 1). Shapes match `web/src/api/types.ts`.

    POST /api/auth/login          {email, password} -> {status: "ok", session}
                                                     | {status: "totp_required"}
    POST /api/auth/login/totp     {code} -> Session          (second step, pending cookie)
    POST /api/auth/logout         -> 204
    GET  /api/auth/me             -> Session                 (401 when signed out)
    GET  /api/auth/demo-accounts  -> [DemoAccount]           (demo mode only, else 404)
    POST /api/auth/totp/enrol     -> {secret, otpauth_uri}   (signed in, not yet enrolled)
    POST /api/auth/totp/confirm   {code} -> Session
    POST /api/auth/password       {current_password, new_password} -> 204

Team and lender access (owner only; adding anyone needs a fresh TOTP in X-Step-Up-Code):

    GET  /api/auth/users                          -> [Member]
    POST /api/auth/users                          {email, display_name, role, password} -> Member
    POST /api/auth/users/{user_id}/deactivate     -> Member     (their sessions end at once)
    GET  /api/auth/lender-access                  -> [LenderGrant]
    POST /api/auth/lender-access                  {lender_email, lender_label, purpose, scopes,
                                                   days, consent} -> LenderGrant (+ one-time
                                                   initial_password)
    POST /api/auth/lender-access/{grant_id}/revoke -> LenderGrant

Errors are ApiError bodies: 401 error.invalid_credentials, 401 error.invalid_totp,
423 error.account_locked (detail.retry_after_minutes), 401 error.not_authenticated,
422 error.weak_password (detail.problems). A failed attempt is written before the error is
returned (not raised), so the lockout counter survives the request.
"""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.contracts import Principal, Role
from app.main import get_session
from app.security import totp
from app.security.accounts import AccountProblem, Accounts, SignIn
from app.security.clock import Clock
from app.security.demo import demo_enabled, demo_listing, ensure_demo_accounts
from app.security.deps import Authenticated, StepUp, authenticated, get_clock, require, step_up
from app.security.errors import ProblemRoute, SecurityProblem, not_authenticated
from app.security.models import LenderGrantRow, UserRow
from app.security.roles import Permission
from app.security.schemas import (
    CodeBody,
    DemoAccountView,
    LenderGrantBody,
    LenderGrantView,
    LoginBody,
    LoginOk,
    LoginTotpRequired,
    MemberView,
    NewMemberBody,
    PasswordChangeBody,
    SessionView,
    TotpEnrolment,
)
from app.security.sessions import COOKIE_NAME, SessionStore, Stage, cookie_attributes, lifetime
from app.security.team import Team, grant_scopes
from app.settings import Settings

router = APIRouter(prefix="/auth", tags=["auth"], route_class=ProblemRoute)

NO_STORE = {"Cache-Control": "no-store"}


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _ensure_demo(request: Request, db: Session, now: datetime) -> None:
    state = request.app.state
    if not getattr(state, "security_demo_seeded", False):
        ensure_demo_accounts(db, state.settings, now)
        state.security_demo_seeded = True


def _set_cookie(response: Response, token: str, stage: Stage, settings: Settings) -> None:
    response.set_cookie(COOKIE_NAME, token, max_age=int(lifetime(stage).total_seconds()),
                        **cookie_attributes(settings))  # type: ignore[arg-type]
    response.headers.update(NO_STORE)


def _clear_cookie(response: Response, settings: Settings) -> None:
    attributes = cookie_attributes(settings)
    response.delete_cookie(COOKIE_NAME, path=str(attributes["path"]),
                           secure=bool(attributes["secure"]), httponly=True, samesite="strict")


def _refusal(result: SignIn, invalid_code: str = "invalid_credentials") -> JSONResponse:
    if result.status == "locked":
        return SecurityProblem(423, "account_locked", "error.account_locked",
                               retry_after_minutes=result.retry_after_minutes).response()
    return SecurityProblem(401, invalid_code, f"error.{invalid_code}").response()


@router.post("/login", response_model=LoginOk | LoginTotpRequired)
def login(body: LoginBody, request: Request, response: Response,
          db: Session = Depends(get_session), clock: Clock = Depends(get_clock)
          ) -> LoginOk | LoginTotpRequired | JSONResponse:
    now = clock()
    settings = _settings(request)
    _ensure_demo(request, db, now)
    accounts = Accounts(db, settings)
    result = accounts.sign_in(body.email, body.password, now)
    if result.user is None:
        return _refusal(result)
    store = SessionStore(db)
    store.revoke(request.cookies.get(COOKIE_NAME), now)  # a sign-in never reuses a session
    stage = Stage.totp_pending if result.status == "totp_required" else Stage.active
    token, _row = store.issue(result.user.id, stage, now)
    _set_cookie(response, token, stage, settings)
    if stage is Stage.totp_pending:
        return LoginTotpRequired()
    return LoginOk(session=accounts.session_view(result.user))


@router.post("/login/totp", response_model=SessionView)
def login_totp(body: CodeBody, request: Request, response: Response,
               db: Session = Depends(get_session), clock: Clock = Depends(get_clock)
               ) -> SessionView | JSONResponse:
    now = clock()
    settings = _settings(request)
    store = SessionStore(db)
    token = request.cookies.get(COOKIE_NAME)
    pending = store.find(token, now, Stage.totp_pending)
    accounts = Accounts(db, settings)
    user = accounts.get(pending.user_id) if pending is not None else None
    if user is None:
        return not_authenticated().response()
    result = accounts.check_totp(user, body.code, now)
    if result.status != "ok":
        if result.status == "locked":
            store.revoke(token, now)  # after a lock the password is needed again
        return _refusal(result, "invalid_totp")
    store.revoke(token, now)
    new_token, _row = store.issue(user.id, Stage.active, now)
    _set_cookie(response, new_token, Stage.active, settings)
    return accounts.session_view(user)


@router.post("/logout", status_code=204)
def logout(request: Request, db: Session = Depends(get_session),
           clock: Clock = Depends(get_clock)) -> Response:
    SessionStore(db).revoke(request.cookies.get(COOKIE_NAME), clock())
    response = Response(status_code=204)
    _clear_cookie(response, _settings(request))
    return response


@router.get("/me", response_model=SessionView)
def me(request: Request, response: Response, auth: Authenticated = Depends(authenticated),
       db: Session = Depends(get_session)) -> SessionView:
    response.headers.update(NO_STORE)
    return Accounts(db, _settings(request)).session_view(auth.user)


@router.get("/demo-accounts", response_model=list[DemoAccountView])
def demo_accounts(request: Request, response: Response, db: Session = Depends(get_session),
                  clock: Clock = Depends(get_clock)) -> list[DemoAccountView] | JSONResponse:
    settings = _settings(request)
    if not demo_enabled(settings):
        return SecurityProblem(404, "not_found", "error.not_found").response()
    now = clock()
    _ensure_demo(request, db, now)
    response.headers.update(NO_STORE)
    return demo_listing(settings, now)


@router.post("/totp/enrol", response_model=TotpEnrolment)
def totp_enrol(request: Request, response: Response,
               auth: Authenticated = Depends(authenticated),
               db: Session = Depends(get_session)) -> TotpEnrolment | JSONResponse:
    try:
        secret = Accounts(db, _settings(request)).start_totp_enrolment(auth.user)
    except AccountProblem as problem:
        return SecurityProblem(409, problem.code, problem.message_key).response()
    response.headers.update(NO_STORE)
    return TotpEnrolment(secret=secret, otpauth_uri=totp.provisioning_uri(secret, auth.user.email))


@router.post("/totp/confirm", response_model=SessionView)
def totp_confirm(body: CodeBody, request: Request,
                 auth: Authenticated = Depends(authenticated),
                 db: Session = Depends(get_session),
                 clock: Clock = Depends(get_clock)) -> SessionView | JSONResponse:
    accounts = Accounts(db, _settings(request))
    if not accounts.confirm_totp_enrolment(auth.user, body.code, clock()):
        return SecurityProblem(401, "invalid_totp", "error.invalid_totp").response()
    return accounts.session_view(auth.user)


@router.post("/password", status_code=204)
def change_password(body: PasswordChangeBody, request: Request,
                    auth: Authenticated = Depends(authenticated),
                    db: Session = Depends(get_session),
                    clock: Clock = Depends(get_clock)) -> Response:
    now = clock()
    accounts = Accounts(db, _settings(request))
    try:
        result = accounts.change_password(auth.user, body.current_password, body.new_password,
                                          now)
    except AccountProblem as problem:
        return SecurityProblem(422, problem.code, problem.message_key, **problem.detail).response()
    if result.status != "ok":
        return _refusal(result)
    SessionStore(db).revoke_user(auth.user.id, now, keep=auth.token)
    return Response(status_code=204)


# ---------------------------------------------------------------------- team and lender access


def _member(user: UserRow) -> MemberView:
    return MemberView(user_id=user.id, email=user.email, role=Role(user.role),
                      display_name=user.display_name, active=user.active,
                      totp_enrolled=user.totp_enrolled, expires_at=user.expires_at,
                      scopes=list(json.loads(user.scopes)))


def _grant(grant: LenderGrantRow, team: Team, initial_password: str | None = None
           ) -> LenderGrantView:
    lender = team.accounts.get(grant.user_id)
    return LenderGrantView(id=grant.id, lender_email=lender.email if lender else "",
                           lender_label=grant.lender_label, purpose=grant.purpose,
                           scopes=grant_scopes(grant), consented_by=grant.consented_by,
                           consented_at=grant.consented_at, expires_at=grant.expires_at,
                           revoked_at=grant.revoked_at, initial_password=initial_password)


def _account_problem(problem: AccountProblem) -> JSONResponse:
    status = {"not_found": 404, "email_taken": 409}.get(problem.code, 422)
    return SecurityProblem(status, problem.code, problem.message_key, **problem.detail).response()


@router.get("/users", response_model=list[MemberView])
def list_members(request: Request, response: Response,
                 owner: Principal = Depends(require(Permission.team_manage)),
                 db: Session = Depends(get_session)) -> list[MemberView]:
    response.headers.update(NO_STORE)
    return [_member(user) for user in Team(db, _settings(request)).members(owner.tenant_id)]


@router.post("/users", response_model=MemberView, status_code=201)
def add_member(body: NewMemberBody, request: Request,
               owner: Principal = Depends(require(Permission.team_manage)),
               step: StepUp = Depends(step_up), db: Session = Depends(get_session),
               clock: Clock = Depends(get_clock)) -> MemberView | JSONResponse:
    if step.problem:
        return step.problem.response()
    try:
        user = Team(db, _settings(request)).add_member(
            owner, email=body.email, display_name=body.display_name, role=body.role,
            password=body.password, now=clock())
    except AccountProblem as problem:
        return _account_problem(problem)
    return _member(user)


@router.post("/users/{user_id}/deactivate", response_model=MemberView)
def deactivate_member(user_id: str, request: Request,
                      owner: Principal = Depends(require(Permission.team_manage)),
                      db: Session = Depends(get_session),
                      clock: Clock = Depends(get_clock)) -> MemberView | JSONResponse:
    try:
        user = Team(db, _settings(request)).deactivate(owner, user_id, clock())
    except AccountProblem as problem:
        return _account_problem(problem)
    return _member(user)


@router.get("/lender-access", response_model=list[LenderGrantView])
def list_lender_access(request: Request, response: Response,
                       owner: Principal = Depends(require(Permission.lender_access_grant)),
                       db: Session = Depends(get_session)) -> list[LenderGrantView]:
    response.headers.update(NO_STORE)
    team = Team(db, _settings(request))
    return [_grant(grant, team) for grant in team.grants(owner.tenant_id)]


@router.post("/lender-access", response_model=LenderGrantView, status_code=201)
def grant_lender_access(body: LenderGrantBody, request: Request, response: Response,
                        owner: Principal = Depends(require(Permission.lender_access_grant)),
                        step: StepUp = Depends(step_up), db: Session = Depends(get_session),
                        clock: Clock = Depends(get_clock)) -> LenderGrantView | JSONResponse:
    if step.problem:
        return step.problem.response()
    team = Team(db, _settings(request))
    try:
        grant, initial_password = team.grant_lender(
            owner, lender_email=body.lender_email, lender_label=body.lender_label,
            purpose=body.purpose, scopes=tuple(body.scopes), days=body.days,
            consent=body.consent, now=clock())
    except AccountProblem as problem:
        return _account_problem(problem)
    response.headers.update(NO_STORE)
    return _grant(grant, team, initial_password)


@router.post("/lender-access/{grant_id}/revoke", response_model=LenderGrantView)
def revoke_lender_access(grant_id: str, request: Request,
                         owner: Principal = Depends(require(Permission.lender_access_grant)),
                         db: Session = Depends(get_session),
                         clock: Clock = Depends(get_clock)) -> LenderGrantView | JSONResponse:
    team = Team(db, _settings(request))
    try:
        grant = team.revoke_lender(owner, grant_id, clock())
    except AccountProblem as problem:
        return _account_problem(problem)
    return _grant(grant, team)
