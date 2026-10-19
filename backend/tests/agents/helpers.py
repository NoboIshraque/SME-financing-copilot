"""Test doubles for WP-10: a controllable clock and a scripted model transport.

`Scripted` stands in for the providers in tests about the gateway's own behaviour (fallback,
cooldown, budgets, cache). Model *answers* in agent tests come from the recorded fixtures in
`tests/fixtures/llm/` through the real `FixtureTransport`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.llm.messages import LLMRequest, Outcome
from app.llm.providers import Provider
from app.llm.transport import Completion, ProviderError

START = datetime(2026, 9, 30, 8, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self, start: datetime = START) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> datetime:
        self.now += timedelta(**delta)
        return self.now


class Scripted:
    """Per slot, a list of answers (text) or failures (Outcome); the last item repeats.
    A slot with no script is unreachable. Records the slots it was asked, in order."""

    def __init__(self, script: dict[str, list[str | Outcome]] | None = None,
                 keys: bool = True) -> None:
        self.script = {slot: list(items) for slot, items in (script or {}).items()}
        self.keys = keys
        self.calls: list[str] = []

    def has_key(self, provider: Provider) -> bool:
        return self.keys

    def send(self, provider: Provider, request: LLMRequest) -> Completion:
        self.calls.append(provider.slot)
        queue = self.script.get(provider.slot)
        if not queue:
            raise ProviderError(Outcome.unreachable)
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Outcome):
            raise ProviderError(item)
        return Completion(item, 12, 7)
