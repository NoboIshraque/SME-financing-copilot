"""Per-provider usage counters and graceful degradation (WP-10 milestone 1).

Free tiers refuse work with a 429 once a limit is hit, and a refused call still costs time.
The meter keeps our own rolling per-minute and per-day windows for each slot and stops
offering a slot *before* its limit, and puts a slot that failed into a cooldown that doubles
with each consecutive failure (30 s, 60 s, ... capped at 10 min). The gateway then moves to the
next provider in the chain, ending at the deterministic planner, so the app degrades instead
of failing. Counters never hold prompts or keys, so `snapshot()` is safe to show.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.llm.messages import Outcome
from app.llm.providers import Provider

MINUTE = timedelta(minutes=1)
DAY = timedelta(days=1)
BASE_COOLDOWN = timedelta(seconds=30)
MAX_COOLDOWN = timedelta(minutes=10)
# A provider's own 429 starts at a full minute: its window is at least that long.
RATE_LIMIT_COOLDOWN = timedelta(minutes=1)

COOLDOWN_OUTCOMES = frozenset({Outcome.rate_limited, Outcome.timeout, Outcome.unreachable,
                               Outcome.server_error, Outcome.bad_request})


@dataclass
class SlotUsage:
    requests: int = 0  # calls sent to the provider
    successes: int = 0
    failures: dict[str, int] = field(default_factory=dict)  # outcome -> count
    skipped: dict[str, int] = field(default_factory=dict)  # outcome -> count (not sent)
    cache_hits: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    consecutive_failures: int = 0
    cooldown_until: datetime | None = None
    minute: deque[datetime] = field(default_factory=deque)
    day: deque[datetime] = field(default_factory=deque)


class UsageMeter:
    def __init__(self) -> None:
        self._slots: dict[str, SlotUsage] = {}
        self._refused = 0
        self._lock = threading.Lock()

    def _usage(self, slot: str) -> SlotUsage:
        return self._slots.setdefault(slot, SlotUsage())

    @staticmethod
    def _trim(window: deque[datetime], now: datetime, span: timedelta) -> None:
        while window and now - window[0] >= span:
            window.popleft()

    def check(self, provider: Provider, now: datetime) -> Outcome | None:
        """None if the slot may be called now, otherwise why not."""
        with self._lock:
            usage = self._usage(provider.slot)
            if usage.cooldown_until is not None and now < usage.cooldown_until:
                return Outcome.cooling_down
            self._trim(usage.minute, now, MINUTE)
            self._trim(usage.day, now, DAY)
            if len(usage.minute) >= provider.rpm or len(usage.day) >= provider.rpd:
                return Outcome.over_budget
            return None

    def sent(self, slot: str, now: datetime) -> None:
        with self._lock:
            usage = self._usage(slot)
            usage.requests += 1
            usage.minute.append(now)
            usage.day.append(now)

    def succeeded(self, slot: str, tokens_in: int, tokens_out: int) -> None:
        with self._lock:
            usage = self._usage(slot)
            usage.successes += 1
            usage.tokens_in += tokens_in
            usage.tokens_out += tokens_out
            usage.consecutive_failures = 0
            usage.cooldown_until = None

    def failed(self, slot: str, outcome: Outcome, now: datetime) -> None:
        with self._lock:
            usage = self._usage(slot)
            usage.failures[outcome.value] = usage.failures.get(outcome.value, 0) + 1
            if outcome in COOLDOWN_OUTCOMES:
                usage.consecutive_failures += 1
                base = RATE_LIMIT_COOLDOWN if outcome is Outcome.rate_limited else BASE_COOLDOWN
                wait = min(base * 2 ** (usage.consecutive_failures - 1), MAX_COOLDOWN)
                usage.cooldown_until = now + wait

    def skipped(self, slot: str, outcome: Outcome) -> None:
        with self._lock:
            usage = self._usage(slot)
            usage.skipped[outcome.value] = usage.skipped.get(outcome.value, 0) + 1

    def cache_hit(self, slot: str) -> None:
        with self._lock:
            self._usage(slot).cache_hits += 1

    def refused(self) -> None:
        """A payload the privacy gate blocked (never sent anywhere)."""
        with self._lock:
            self._refused += 1

    def snapshot(self, now: datetime) -> dict[str, object]:
        with self._lock:
            slots = {}
            for slot, usage in sorted(self._slots.items()):
                self._trim(usage.minute, now, MINUTE)
                self._trim(usage.day, now, DAY)
                cooling = usage.cooldown_until is not None and now < usage.cooldown_until
                slots[slot] = {
                    "requests": usage.requests, "successes": usage.successes,
                    "failures": dict(usage.failures), "skipped": dict(usage.skipped),
                    "cache_hits": usage.cache_hits, "tokens_in": usage.tokens_in,
                    "tokens_out": usage.tokens_out, "last_minute": len(usage.minute),
                    "last_day": len(usage.day), "cooling_down": cooling,
                }
            return {"refused_by_privacy_gate": self._refused, "slots": slots}
