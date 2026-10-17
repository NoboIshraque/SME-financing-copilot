"""Health and build info (owned by WP-00)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.contracts import CONTRACTS_VERSION

router = APIRouter(tags=["health"])


@router.get("/health")
def health(request: Request) -> dict[str, object]:
    settings = request.app.state.settings
    return {
        "status": "ok",
        "contracts_version": CONTRACTS_VERSION,
        "data_mode_banner": "synthetic" if settings.demo_mode else None,
        "config": settings.public_view(),
    }
