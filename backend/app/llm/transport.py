"""How a request reaches a model: live, replayed from a fixture, or recorded (WP-10 milestone 1).

- `OpenAICompatTransport`: the real call, one OpenAI-compatible client per endpoint. Retries
  are off: the gateway's fallback chain is the retry policy, and a slow free tier must not
  hold a request for minutes.
- `FixtureTransport`: replays recorded responses from `backend/tests/fixtures/llm/`, matched
  by slot and prompt hash. Tests and the offline demo use it (CLAUDE.md rule 6).
- `RecordingTransport`: wraps the live transport and writes each response as a fixture, so a
  live run (`python -m app.llm.live_check`) produces the recordings the tests replay.

Every transport raises `ProviderError(outcome)` on failure and nothing else, so the gateway
can treat all providers alike. Error messages never include prompts or keys.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

import openai

from app.llm.messages import LLMRequest, Outcome
from app.llm.providers import KeyName, Provider
from app.settings import Settings

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "llm"


class ProviderError(RuntimeError):
    def __init__(self, outcome: Outcome, detail: str = "") -> None:
        self.outcome = outcome
        super().__init__(f"{outcome.value}{': ' + detail if detail else ''}")


@dataclass(frozen=True)
class Completion:
    text: str
    tokens_in: int = 0
    tokens_out: int = 0


class Transport(Protocol):
    def has_key(self, provider: Provider) -> bool: ...

    def send(self, provider: Provider, request: LLMRequest) -> Completion: ...


def _outcome_for(exc: openai.OpenAIError) -> Outcome:
    if isinstance(exc, openai.RateLimitError):
        return Outcome.rate_limited
    if isinstance(exc, openai.APITimeoutError):  # subclass of APIConnectionError: check first
        return Outcome.timeout
    if isinstance(exc, openai.APIConnectionError):
        return Outcome.unreachable
    if isinstance(exc, openai.APIStatusError):
        return Outcome.server_error if exc.status_code >= 500 else Outcome.bad_request
    return Outcome.bad_response


class OpenAICompatTransport:
    def __init__(self, settings: Settings, *, timeout: float = 20.0,
                 http_client: Any = None) -> None:
        self._settings = settings
        self._timeout = timeout
        self._http_client = http_client  # tests pass a client with a mock transport
        self._clients: dict[tuple[str, str], openai.OpenAI] = {}

    def _key(self, provider: Provider) -> str:
        if provider.key is KeyName.none:
            return "local"  # Ollama ignores the key but the client requires one
        return getattr(self._settings, provider.key.value).get_secret_value()

    def has_key(self, provider: Provider) -> bool:
        return bool(self._key(provider))

    def _client(self, provider: Provider) -> openai.OpenAI:
        ident = (provider.base_url, provider.key.value)
        if ident not in self._clients:
            self._clients[ident] = openai.OpenAI(
                api_key=self._key(provider), base_url=provider.base_url,
                timeout=self._timeout, max_retries=0, http_client=self._http_client)
        return self._clients[ident]

    def send(self, provider: Provider, request: LLMRequest) -> Completion:
        kwargs: dict[str, Any] = {
            "model": provider.model,
            "messages": [m.as_dict() for m in request.messages],
            "temperature": request.temperature,
        }
        if request.json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            result = self._client(provider).chat.completions.create(**kwargs)
        except openai.OpenAIError as exc:
            raise ProviderError(_outcome_for(exc), type(exc).__name__) from None
        if not result.choices or result.choices[0].message.content is None:
            raise ProviderError(Outcome.bad_response, "empty completion")
        usage = result.usage
        return Completion(result.choices[0].message.content,
                          usage.prompt_tokens if usage else 0,
                          usage.completion_tokens if usage else 0)


class FixtureStore:
    """Recorded responses, one JSON file per (slot, prompt hash):
    `<root>/<slot>/<first 16 hex of the hash>.json`. The file keeps the anonymised messages
    so a reviewer can see what was asked; `source` says whether a live model answered
    ("live") or a person wrote the answer for a test ("authored")."""

    def __init__(self, root: Path = FIXTURES_DIR) -> None:
        self.root = root

    def path(self, slot: str, prompt_hash: str) -> Path:
        return self.root / slot / f"{prompt_hash[:16]}.json"

    def load(self, slot: str, request: LLMRequest) -> Completion | None:
        prompt_hash = request.prompt_hash()
        path = self.path(slot, prompt_hash)
        if not path.is_file():
            return None
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("prompt_hash") != prompt_hash:  # a 16-hex prefix collision
            return None
        response = record["response"]
        return Completion(response["text"], response.get("tokens_in", 0),
                          response.get("tokens_out", 0))

    def record(self, provider: Provider, request: LLMRequest, completion: Completion, *,
               source: str, recorded_at: datetime) -> Path:
        prompt_hash = request.prompt_hash()
        path = self.path(provider.slot, prompt_hash)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "slot": provider.slot, "model": provider.model, "task": request.task.value,
            "prompt_hash": prompt_hash, "source": source,
            "recorded_at": recorded_at.isoformat(),
            "messages": [m.as_dict() for m in request.messages],
            "response": {"text": completion.text, "tokens_in": completion.tokens_in,
                         "tokens_out": completion.tokens_out},
        }
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8", newline="\n")
        return path


class FixtureTransport:
    def __init__(self, store: FixtureStore | None = None) -> None:
        self.store = store or FixtureStore()

    def has_key(self, provider: Provider) -> bool:
        return True  # replay needs no key

    def send(self, provider: Provider, request: LLMRequest) -> Completion:
        completion = self.store.load(provider.slot, request)
        if completion is None:
            raise ProviderError(Outcome.fixture_missing, provider.slot)
        return completion


class RecordingTransport:
    def __init__(self, inner: Transport, store: FixtureStore, clock: Any) -> None:
        self.inner = inner
        self.store = store
        self.clock = clock
        self.recorded: list[Path] = []

    def has_key(self, provider: Provider) -> bool:
        return self.inner.has_key(provider)

    def send(self, provider: Provider, request: LLMRequest) -> Completion:
        completion = self.inner.send(provider, request)
        self.recorded.append(self.store.record(provider, request, completion, source="live",
                                               recorded_at=self.clock()))
        return completion
