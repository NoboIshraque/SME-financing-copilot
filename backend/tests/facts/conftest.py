"""Fixtures for the fact ledger tests: a store on a fresh in-memory database."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from app.db import init_db, make_engine, session_factory
from app.facts import FactStore


@pytest.fixture
def session() -> Iterator[Session]:
    engine = make_engine("sqlite://")
    init_db(engine)
    with session_factory(engine)() as db:
        yield db
    engine.dispose()


@pytest.fixture
def store(session: Session) -> FactStore:
    return FactStore(session)
