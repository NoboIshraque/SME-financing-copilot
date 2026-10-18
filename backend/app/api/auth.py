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

Errors are ApiError bodies: 401 error.invalid_credentials, 401 error.invalid_totp,
423 error.account_locked (detail.retry_after_minutes), 401 error.not_authenticated,
422 error.weak_password (detail.problems). A failed attempt is written before the error is
returned (not raised), so the lockout counter survives the request.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.main import get_session
from app.security import totp
from app.security.accounts import AccountProblem, Accounts, SignIn
from app.security.clock import Clock
from app.security.demo import demo_enabled, demo_listing, ensure_demo_accounts
from app.security.deps import Authenticated, authenticated, get_clock
from app.security.errors import ProblemRoute, SecurityProblem, not_authenticated
from app.security.schemas import (
    CodeBody,
    DemoAccountView,
    LoginBody,
    LoginOk,
    LoginTotpRequired,
    PasswordChangeBody,
    SessionView,
    TotpEnrolment,
)
from app.security.sessions import COOKIE_NAME, SessionStore, Stage, cookie_attributes, lifetime
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
    result = accounts.complete_totp(user, body.code, now)
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
