"""What callers send to the gateway and what they get back (WP-10 milestone 1).

These are internal types, not shared contracts: agents build an `LLMRequest`, the gateway
returns an `LLMResponse`. Everything in a request is already anonymised; the gateway checks
that again (fail closed) before anything leaves the server.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.llm.providers import Role


class Task(StrEnum):
    """The kind of work asked for. The deterministic planner answers the first four."""

    plan = "plan"  # intent + which tools to call
    vote = "vote"  # pick one of the given options
    critique = "critique"  # strongest objection to a recommendation
    narrate = "narrate"  # explain verified claims in words
    chat = "chat"  # free text; no rule-based fallback


@dataclass(frozen=True)
class Message:
    role: str  # system | user | assistant
    content: str

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class LLMRequest:
    role: Role
    task: Task
    messages: tuple[Message, ...]
    # Structured, anonymised inputs: the deterministic planner reads these instead of prose
    # (e.g. {"question": ..., "options": [...]}). Checked by the privacy gate like the messages.
    context: dict[str, Any] = field(default_factory=dict)
    json_mode: bool = True  # ask for, and validate, a JSON object
    temperature: float = 0.0
    private: bool = False  # private mode: only a local model, data never leaves the machine
    exclude_families: tuple[str, ...] = ()
    # Names the privacy gate must also look for (the tenant's party registry).
    party_names: tuple[str, ...] = ()
    shop_names: tuple[str, ...] = ()

    def payload(self) -> dict[str, Any]:
        """Everything that could reach a provider, for the privacy gate."""
        return {"messages": [m.as_dict() for m in self.messages], "context": self.context}

    def prompt_hash(self) -> str:
        """SHA-256 of the anonymised prompt. Names the cache entry and the recorded fixture,
        so it covers only what a model sees: task, messages, output format, temperature."""
        canonical = json.dumps(
            {"task": self.task.value, "messages": [m.as_dict() for m in self.messages],
             "json_mode": self.json_mode, "temperature": self.temperature},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class Outcome(StrEnum):
    ok = "ok"
    cached = "cached"
    no_key = "no_key"
    over_budget = "over_budget"  # our own per-minute / per-day limit for this slot
    cooling_down = "cooling_down"  # recent failures; skipped until the cooldown ends
    rate_limited = "rate_limited"  # the provider said 429
    timeout = "timeout"
    unreachable = "unreachable"
    server_error = "server_error"
    bad_request = "bad_request"  # 4xx other than 429 (model renamed, bad key, ...)
    bad_response = "bad_response"  # not the JSON object we asked for
    fixture_missing = "fixture_missing"
    unsupported = "unsupported"  # the deterministic planner cannot do this task


@dataclass(frozen=True)
class Attempt:
    slot: str
    outcome: Outcome


@dataclass(frozen=True)
class LLMResponse:
    text: str
    data: dict[str, Any] | None  # the parsed JSON object when json_mode
    slot: str
    model: str
    family: str
    prompt_hash: str
    cached: bool = False
    attempts: tuple[Attempt, ...] = ()
    tokens_in: int = 0
    tokens_out: int = 0

    @property
    def deterministic(self) -> bool:
        return self.family == "rules"

    @property
    def degraded(self) -> bool:
        """True when the answer did not come from the first provider in the chain."""
        return bool(self.attempts) and self.attempts[0].outcome not in (Outcome.ok,
                                                                        Outcome.cached)
