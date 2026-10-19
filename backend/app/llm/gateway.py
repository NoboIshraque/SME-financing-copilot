"""The LLM gateway: the only door from Hishab to a language model (WP-10 milestone 1).

CLAUDE.md rule 3: every model call goes through `LLMGateway.complete()`, which

1. runs the WP-03 privacy gate on everything that could reach a provider (messages *and*
   structured context) and refuses the request if any detector fires (fail closed: the
   request is never sent, the refusal is counted, the error names kinds only);
2. walks the role's fallback chain (`providers.chain`): cache -> key present -> within our
   own budget -> send -> valid JSON; any failure moves to the next provider;
3. ends at the deterministic planner, which always answers the tasks it knows.

Callers anonymise first with `prepare_messages()` (labels shared across all messages, so
"Customer 1" means the same party everywhere) and restore labels in the answer with the
returned `Anonymised`. Numbers in an answer are never trusted (rule 1): figures come from
the engines and every numeric claim is re-checked by the checker.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any

from app.llm import deterministic
from app.llm.cache import CachedAnswer, MemoryCache, ResponseCache, cache_key
from app.llm.messages import Attempt, LLMRequest, LLMResponse, Message, Outcome
from app.llm.providers import Provider, chain, configured
from app.llm.transport import FixtureTransport, OpenAICompatTransport, ProviderError, Transport
from app.llm.usage import UsageMeter
from app.privacy import Anonymised, PrivacyViolation, TokenVault, anonymise, assert_safe
from app.security.clock import Clock, system_clock
from app.settings import LLMMode, Settings

log = logging.getLogger("app.llm")

_SEPARATOR = "\n␞\n"  # SYMBOL FOR RECORD SEPARATOR: no digits, letters or names
_THINK = re.compile(r"<think>.*?</think>", re.S)
_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.S)


class NoProviderAvailable(RuntimeError):
    """Every provider failed and the deterministic planner cannot do this task."""

    def __init__(self, attempts: Sequence[Attempt]) -> None:
        self.attempts = tuple(attempts)
        trail = ", ".join(f"{a.slot}={a.outcome.value}" for a in self.attempts)
        super().__init__(f"no provider could answer ({trail})")


def parse_json_object(text: str) -> dict[str, Any] | None:
    """The JSON object in a model's reply, tolerating a reasoning block or a code fence."""
    body = _THINK.sub("", text).strip()
    fenced = _FENCE.match(body)
    if fenced:
        body = fenced.group(1)
    try:
        value = json.loads(body)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def prepare_messages(
    messages: Sequence[Message], *, vault: TokenVault, tenant: str, anchor: date,
    roles: dict[str, str] | None = None, party_names: Iterable[str] = (),
    shop_names: Iterable[str] = (), rare_terms: Iterable[str] = (),
    scale_amounts: bool = False,
) -> tuple[tuple[Message, ...], Anonymised]:
    """Anonymise all messages in one pass so they share one label map (WP-03 anonymiser)."""
    joined = _SEPARATOR.join(m.content for m in messages)
    result = anonymise(joined, vault=vault, tenant=tenant, anchor=anchor, roles=roles,
                       party_names=party_names, shop_names=shop_names, rare_terms=rare_terms,
                       scale_amounts=scale_amounts)
    parts = result.text.split(_SEPARATOR)
    if len(parts) != len(messages):
        raise ValueError("anonymisation changed the message boundaries")
    return tuple(Message(m.role, part) for m, part in zip(messages, parts, strict=True)), result


