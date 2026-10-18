"""Web hardening for the API (WP-11 milestone 6): headers, rate limits, origin check.

    from app.security.web import install_security
    install_security(application, settings)      # in create_app (WP-00 wires this line)

Installs, outermost first:
1. `SecurityHeadersMiddleware`: CSP, HSTS, nosniff, frame denial, referrer and permissions
   policies, cross-origin isolation headers, and `Cache-Control: no-store` on API data.
2. `RateLimitMiddleware`: token buckets per client IP and route group (sign-in is the
   tightest); 429 `error.rate_limited` with Retry-After.
3. `OriginCheckMiddleware`: state-changing requests from a browser must come from our own
   origin or an allowed one (CSRF defence in depth behind the SameSite=Strict cookie).
Plus the app-wide `SecurityProblem` handler and the source-row masking policy for WP-01.

CORS itself stays in `create_app` (an explicit origin list, never "*"); `install_security`
refuses a wildcard origin when the app is deployed. Caddy (WP-18) sets the same headers for
the web app; these keep the API safe when it is reached without Caddy.
"""

from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.facts.masking import set_masker
from app.security.errors import SecurityProblem, problem_handler
from app.security.roles import policy_masker
from app.settings import AppEnv, Settings

API_CSP = ("default-src 'none'; frame-ancestors 'none'; base-uri 'none'; "
           "form-action 'none'")
# FastAPI's interactive docs load Swagger UI from jsdelivr with an inline bootstrap script.
DOCS_CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "img-src 'self' data: https://fastapi.tiangolo.com; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'none'")
DOCS_PATHS = ("/api/docs", "/api/redoc")
BASE_HEADERS = {
    "strict-transport-security": "max-age=31536000; includeSubDomains",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "permissions-policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
}
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope.get("path", "")
        csp = DOCS_CSP if path.startswith(DOCS_PATHS) else API_CSP

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {name.lower() for name, _ in headers}
                extra = {**BASE_HEADERS, "content-security-policy": csp}
                if path.startswith("/api/") and not path.startswith(DOCS_PATHS):
                    extra.setdefault("cache-control", "no-store")
                for name, value in extra.items():
                    if name.encode() not in present:
                        headers.append((name.encode(), value.encode()))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


@dataclass(frozen=True)
class Limit:
    bucket: str
    methods: frozenset[str] | None  # None: every method
    pattern: re.Pattern[str]
    per_minute: int


def _limit(bucket: str, pattern: str, per_minute: int, methods: str | None = None) -> Limit:
    return Limit(bucket, frozenset(methods.split()) if methods else None,
                 re.compile(pattern), per_minute)


# First match wins. Per client IP.
LIMITS: tuple[Limit, ...] = (
    _limit("sign_in", r"^/api/auth/login(/totp)?$", 10, "POST"),
    _limit("auth_change", r"^/api/auth/(password|users|lender-access|totp/.*)", 20,
           "POST PUT PATCH DELETE"),
    _limit("approve", r"^/api/approvals/[^/]+/(approve|execute)$", 30, "POST"),
    _limit("copilot", r"^/api/copilot/", 20, "POST"),
    _limit("ingest", r"^/api/ingest/", 30, "POST"),
    _limit("guard", r"^/api/guard/check$", 60, "POST"),
    _limit("api", r"^/api/", 300),
)


def _problem_body(problem: SecurityProblem) -> bytes:
    return json.dumps(problem.api_error.model_dump(mode="json")).encode()


async def _send_problem(send: Send, problem: SecurityProblem) -> None:
    body = _problem_body(problem)
    headers = [(b"content-type", b"application/json"),
               (b"content-length", str(len(body)).encode())]
    headers += [(k.lower().encode(), v.encode()) for k, v in (problem.headers or {}).items()]
    await send({"type": "http.response.start", "status": problem.status_code,
                "headers": headers})
    await send({"type": "http.response.body", "body": body})


