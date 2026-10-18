"""FastAPI dependencies for authentication, permissions and step-up (WP-11).

    principal: Principal = Depends(current_principal)            # any signed-in user
    principal: Principal = Depends(require(Permission.audit_read))  # 403 without it
    step: StepUp = Depends(step_up)                               # fresh TOTP in X-Step-Up-Code
    if step.problem: return step.problem.response()

A missing, expired or revoked session answers 401 `error.not_authenticated`. `step_up` never
raises: a wrong code is counted towards the lockout, and raising would roll that count back
with the request's transaction, so the route returns `step.problem.response()` instead.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.contracts import Principal
from app.main import get_session
from app.security.accounts import Accounts, principal_of
from app.security.clock import Clock, system_clock
from app.security.errors import SecurityProblem, forbidden, not_authenticated
from app.security.models import SessionRow, UserRow
from app.security.roles import Permission, has_permission
from app.security.sessions import COOKIE_NAME, SessionStore

STEP_UP_HEADER = "X-Step-Up-Code"


def get_clock(request: Request) -> Clock:
    return getattr(request.app.state, "security_clock", system_clock)


@dataclass(frozen=True)
class Authenticated:
    user: UserRow
    session: SessionRow
    token: str


def authenticated(request: Request, db: Session = Depends(get_session),
                  clock: Clock = Depends(get_clock)) -> Authenticated:
    now = clock()
    token = request.cookies.get(COOKIE_NAME)
    row = SessionStore(db).find(token, now)
    if row is None or token is None:
        raise not_authenticated()
    accounts = Accounts(db, request.app.state.settings)
    user = accounts.get(row.user_id)
    if user is None or not accounts.usable(user, now):
        raise not_authenticated()
    return Authenticated(user=user, session=row, token=token)


def current_principal(auth: Authenticated = Depends(authenticated)) -> Principal:
    return principal_of(auth.user)


def require(permission: Permission) -> Callable[..., Principal]:
    def dependency(principal: Principal = Depends(current_principal),
                   clock: Clock = Depends(get_clock)) -> Principal:
        if not has_permission(principal, permission, clock()):
            raise forbidden(permission.value)
        return principal

    dependency.__name__ = f"require_{permission.name}"
    return dependency


@dataclass(frozen=True)
class StepUp:
    auth: Authenticated
    problem: SecurityProblem | None  # None: a fresh TOTP code was verified for this request

    @property
    def verified(self) -> bool:
        return self.problem is None


def step_up(request: Request, auth: Authenticated = Depends(authenticated),
            db: Session = Depends(get_session), clock: Clock = Depends(get_clock)) -> StepUp:
    code = request.headers.get(STEP_UP_HEADER, "")
    if not code:
        return StepUp(auth, SecurityProblem(401, "step_up_required", "error.step_up_required"))
    if not auth.user.totp_enrolled:
        return StepUp(auth, SecurityProblem(403, "totp_not_enrolled", "error.totp_not_enrolled"))
    result = Accounts(db, request.app.state.settings).check_totp(auth.user, code, clock())
    if result.status == "locked":
        return StepUp(auth, SecurityProblem(423, "account_locked", "error.account_locked",
                                            retry_after_minutes=result.retry_after_minutes))
    if result.status != "ok":
        return StepUp(auth, SecurityProblem(401, "invalid_step_up", "error.invalid_step_up"))
    return StepUp(auth, None)
