"""Fixtures for WP-10 tests (test doubles live in tests/agents/helpers.py)."""

from __future__ import annotations

import pytest

from app.settings import LLMMode, Settings
from tests.agents.helpers import FakeClock


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def live_settings(settings: Settings) -> Settings:
    return settings.model_copy(update={"llm_mode": LLMMode.live})
