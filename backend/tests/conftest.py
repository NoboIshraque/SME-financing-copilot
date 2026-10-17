"""Shared test fixtures (owned by WP-00).

- Network guard: any socket connection to a non-loopback address fails the test
  (CLAUDE.md rule 6: tests never call real LLMs or the network).
- `settings`, `client`: an app on an in-memory SQLite database.
- `universe`: the synthetic SME universe as typed contracts (loaded once per session).
"""

from __future__ import annotations

import ipaddress
import os
import socket
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from hypothesis import HealthCheck
from hypothesis import settings as hypothesis_settings

from app.main import create_app
from app.settings import Settings
from app.synthetic import Universe, load_universe

hypothesis_settings.register_profile(
    "ci", max_examples=100, derandomize=True, deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
hypothesis_settings.register_profile("dev", max_examples=50, deadline=None)
hypothesis_settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))


class NetworkBlockedError(RuntimeError):
    pass


def _is_local(address: object) -> bool:
    if isinstance(address, str):  # unix socket path
        return True
    if isinstance(address, tuple) and address:
        host = address[0]
        if host in ("localhost", ""):
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False
    return False


@pytest.fixture(autouse=True, scope="session")
def _block_network() -> Iterator[None]:
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def guarded_connect(self: socket.socket, address: object) -> None:
        if not _is_local(address):
            raise NetworkBlockedError(f"tests must not use the network (tried {address!r})")
        return original_connect(self, address)

    def guarded_connect_ex(self: socket.socket, address: object) -> int:
        if not _is_local(address):
            raise NetworkBlockedError(f"tests must not use the network (tried {address!r})")
        return original_connect_ex(self, address)

    socket.socket.connect = guarded_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = guarded_connect_ex  # type: ignore[method-assign]
    yield
    socket.socket.connect = original_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = original_connect_ex  # type: ignore[method-assign]


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,  # never read a developer's backend/.env in tests
        app_env="test",
        demo_mode=True,
        database_url="sqlite://",
        llm_mode="fixtures",
        chain_mode="offline",
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def universe() -> Universe:
    return load_universe()
