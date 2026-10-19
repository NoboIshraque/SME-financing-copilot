"""FastAPI application factory.

Routers are discovered automatically: every module in `app/api/` that defines a module-level
`router` (a FastAPI `APIRouter`) is mounted. A work package adds `app/api/<wp_name>.py` and
never edits this file.

App-wide behaviour (middleware, exception handlers, startup checks) plugs in the same way: a
package `app/<area>/` may define `app_hooks.py` with `install(app, settings) -> None`. Hooks run
in package-name order, after every router is mounted (so a hook can walk `api_routes(app)`,
e.g. refuse to start when a route has no permission tier) and before CORS is added, so CORS stays
the outermost layer and even an early 429/403 from a hook's middleware carries CORS headers.
WP-11 uses `app/security/app_hooks.py` for security headers, rate limits and the like.
"""

from __future__ import annotations

import importlib
import importlib.util
import pkgutil
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from types import ModuleType

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from starlette.routing import BaseRoute

import app as app_pkg
from app import api as api_pkg
from app.db import init_db, make_engine, session_factory
from app.settings import AppEnv, Settings, get_settings


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


AppHook = Callable[[FastAPI, Settings], None]
API_PREFIX = "/api"


@dataclass(frozen=True)
class ApiRoute:
    module: str  # app/api/<module>.py
    path: str  # full path, "/api/..."
    methods: frozenset[str]
    endpoint: Callable[..., object]
    route: APIRoute


def _walk(routes: Sequence[BaseRoute], prefix: str) -> Iterator[tuple[str, APIRoute]]:
    """(full path, route) for every APIRoute in `routes`, descending into included routers.

    A route's own `path` already carries its router's prefix. FastAPI (0.14x) includes routers
    lazily: `include_router` appends one entry holding `original_router` and an
    `include_context` whose `prefix` joins the including router's prefix and the include's own,
    so the prefixes add up on the way down. Older versions copied the routes in, flattened,
    which the first branch covers."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield prefix + route.path, route
            continue
        included = getattr(route, "original_router", None)
        context = getattr(route, "include_context", None)
        if isinstance(included, APIRouter) and context is not None:
            yield from _walk(included.routes, prefix + context.prefix)


def api_routes(application: FastAPI) -> list[ApiRoute]:
    """Every API route with its full path, from the routers create_app mounted, including the
    routes of routers they include (at any depth). Public and stable, unlike walking
    `app.routes` (FastAPI includes routers lazily)."""
    return [ApiRoute(module, path, frozenset(route.methods or ()), route.endpoint, route)
            for module, router in application.state.api_routers
            for path, route in _walk(router.routes, API_PREFIX)]


def discover_app_hooks(package: ModuleType = app_pkg) -> list[tuple[str, AppHook]]:
    """`install` from every `<package>.<area>.app_hooks` module, in area-name order.

    A package without `app_hooks.py` is skipped. An error inside one, or an `app_hooks.py`
    without a callable `install`, is raised, never hidden: a security hook that silently fails
    to load would leave the app running without it."""
    hooks: list[tuple[str, AppHook]] = []
    for info in sorted(pkgutil.iter_modules(package.__path__), key=lambda i: i.name):
        if not info.ispkg or info.name.startswith("_"):
            continue
        name = f"{package.__name__}.{info.name}.app_hooks"
        if importlib.util.find_spec(name) is None:
            continue
        install = getattr(importlib.import_module(name), "install", None)
        if not callable(install):
            raise TypeError(f"{name} must define install(app, settings)")
        hooks.append((info.name, install))
    return hooks


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    local = settings.app_env in (AppEnv.development, AppEnv.test)
    application = FastAPI(
        title="Hishab - SME Finance Copilot API",
        version="0.1.0",
        # Interactive docs only where developers run the app: Swagger UI loads from a
        # third-party CDN (may be blocked in China, needs a relaxed CSP). The API contract is
        # published as docs/api/contracts.json.
        docs_url="/api/docs" if local else None,
        redoc_url="/api/redoc" if local else None,
        openapi_url="/api/openapi.json" if local else None,
    )
    application.state.settings = settings
    engine = make_engine(settings.database_url)
    init_db(engine)
    application.state.engine = engine
    application.state.session_factory = session_factory(engine)

    routers = discover_routers()
    application.state.api_routers = routers
    for _name, router in routers:
        application.include_router(router, prefix=API_PREFIX)

    for _name, install in discover_app_hooks():
        install(application, settings)

    # Added last, so it is the outermost middleware (Starlette wraps in reverse order).
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-Idempotency-Key", "X-Step-Up-Code"],
    )
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
