import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.contracts import Role
from app.facts import masking
from app.main import create_app
from app.security.errors import not_authenticated
from app.security.web import LIMITS, RateLimitMiddleware, install_security
from app.settings import Settings
from tests.security.conftest import sign_in

ALLOWED = "http://localhost:5173"


@pytest.fixture
def hardened(app, settings):
    install_security(app, settings)
    previous = masking.get_masker()
    yield app
    masking.set_masker(previous)


@pytest.fixture
def web(hardened):
    with TestClient(hardened) as client:
        yield client


@pytest.mark.parametrize("path", ["/api/health", "/api/auth/me", "/api/nope"])
def test_security_headers_are_on_every_api_response(web, path):
    headers = web.get(path).headers
    assert headers["content-security-policy"].startswith("default-src 'none'")
    assert "frame-ancestors 'none'" in headers["content-security-policy"]
    assert headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "no-referrer"
    assert "camera=()" in headers["permissions-policy"]
    assert headers["cross-origin-opener-policy"] == "same-origin"
    assert headers["cache-control"] == "no-store"


def test_docs_get_a_csp_that_lets_swagger_load_but_still_cannot_be_framed(web):
    csp = web.get("/api/docs").headers["content-security-policy"]
    assert "https://cdn.jsdelivr.net" in csp and "frame-ancestors 'none'" in csp


def test_errors_from_dependencies_use_the_api_error_shape_app_wide(hardened):
    @hardened.get("/api/probe")
    def probe():
        raise not_authenticated()

    with TestClient(hardened) as client:
        response = client.get("/api/probe")
    assert response.status_code == 401
    assert response.json() == {"code": "not_authenticated",
                               "message_key": "error.not_authenticated", "detail": {}}


def test_cors_answers_our_origin_and_rejects_a_foreign_one(web):
    ok = web.options("/api/auth/login", headers={"Origin": ALLOWED,
                                                 "Access-Control-Request-Method": "POST"})
    assert ok.headers["access-control-allow-origin"] == ALLOWED
    assert ok.headers["access-control-allow-credentials"] == "true"
    evil = web.options("/api/auth/login", headers={"Origin": "https://evil.example",
                                                   "Access-Control-Request-Method": "POST"})
    assert evil.status_code == 400 and "access-control-allow-origin" not in evil.headers
    simple = web.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in simple.headers


@pytest.mark.parametrize(("headers", "status"), [
    ({"Origin": "https://evil.example"}, 403),
    ({"Sec-Fetch-Site": "cross-site"}, 403),
    ({"Origin": ALLOWED}, 401),  # allowed origin: reaches the route (bad credentials)
    ({"Origin": "http://testserver"}, 401),  # same origin as the Host header
    ({}, 401),  # no Origin: not a browser cross-site request
])
def test_state_changing_requests_from_foreign_origins_are_refused(web, headers, status):
    response = web.post("/api/auth/login", headers=headers,
                        json={"email": "a@b.test", "password": "wrong password!"})
    assert response.status_code == status
    if status == 403:
        assert response.json()["code"] == "origin_not_allowed"


def test_sign_in_is_rate_limited_per_client(web, hardened, clock):
    def attempt(i):  # a different email each time, so account lockout never interferes
        return web.post("/api/auth/login",
                        json={"email": f"nobody{i}@shop.test", "password": "wrong password!"})

    statuses = [attempt(i).status_code for i in range(11)]
    assert statuses[:10] == [401] * 10 and statuses[10] == 429
    limited = attempt(11)
    assert limited.json()["code"] == "rate_limited"
    assert limited.json()["detail"]["bucket"] == "sign_in"
    assert int(limited.headers["retry-after"]) >= 1
    assert web.get("/api/health").status_code == 200  # other route groups unaffected
    clock.advance(seconds=6)  # 10 per minute: one new token every 6 s
    assert attempt(12).status_code == 401


def test_rate_limit_buckets_are_per_client_ip():
    limiter = RateLimitMiddleware(app=None)  # type: ignore[arg-type]
    sign_in_limit = LIMITS[0]
    assert all(limiter.take(sign_in_limit, "10.0.0.1", 0.0) == 0 for _ in range(10))
    assert limiter.take(sign_in_limit, "10.0.0.1", 0.0) > 0
    assert limiter.take(sign_in_limit, "10.0.0.2", 0.0) == 0


@pytest.mark.parametrize(("method", "path", "bucket"), [
    ("POST", "/api/auth/login", "sign_in"),
    ("POST", "/api/auth/login/totp", "sign_in"),
    ("POST", "/api/auth/password", "auth_change"),
    ("POST", "/api/approvals/ap-1/approve", "approve"),
    ("POST", "/api/copilot/ask", "copilot"),
    ("POST", "/api/guard/check", "guard"),
    ("GET", "/api/auth/me", "api"),
    ("GET", "/api/approvals/ap-1", "api"),
])
def test_routes_fall_into_the_right_rate_limit_group(method, path, bucket):
    limiter = RateLimitMiddleware(app=None)  # type: ignore[arg-type]
    assert limiter._match(method, path).bucket == bucket


def test_sign_in_is_the_tightest_limit():
    per_minute = {limit.bucket: limit.per_minute for limit in LIMITS}
    assert per_minute["sign_in"] == min(per_minute.values()) == 10


def test_installing_twice_adds_nothing(app, settings):
    install_security(app, settings)
    count = len(app.user_middleware)
    install_security(app, settings)
    assert len(app.user_middleware) == count


def test_a_wildcard_cors_origin_is_refused_when_deployed():
    settings = Settings.model_construct(app_env="production", cors_origins=["*"])
    with pytest.raises(ValueError, match="explicit origins"):
        install_security(FastAPI(), settings)


def test_install_plugs_the_role_masking_policy_into_the_fact_ledger(hardened):
    rows, masked = masking.get_masker()("t1", ("bank.csv#L1",), Role.staff)
    assert masked and re.fullmatch(r"masked:[0-9a-f]{16}", rows[0])


def test_the_hardened_app_still_signs_in_end_to_end(web, make_user, clock):
    make_user()
    assert sign_in(web).json()["status"] == "ok"
    me = web.get("/api/auth/me")
    assert me.status_code == 200 and me.headers["cache-control"] == "no-store"
    clock.advance(minutes=31)
    assert web.get("/api/auth/me").status_code == 401


def test_rate_limits_survive_an_app_restart_only_in_memory(settings):
    """Documented limit: buckets live in process memory (one API process in the demo)."""
    first = create_app(settings)
    install_security(first, settings)
    with TestClient(first) as client:
        for _ in range(10):
            client.post("/api/auth/login", json={"email": "x@y.test", "password": "p" * 12})
        assert client.post("/api/auth/login",
                           json={"email": "x@y.test", "password": "p" * 12}).status_code == 429
    second = create_app(settings)
    install_security(second, settings)
    with TestClient(second) as client:
        assert client.post("/api/auth/login",
                           json={"email": "x@y.test", "password": "p" * 12}).status_code == 401
