"""Every API route needs a signed-in session unless it is listed as public (known risk R20).

The list mirrors "Public routes" in docs/submission/security-self-assessment.md section 1. A new
route that forgets its permission check fails here instead of shipping open."""

import re

from fastapi.testclient import TestClient

from app.main import api_routes

PUBLIC = {
    ("GET", "/api/health"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/login/totp"),
    ("POST", "/api/auth/logout"),
    ("GET", "/api/auth/demo-accounts"),
    ("GET", "/api/verify/{passport_id}"),  # Trust Passport check for lenders (WP-13)
}


def _calls(client: TestClient) -> list[tuple[str, str]]:
    return sorted({(method, route.path) for route in api_routes(client.app)
                   for method in route.methods - {"HEAD", "OPTIONS"}})


def test_the_route_list_is_not_empty_and_includes_nested_routers(client: TestClient):
    calls = _calls(client)
    assert ("POST", "/api/approvals") in calls and ("POST", "/api/auth/login") in calls
    assert len(calls) > 60


def test_every_route_outside_the_public_list_refuses_an_anonymous_caller(client: TestClient):
    open_routes = []
    for method, path in _calls(client):
        if (method, path) in PUBLIC:
            continue
        url = re.sub(r"\{[^}]+\}", "probe-id", path)
        response = client.request(method, url, json={} if method in {"POST", "PUT", "PATCH"}
                                  else None)
        if response.status_code != 401:
            open_routes.append(f"{method} {path} -> {response.status_code}")
    assert open_routes == []


def test_every_public_route_still_exists(client: TestClient):
    assert set(_calls(client)) >= PUBLIC