class RateLimitMiddleware:
    """Token bucket per (route group, client IP), in process memory. One API process serves
    the demo (WP-18); a multi-process deployment needs a shared store (known-risk list)."""

    MAX_KEYS = 50_000

    def __init__(self, app: ASGIApp, limits: tuple[Limit, ...] = LIMITS,
                 now: Callable[[Scope], float] | None = None) -> None:
        self.app = app
        self.limits = limits
        self._now = now or (lambda scope: time.monotonic())
        self._buckets: dict[tuple[str, str], tuple[float, float]] = {}

    def _match(self, method: str, path: str) -> Limit | None:
        for limit in self.limits:
            if (limit.methods is None or method in limit.methods) and limit.pattern.search(path):
                return limit
        return None

    def take(self, limit: Limit, client: str, now: float) -> float:
        """Spend one token. Returns 0 when allowed, else seconds until the next token."""
        rate = limit.per_minute / 60.0
        key = (limit.bucket, client)
        tokens, last = self._buckets.get(key, (float(limit.per_minute), now))
        tokens = min(float(limit.per_minute), tokens + (now - last) * rate)
        if tokens >= 1.0:
            if len(self._buckets) >= self.MAX_KEYS and key not in self._buckets:
                self._buckets.clear()  # memory bound: forget everyone rather than grow
            self._buckets[key] = (tokens - 1.0, now)
            return 0.0
        self._buckets[key] = (tokens, now)
        return (1.0 - tokens) / rate

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self._match(scope.get("method", "GET"), scope.get("path", ""))
        if limit is not None:
            client = (scope.get("client") or ("unknown", 0))[0]
            wait = self.take(limit, client, self._now(scope))
            if wait > 0:
                seconds = max(1, math.ceil(wait))
                await _send_problem(send, SecurityProblem(
                    429, "rate_limited", "error.rate_limited",
                    headers={"Retry-After": str(seconds)}, retry_after_seconds=seconds,
                    bucket=limit.bucket))
                return
        await self.app(scope, receive, send)


class OriginCheckMiddleware:
    """Refuse state-changing browser requests from foreign origins. Requests without an
    Origin header (curl, server-to-server, tests) pass unless the browser marks them
    cross-site."""

    def __init__(self, app: ASGIApp, allowed_origins: list[str]) -> None:
        self.app = app
        self.allowed = {origin.rstrip("/").lower() for origin in allowed_origins}

    def permitted(self, headers: dict[str, str]) -> bool:
        origin = headers.get("origin")
        if origin is None:
            return headers.get("sec-fetch-site", "same-origin") != "cross-site"
        origin = origin.rstrip("/").lower()
        if origin in self.allowed:
            return True
        host = headers.get("host", "").lower()
        return bool(host) and origin.split("://", 1)[-1] == host

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("method") in UNSAFE_METHODS \
                and scope.get("path", "").startswith("/api/"):
            headers = {k.decode("latin-1").lower(): v.decode("latin-1")
                       for k, v in scope.get("headers", [])}
            if not self.permitted(headers):
                await _send_problem(send, SecurityProblem(403, "origin_not_allowed",
                                                          "error.origin_not_allowed"))
                return
        await self.app(scope, receive, send)


def _clock_seconds(scope: Scope) -> float:
    """Rate-limit clock: the security clock tests install, else the monotonic clock."""
    app: Any = scope.get("app")
    clock = getattr(getattr(app, "state", None), "security_clock", None)
    return clock().timestamp() if clock is not None else time.monotonic()


def install_security(app: FastAPI, settings: Settings) -> None:
    if getattr(app.state, "security_installed", False):
        return
    if settings.app_env in (AppEnv.demo, AppEnv.production) and "*" in settings.cors_origins:
        raise ValueError("CORS must list explicit origins when deployed, never '*'")
    app.add_exception_handler(SecurityProblem, problem_handler)
    set_masker(policy_masker)
    app.add_middleware(OriginCheckMiddleware, allowed_origins=list(settings.cors_origins))
    app.add_middleware(RateLimitMiddleware, now=_clock_seconds)
    app.add_middleware(SecurityHeadersMiddleware)
    app.state.security_installed = True
