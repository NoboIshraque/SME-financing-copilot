"""FastAPI dependencies for authentication (WP-11).

    from app.security.deps import current_principal
    def route(principal: Principal = Depends(current_principal)): ...

A missing, expired or revoked session answers 401 `error.not_authenticated`.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.contracts import Principal
from app.main import get_session
from app.security.accounts import Accounts, principal_of
from app.security.clock import Clock, system_clock
from app.security.errors import not_authenticated
from app.security.models import SessionRow, UserRow
from app.security.sessions import COOKIE_NAME, SessionStore


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
