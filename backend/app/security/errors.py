"""Security errors as `ApiError` bodies.

`SecurityProblem` is an HTTPException, so it works from any dependency. Routes declared with
`route_class=ProblemRoute` (every WP-11 route) turn it into a top-level `ApiError` body;
`install_security()` (app.security.web) adds the same handler app-wide.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from app.contracts import ApiError


class SecurityProblem(HTTPException):
    def __init__(self, status: int, code: str, message_key: str,
                 headers: dict[str, str] | None = None, **detail: object) -> None:
        self.api_error = ApiError(code=code, message_key=message_key,
                                  detail={key: str(value) for key, value in detail.items()})
        super().__init__(status_code=status, detail=self.api_error.model_dump(mode="json"),
                         headers=headers)

    def response(self) -> JSONResponse:
        return JSONResponse(status_code=self.status_code,
                            content=self.api_error.model_dump(mode="json"),
                            headers=self.headers)


def not_authenticated() -> SecurityProblem:
    return SecurityProblem(401, "not_authenticated", "error.not_authenticated")


def forbidden(reason: str = "role") -> SecurityProblem:
    return SecurityProblem(403, "forbidden", "error.forbidden", reason=reason)


async def problem_handler(_request: Request, exc: Exception) -> Response:
    if isinstance(exc, SecurityProblem):
        return exc.response()
    raise exc


class ProblemRoute(APIRoute):
    """Route class that answers a SecurityProblem (from the endpoint or a dependency) with a
    top-level ApiError body, whether or not the app-wide handler is installed."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def guarded(request: Request) -> Response:
            try:
                return await handler(request)
            except SecurityProblem as problem:
                return problem.response()

        return guarded
