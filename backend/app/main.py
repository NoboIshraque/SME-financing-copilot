"""FastAPI application factory.

Routers are discovered automatically: every module in `app/api/` that defines a module-level
`router` (a FastAPI `APIRouter`) is mounted. A work package adds `app/api/<wp_name>.py` and
never edits this file.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Iterator

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app import api as api_pkg
from app.db import init_db, make_engine, session_factory
from app.settings import Settings, get_settings


def discover_routers() -> list[tuple[str, APIRouter]]:
    routers: list[tuple[str, APIRouter]] = []
    for info in sorted(pkgutil.iter_modules(api_pkg.__path__), key=lambda i: i.name):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{api_pkg.__name__}.{info.name}")
        router = getattr(module, "router", None)
        if isinstance(router, APIRouter):
            routers.append((info.name, router))
    return routers


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    application = FastAPI(
        title="Hishab - SME Finance Copilot API",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    application.state.settings = settings
    engine = make_engine(settings.database_url)
    init_db(engine)
    application.state.engine = engine
    application.state.session_factory = session_factory(engine)

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-Idempotency-Key", "X-Step-Up-Code"],
    )

    for _name, router in discover_routers():
        application.include_router(router, prefix="/api")
    return application


def get_session(request: Request) -> Iterator[object]:
    """FastAPI dependency: one SQLAlchemy session per request."""
    factory = request.app.state.session_factory
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


# Run with: uvicorn --factory app.main:create_app  (no app is built at import time, so
# importing this module in tests never touches a database file).
