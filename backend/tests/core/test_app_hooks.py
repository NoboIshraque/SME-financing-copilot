"""App-wide hooks (`app/<area>/app_hooks.py`) discovered by main.create_app (WP-00)."""

from __future__ import annotations

import importlib
import itertools
import textwrap
from pathlib import Path

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse

import app.main as main_mod
from app.main import api_routes, create_app, discover_app_hooks

_counter = itertools.count()
INSTALL = "def install(app, settings):\n    app.state.hook_order.append({name!r})\n"


def _package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, areas: dict[str, str | None]):
    """A throwaway package: {area: app_hooks.py source, or None for an area without hooks}."""
    name = f"hookpkg_{next(_counter)}"
    root = tmp_path / name
    root.mkdir()
    (root / "__init__.py").write_text("")
    for area, source in areas.items():
        (root / area).mkdir()
        (root / area / "__init__.py").write_text("")
        if source is not None:
            (root / area / "app_hooks.py").write_text(textwrap.dedent(source))
    monkeypatch.syspath_prepend(str(tmp_path))
    return importlib.import_module(name)


def test_hooks_are_found_in_area_order_and_areas_without_hooks_are_skipped(tmp_path, monkeypatch):
    pkg = _package(tmp_path, monkeypatch, {
        "security": INSTALL.format(name="security"),
        "audit": INSTALL.format(name="audit"),
        "facts": None,                                   # no app_hooks.py
        "_private": INSTALL.format(name="private"),      # private packages are never loaded
    })
    assert [name for name, _ in discover_app_hooks(pkg)] == ["audit", "security"]


def test_a_hooks_module_without_install_fails_loudly(tmp_path, monkeypatch):
    pkg = _package(tmp_path, monkeypatch, {"security": "def instal(app, settings): ...\n"})
    with pytest.raises(TypeError, match="must define install"):
        discover_app_hooks(pkg)


def test_an_error_inside_a_hook_module_is_raised_not_hidden(tmp_path, monkeypatch):
    pkg = _package(tmp_path, monkeypatch, {"security": "raise RuntimeError('broken policy')\n"})
    with pytest.raises(RuntimeError, match="broken policy"):
        discover_app_hooks(pkg)


def test_hooks_see_every_route_and_cors_still_wraps_their_early_responses(settings, monkeypatch):
    seen: list[str] = []

    def install(app, _settings):
        seen.extend(r.path for r in api_routes(app))

        @app.middleware("http")
        async def throttle(request, call_next):
            if request.url.path == "/api/health":
                return JSONResponse({"error": "rate_limited"}, status_code=429)
            return await call_next(request)

    monkeypatch.setattr(main_mod, "discover_app_hooks", lambda: [("security", install)])
    origin = settings.cors_origins[0]

    with TestClient(create_app(settings)) as client:
        response = client.get("/api/health", headers={"Origin": origin})

    assert {"/api/health", "/api/facts/{metric}"} <= set(seen)  # routers mount before hooks
    assert response.status_code == 429
    assert response.headers["access-control-allow-origin"] == origin


def test_the_app_builds_with_the_hooks_the_repo_actually_has(settings):
    # Whatever app_hooks.py files exist (none before WP-11) must load and install cleanly.
    assert all(callable(install) for _, install in discover_app_hooks())
    create_app(settings)


def test_api_routes_lists_full_paths_once_even_for_prefixed_routers(settings, monkeypatch):
    mesh = APIRouter(prefix="/mesh")

    @mesh.post("/rounds/propose")
    def propose() -> dict:
        return {}

    real = main_mod.discover_routers()
    monkeypatch.setattr(main_mod, "discover_routers", lambda: [*real, ("mesh", mesh)])

    routes = {(r.module, r.path): r.methods for r in api_routes(create_app(settings))}

    assert routes[("mesh", "/api/mesh/rounds/propose")] == {"POST"}
    assert routes[("health", "/api/health")] == {"GET"}

