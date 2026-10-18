"""App-wide security (WP-11): `create_app` calls `install` after mounting every router and
before adding CORS, so CORS stays outermost and wraps our 429/403 answers too."""

from __future__ import annotations

from fastapi import FastAPI

from app.security.web import install_security
from app.settings import Settings


def install(app: FastAPI, settings: Settings) -> None:
    install_security(app, settings)
