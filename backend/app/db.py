"""Database engine and session.

Each work package defines its tables in its own package as `app/<area>/models.py`
(subclassing `Base`). `init_db()` imports every such module automatically, so nobody edits a
shared registry file. SQLite in development and tests, Postgres in production.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str) -> Engine:
    if database_url.startswith("sqlite"):
        kwargs: dict[str, object] = {"connect_args": {"check_same_thread": False}}
        if database_url in ("sqlite://", "sqlite:///:memory:"):
            kwargs["poolclass"] = StaticPool
        engine = create_engine(database_url, **kwargs)

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record) -> None:  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return engine
    return create_engine(database_url, pool_pre_ping=True)


def discover_model_modules() -> list[str]:
    """Return the dotted names of every `app.<pkg>[.<sub>].models` module."""
    found: list[str] = []
    for info in pkgutil.walk_packages(app.__path__, prefix="app."):
        if info.name.endswith(".models"):
            found.append(info.name)
    return sorted(found)


def init_db(engine: Engine) -> None:
    for name in discover_model_modules():
        importlib.import_module(name)
    Base.metadata.create_all(engine)


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
