"""Fixtures for WP-11 tests: a controllable clock, cheap argon2, users made directly in the DB."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from argon2.profiles import CHEAPEST
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.contracts import DataMode, Role
from app.db import init_db, make_engine, session_factory
from app.main import create_app
from app.security import passwords
from app.security.accounts import Accounts
from app.settings import Settings

START = datetime(2026, 10, 1, 9, 0, 7, tzinfo=UTC)
PASSWORD = "correct horse battery staple"


class FakeClock:
    def __init__(self, start: datetime = START) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> datetime:
        self.now += timedelta(**delta)
        return self.now


@pytest.fixture(autouse=True)
def cheap_hashing() -> Iterator[None]:
    """argon2's CHEAPEST profile keeps the suite fast; production parameters are asserted in
    test_passwords.py."""
    previous = passwords.use_parameters(CHEAPEST)
    yield
    passwords.use_parameters(previous)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def db(settings: Settings) -> Iterator[Session]:
    """A session on its own in-memory database (for service-level tests)."""
    engine = make_engine("sqlite://")
    init_db(engine)
    session = session_factory(engine)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def app(settings: Settings, clock: FakeClock) -> FastAPI:
    application = create_app(settings)
    application.state.security_clock = clock
    return application


@pytest.fixture
def api(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def make_user(app: FastAPI, clock: FakeClock):
    """Create a user straight in the app's database; returns the user id."""

    def make(email: str = "owner@shop.test", *, password: str = PASSWORD,
             role: Role = Role.owner, tenant: str = "t1", totp_secret: str | None = None,
             expires_at: datetime | None = None, scopes: tuple[str, ...] = ()) -> str:
        with app.state.session_factory() as session:
            accounts = Accounts(session, app.state.settings)
            accounts.ensure_tenant(tenant, "Test Shop", DataMode.synthetic, clock())
            user = accounts.create_user(email=email, password=password, tenant_id=tenant,
                                        role=role, display_name="Test user", now=clock(),
                                        scopes=scopes, expires_at=expires_at)
            if totp_secret:
                accounts.set_totp_secret(user, totp_secret, enrolled=True)
            session.commit()
            return user.id

    return make


def sign_in(client: TestClient, email: str = "owner@shop.test", password: str = PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})