class LLMGateway:
    def __init__(self, settings: Settings, *, transport: Transport | None = None,
                 cache: ResponseCache | None = None, meter: UsageMeter | None = None,
                 clock: Clock = system_clock, models: dict[str, str] | None = None,
                 enforce_budgets: bool | None = None) -> None:
        self.mode = settings.llm_mode
        self.table = configured(settings, models)
        if transport is None:
            transport = (OpenAICompatTransport(settings) if self.mode is LLMMode.live
                         else FixtureTransport())
        self.transport = transport
        self.cache = cache if cache is not None else MemoryCache()
        self.meter = meter or UsageMeter()
        self.clock = clock
        # Replaying fixtures costs nothing, so budgets bind only on live calls by default.
        self.enforce_budgets = (self.mode is LLMMode.live if enforce_budgets is None
                                else enforce_budgets)

    def chain_for(self, request: LLMRequest, slots: Sequence[str] | None = None,
                  rules_fallback: bool = True) -> tuple[Provider, ...]:
        """The role's chain, or exactly `slots` (a voter pinned to one model) under the same
        mode, privacy and family rules; with or without the deterministic planner at the end."""
        full = chain(request.role, self.mode, private=request.private,
                     exclude_families=request.exclude_families, table=self.table)
        models, rules = full[:-1], full[-1]
        if slots is not None:
            excluded = set(request.exclude_families)
            allowed = [self.table[s] for s in slots]
            if self.mode is LLMMode.deterministic:
                allowed = []
            elif request.private:
                allowed = [p for p in allowed if p.local]
            models = tuple(p for p in allowed
                           if p.family not in excluded and not p.deterministic)
        return (*models, rules) if rules_fallback else models

    def complete(self, request: LLMRequest, *, slots: Sequence[str] | None = None,
                 rules_fallback: bool = True) -> LLMResponse:
        try:
            assert_safe(request.payload(), party_names=request.party_names,
                        shop_names=request.shop_names)
        except PrivacyViolation as exc:
            self.meter.refused()
            log.warning("llm request refused by the privacy gate: %s",
                        ",".join(k.value for k in exc.kinds))
            raise
        prompt_hash = request.prompt_hash()
        attempts: list[Attempt] = []
        for provider in self.chain_for(request, slots, rules_fallback):
            if provider.deterministic:
                return self._rules(provider, request, prompt_hash, attempts)
            response = self._try(provider, request, prompt_hash, attempts)
            if response is not None:
                return response
        raise NoProviderAvailable(attempts)

    def _try(self, provider: Provider, request: LLMRequest, prompt_hash: str,
             attempts: list[Attempt]) -> LLMResponse | None:
        now = self.clock()
        key = cache_key(provider.model_id, prompt_hash)
        hit = self.cache.get(key, now)
        if hit is not None:
            self.meter.cache_hit(provider.slot)
            attempts.append(Attempt(provider.slot, Outcome.cached))
            data = parse_json_object(hit.text) if request.json_mode else None
            return self._response(provider, request, prompt_hash, attempts, hit.text, data,
                                  cached=True)
        blocked = None if self.transport.has_key(provider) else Outcome.no_key
        if blocked is None and self.enforce_budgets:
            blocked = self.meter.check(provider, now)
        if blocked is not None:
            self.meter.skipped(provider.slot, blocked)
            attempts.append(Attempt(provider.slot, blocked))
            return None
        self.meter.sent(provider.slot, now)
        try:
            completion = self.transport.send(provider, request)
        except ProviderError as exc:
            return self._failed(provider, exc.outcome, prompt_hash, attempts)
        data = None
        if request.json_mode:
            data = parse_json_object(completion.text)
            if data is None:
                return self._failed(provider, Outcome.bad_response, prompt_hash, attempts)
        self.meter.succeeded(provider.slot, completion.tokens_in, completion.tokens_out)
        self.cache.put(key, CachedAnswer(completion.text, now, completion.tokens_in,
                                         completion.tokens_out))
        attempts.append(Attempt(provider.slot, Outcome.ok))
        return self._response(provider, request, prompt_hash, attempts, completion.text, data,
                              tokens=(completion.tokens_in, completion.tokens_out))

    def _failed(self, provider: Provider, outcome: Outcome, prompt_hash: str,
                attempts: list[Attempt]) -> None:
        self.meter.failed(provider.slot, outcome, self.clock())
        attempts.append(Attempt(provider.slot, outcome))
        log.info("llm %s failed (%s) for prompt %s", provider.slot, outcome.value,
                 prompt_hash[:12])

    def _rules(self, provider: Provider, request: LLMRequest, prompt_hash: str,
               attempts: list[Attempt]) -> LLMResponse:
        try:
            text = deterministic.answer(request)
        except deterministic.Unsupported:
            attempts.append(Attempt(provider.slot, Outcome.unsupported))
            raise NoProviderAvailable(attempts) from None
        attempts.append(Attempt(provider.slot, Outcome.ok))
        return self._response(provider, request, prompt_hash, attempts, text, json.loads(text))

    @staticmethod
    def _response(provider: Provider, request: LLMRequest, prompt_hash: str,
                  attempts: list[Attempt], text: str, data: dict[str, Any] | None, *,
                  cached: bool = False, tokens: tuple[int, int] = (0, 0)) -> LLMResponse:
        return LLMResponse(text=text, data=data, slot=provider.slot, model=provider.model,
                           family=provider.family, prompt_hash=prompt_hash, cached=cached,
                           attempts=tuple(attempts), tokens_in=tokens[0], tokens_out=tokens[1])

    def usage(self) -> dict[str, object]:
        return {"mode": self.mode.value, **self.meter.snapshot(self.clock())}
