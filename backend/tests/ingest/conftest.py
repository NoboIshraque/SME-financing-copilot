"""Fixtures for ingest tests that need a database: a fresh in-memory SQLite per test."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from app.db import init_db, make_engine, session_factory


@pytest.fixture
def session() -> Iterator[Session]:
    engine = make_engine("sqlite://")
    init_db(engine)
    with session_factory(engine)() as db:
        yield db
    engine.dispose()
