"""Orchestrator and sub-agents (WP-10 milestone 3; FEATURES N8, P9, P13).

    run = Orchestrator(gateway).ask(ctx, "Will I run out of cash next month?")
    run.recommendation          # answer + claims + figures + up to 3 action cards, or abstain

1. Guard: the question passes WP-11's injection guard before any model sees it.
2. Plan: the brain proposes intents and tools from the anonymised question; code repairs the
   plan (planning.py). If the gate still finds personal data, the rules plan locally.
3. Dispatch: one sub-agent per intent, in parallel threads. A tool two sub-agents need runs
   once (memoised); dependencies run first; every call is charged to the run's budget.
4. Compose: every number becomes a Claim (claims.py); the brain narrates the claim texts; at
   most three action cards the caller's role may act on are attached (P9: rails, not chat).

A failure in the primary intent's tools abstains with exactly what is missing; a failure in a
secondary intent is reported in `Run.skipped` while the rest is answered.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.agents import abstention as abstain
from app.agents import agreement as agreement_mod
from app.agents import claims as claims_mod
from app.agents import critic as critic_mod
from app.agents.agreement import AgreementOutcome
from app.agents.budget import Budget
from app.agents.checker import Checker, log_rejections, unverified_numbers
from app.agents.claims import Statement
from app.agents.critic import Objection
from app.agents.planning import DEPENDS, Plan, build_plan
from app.agents.selfloop import self_loop
from app.agents.stakes import Stakes, assess
from app.agents.tools import (
    InsufficientData,
    ToolContext,
    ToolError,
    ToolRegistry,
    ToolResult,
    ToolUnavailable,
    most_cautious,
)
from app.agents.toolset import REGISTRY
from app.contracts import (
    Abstention,
    ActionCard,
    CheckResult,
    CheckStatus,
    DataMode,
    Figure,
    Recommendation,
    Role,
    StabilityReport,
)
from app.llm import LLMGateway, LLMRequest, LLMResponse, NoProviderAvailable
from app.llm import deterministic as rules
from app.llm.prompts import narrate_request, plan_request
from app.privacy import PrivacyViolation, TokenVault, anonymise
from app.security import policy
from app.security.guard import Source, screen

MAX_CARDS = 3
QUARANTINED = "[quarantined: see the quarantine list]"  # never echo an injection attempt
CARD_SOURCES = ("cash.gaps", "financing.match", "mesh.propose")


class BudgetExhausted(ToolError):
    def __init__(self, tool: str) -> None:
        self.tool = tool
        super().__init__(f"{tool}: the run's tool budget is used up")


@dataclass(frozen=True)
class TraceEvent:
    step: str  # guard | plan | tool | narrate | ...
    name: str
    outcome: str
    ms: int
    detail: str = ""


class Trace:
    def __init__(self) -> None:
        self._events: list[TraceEvent] = []
        self._lock = threading.Lock()

    def add(self, step: str, name: str, outcome: str, started: float, detail: str = "") -> None:
        ms = round((time.perf_counter() - started) * 1000)
        with self._lock:
            self._events.append(TraceEvent(step, name, outcome, ms, detail))

    def events(self) -> tuple[TraceEvent, ...]:
        with self._lock:
            return tuple(self._events)


class ToolRunner:
    """Runs each tool at most once per run, dependencies first, charged to the budget."""

    def __init__(self, registry: ToolRegistry, ctx: ToolContext, budget: Budget,
                 params: Mapping[str, Mapping[str, Any]], trace: Trace) -> None:
        self.registry, self.ctx, self.budget = registry, ctx, budget
        self.params, self.trace = params, trace
        self._done: dict[str, ToolResult | ToolError] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def _lock_for(self, name: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(name, threading.Lock())

    def call(self, name: str) -> ToolResult | ToolError:
        for dependency in DEPENDS.get(name, ()):
            self.call(dependency)
        with self._lock_for(name):
            if name in self._done:
                return self._done[name]
            started = time.perf_counter()
            outcome: ToolResult | ToolError
            if not self.budget.take_tool(name):
                outcome = BudgetExhausted(name)
            else:
                try:
                    outcome = self.registry.run(name, self.ctx, self.params.get(name))
                except ToolError as exc:
                    outcome = exc
            self._done[name] = outcome
            label = "ok" if isinstance(outcome, ToolResult) else type(outcome).__name__
            self.trace.add("tool", name, label, started,
                           "" if isinstance(outcome, ToolResult) else str(outcome))
            return outcome

    def run_all(self, tools: Iterable[str]) -> None:
        for name in tools:
            self.call(name)

    def results(self) -> dict[str, ToolResult]:
        return {n: r for n, r in self._done.items() if isinstance(r, ToolResult)}

    def errors(self) -> dict[str, ToolError]:
        return {n: e for n, e in self._done.items() if isinstance(e, ToolError)}


@dataclass(frozen=True)
class Run:
    recommendation: Recommendation
    plan: Plan
    statements: tuple[Statement, ...] = ()  # verified only
    results: Mapping[str, ToolResult] = field(default_factory=dict)
    checks: tuple[CheckResult, ...] = ()  # every claim, verified or not
    dropped_cards: tuple[str, ...] = ()  # cards whose figures did not pass the checker
    skipped: Mapping[str, str] = field(default_factory=dict)  # tool -> why (secondary intents)
    stakes: Stakes | None = None
    objection: Objection | None = None  # the critic's, with who argued it
    agreement: AgreementOutcome | None = None  # the vote on the judgement, if one was taken
    budget: Mapping[str, object] = field(default_factory=dict)
    trace: tuple[TraceEvent, ...] = ()


def recommendation_id(tenant_id: str, question: str, now: datetime) -> str:
    digest = hashlib.sha256(f"{tenant_id}|{question}|{now.isoformat()}".encode()).hexdigest()
    return f"rec_{digest[:20]}"


def abstention_for(errors: Mapping[str, ToolError]) -> Abstention:
    """The most specific reason among the failed tools, naming exactly what is missing."""
    missing = [m for e in errors.values() if isinstance(e, InsufficientData) for m in e.missing]
    if missing:
        return abstain.insufficient_data(missing)
    refused = [n for n, e in errors.items() if isinstance(e, BudgetExhausted)]
    if refused:
        return abstain.budget_exhausted(refused)
    engines = [e.engine for e in errors.values() if isinstance(e, ToolUnavailable)]
    if engines:
        return abstain.out_of_scope(engines, detail="engine_unavailable")
    return abstain.unverifiable(detail="; ".join(sorted(str(e) for e in errors.values())))


class Orchestrator:
    def __init__(self, gateway: LLMGateway, registry: ToolRegistry = REGISTRY, *,
                 vault: TokenVault | None = None, max_workers: int = 3,
                 guard: bool = True) -> None:
        self.gateway = gateway
        self.registry = registry
        # Tokens only label text for one request; originals are never restored from here.
        self.vault = vault or TokenVault(secrets.token_bytes(32))
        self.max_workers = max_workers
        self.guard = guard

    # ------------------------------------------------------------------ model calls

    def llm(self, request: LLMRequest, what: str, budget: Budget, trace: Trace) -> LLMResponse:
        """A model call charged to the budget; past the budget only the rules answer."""
        started = time.perf_counter()
        allowed = budget.take_llm(what)
        reply = self.gateway.complete(request, slots=None if allowed else [])
        budget.spend_tokens(reply.tokens_in + reply.tokens_out)
        trace.add(what, reply.slot, "cached" if reply.cached else "ok", started,
                  ",".join(f"{a.slot}={a.outcome.value}" for a in reply.attempts))
        return reply

    def vote_call(self, budget: Budget, trace: Trace
                  ) -> Callable[[LLMRequest, str, Sequence[str]], LLMResponse | None]:
        """A voter call pinned to the given models, never the rules, charged to the budget."""
        def call(request: LLMRequest, what: str, slots: Sequence[str]) -> LLMResponse | None:
            if not budget.take_llm(what):
                return None
            started = time.perf_counter()
            try:
                reply = self.gateway.complete(request, slots=slots, rules_fallback=False)
            except NoProviderAvailable as exc:
                trace.add(what, ",".join(slots), "unavailable", started,
                          ",".join(f"{a.slot}={a.outcome.value}" for a in exc.attempts))
                return None
            budget.spend_tokens(reply.tokens_in + reply.tokens_out)
            trace.add(what, reply.slot, "cached" if reply.cached else "ok", started)
            return reply
        return call

    def _plan(self, ctx: ToolContext, question: str, language: str | None, private: bool,
              party_names: tuple[str, ...], budget: Budget, trace: Trace) -> Plan:
        anon = anonymise(question, vault=self.vault, tenant=ctx.tenant_id, anchor=ctx.as_of,
                         party_names=party_names)
        try:
            reply = self.llm(plan_request(anon.text, private=private, party_names=party_names),
                             "plan", budget, trace)
            return build_plan(reply.data, question, self.registry, planner=reply.slot,
                              language=language, asked=anon.text)
        except PrivacyViolation as exc:
            # Something the anonymiser missed: plan locally, nothing leaves the server.
            trace.add("plan", "deterministic", "privacy_blocked", time.perf_counter(),
                      ",".join(k.value for k in exc.kinds))
            return build_plan(rules.plan(question), question, self.registry,
                              planner="deterministic", language=language)

    # ------------------------------------------------------------------ the run

    def ask(self, ctx: ToolContext, question: str, *, language: str | None = None,
            role: Role = Role.owner, actor: str = "copilot", private: bool = False,
            party_names: Iterable[str] = (), budget: Budget | None = None) -> Run:
        budget = budget or Budget()
        trace = Trace()
        rec_id = recommendation_id(ctx.tenant_id, question, ctx.now)
        names = tuple(party_names)
        if self.guard:
            started = time.perf_counter()
            with ctx.db() as store:
                verdict = screen(store.session, ctx.tenant_id, actor, question,
                                 Source.user_message, ctx.now)
            trace.add("guard", "injection", "allowed" if verdict.allowed else "quarantined",
                      started, ",".join(verdict.rule_ids))
            if not verdict.allowed:
                plan = Plan((), (), language or rules.language_of(question), "none")
                abstention = abstain.policy(detail=f"quarantined:{verdict.quarantine_id}")
                return self._finish(ctx, rec_id, QUARANTINED, plan, abstention=abstention,
                                    actor=actor, budget=budget, trace=trace)
        plan = self._plan(ctx, question, language, private, names, budget, trace)
        if not plan.understood:
            return self._finish(ctx, rec_id, question, plan,
                                abstention=abstain.out_of_scope(detail="not_understood"),
                                actor=actor, budget=budget, trace=trace)
        runner = ToolRunner(self.registry, ctx, budget, plan.params, trace)
        subagents = plan.subagents()
        with ThreadPoolExecutor(max_workers=max(1, min(len(subagents), self.max_workers)),
                                thread_name_prefix="subagent") as pool:
            for future in [pool.submit(runner.run_all, tools) for _, tools in subagents]:
                future.result()
        results, errors = runner.results(), runner.errors()
        primary = set(subagents[0][1]) if subagents else set()
        primary_errors = {n: e for n, e in errors.items() if n in primary}
        skipped = {n: str(e) for n, e in errors.items() if n not in primary}
        composed = claims_mod.compose(results, plan.tools, plan.language)
        if primary_errors or not composed:
            abstention = abstention_for(primary_errors or errors) if (primary_errors or errors) \
                else abstain.unverifiable(detail="nothing_to_report")
            return self._finish(ctx, rec_id, question, plan, results=results, skipped=skipped,
                                abstention=abstention, actor=actor, budget=budget, trace=trace)
        checker = Checker(ctx, results)
        statements, checks = self.verify(checker, composed, ctx, rec_id, trace)
        cards, dropped = self.verified_cards(checker, self.cards(results, role, limit=None))
        if not statements:
            abstention = abstain.unverifiable(
                detail="; ".join(sorted({c.reason or "" for c in checks})))
            return self._finish(ctx, rec_id, question, plan, results=results, skipped=skipped,
                                abstention=abstention, checks=checks, actor=actor,
                                budget=budget, trace=trace)
        answer, narrator = self._narrate(statements, plan, private, budget, trace)
        stakes = assess(plan.intents, cards)
        objection = None
        if stakes.needs_critic:  # N11: every material recommendation gets the case against
            found = critic_mod.risks(results, cards, plan.language,
                                     history_days=ctx.history_days, data_mode=ctx.data_mode)
            objection = critic_mod.critique(
                lambda request, what: self.llm(request, what, budget, trace), answer,
                statements, found, language=plan.language,
                brain_families=(self.family(plan.planner), narrator), private=private)
        agreement = stability = None
        judgement = (agreement_mod.judgement_for(plan, results, cards, plan.asked)
                     if stakes.needs_agreement else None)
        if judgement is not None:  # N9: other models vote on the judgement code made
            agreement = agreement_mod.agree(self.vote_call(budget, trace), judgement, stakes,
                                            private=private)
            started = time.perf_counter()  # N10: the engines re-make it under stress
            stability = self_loop(ctx, judgement, stakes, results, rec_id)
            if stability is not None:
                trace.add("selfloop", judgement.kind, f"score {stability.score}", started,
                          ",".join(stability.what_would_flip))
        # N17: withhold the answer when the checks do not back it, at the stakes' threshold
        withheld = abstain.after_checks(stakes, checks, agreement, stability)
        return self._finish(ctx, rec_id, question, plan, results=results, skipped=skipped,
                            statements=statements, answer=answer, cards=cards, checks=checks,
                            dropped_cards=dropped, stakes=stakes, objection=objection,
                            agreement=agreement, stability=stability, abstention=withheld,
                            actor=actor, budget=budget, trace=trace)

    def family(self, slot: str) -> str:
        provider = self.gateway.table.get(slot)
        return provider.family if provider is not None else "rules"

    @staticmethod
    def verify(checker: Checker, composed: list[Statement], ctx: ToolContext, rec_id: str,
               trace: Trace) -> tuple[list[Statement], tuple[CheckResult, ...]]:
        """Recompute every claim; keep the verified ones, log and drop the rest."""
        started = time.perf_counter()
        checks = tuple(checker.check_statements(composed))
        verified = [s for s, c in zip(composed, checks, strict=True)
                    if c.status is CheckStatus.verified]
        with ctx.db() as store:
            refused = log_rejections(checks, {s.claim.id: s.claim for s in composed},
                                     tenant_id=ctx.tenant_id, recommendation_id=rec_id,
                                     now=ctx.now, session=store.session)
        trace.add("check", "claims", f"{len(verified)} verified, {refused} removed", started)
        return verified, checks

    @staticmethod
    def verified_cards(checker: Checker, cards: tuple[ActionCard, ...]
                       ) -> tuple[tuple[ActionCard, ...], tuple[str, ...]]:
        """A card whose impact or cost does not recompute is dropped; a supporting figure
        that cannot be recomputed is taken off the card."""
        kept: list[ActionCard] = []
        dropped: list[str] = []
        for card in cards:
            heads = [f for f in (card.impact, card.cost) if f is not None]
            if any(checker.check_figure(f) is not CheckStatus.verified for f in heads):
                dropped.append(card.id)
                continue
            statuses = {f.id: checker.check_figure(f) for f in card.figures}
            if any(s is CheckStatus.rejected for s in statuses.values()):
                dropped.append(card.id)
                continue
            figures = tuple(f for f in card.figures if statuses[f.id] is CheckStatus.verified)
            kept.append(card.model_copy(update={"figures": figures}))
            if len(kept) == MAX_CARDS:
                break
        return tuple(kept), tuple(dropped)

    def _narrate(self, statements: list[Statement], plan: Plan, private: bool, budget: Budget,
                 trace: Trace) -> tuple[str, str]:
        """The answer text and the family that wrote it ("rules" for the claim texts)."""
        texts = [s.claim.text for s in statements]
        fallback = " ".join(texts), "rules"
        reply = self.llm(narrate_request(texts, language=plan.language, private=private),
                         "narrate", budget, trace)
        text = (reply.data or {}).get("text")
        if reply.deterministic or not isinstance(text, str) or not text.strip():
            return fallback
        invented = unverified_numbers(text, statements)
        if invented:  # a narrated number no verified claim states: use the claims themselves
            trace.add("check", "narration", "rejected", time.perf_counter(),
                      ",".join(sorted(str(n) for n in invented)))
            return fallback
        return text, reply.family

    @staticmethod
    def cards(results: Mapping[str, ToolResult], role: Role,
              limit: int | None = MAX_CARDS) -> tuple[ActionCard, ...]:
        """Cards in plan priority that the caller's role may at least draft (the approval
        flow decides who executes); at most `limit`."""
        out: list[ActionCard] = []
        for name in CARD_SOURCES:
            result = results.get(name)
            for card in result.cards if result is not None else ():
                if card.id in {c.id for c in out}:
                    continue
                if policy.decide(role, card.action_type, card.tier).allowed or \
                        policy.may_request(role, card.action_type):
                    out.append(card)
        return tuple(out if limit is None else out[:limit])

    def _finish(self, ctx: ToolContext, rec_id: str, question: str, plan: Plan, *,
                results: Mapping[str, ToolResult] | None = None,
                skipped: Mapping[str, str] | None = None,
                statements: list[Statement] | None = None, answer: str | None = None,
                cards: tuple[ActionCard, ...] = (), abstention: Abstention | None = None,
                checks: tuple[CheckResult, ...] = (), dropped_cards: tuple[str, ...] = (),
                stakes: Stakes | None = None, objection: Objection | None = None,
                agreement: AgreementOutcome | None = None,
                stability: StabilityReport | None = None, actor: str = "copilot",
                budget: Budget, trace: Trace) -> Run:
        results = results or {}
        statements = statements or []
        figures: dict[str, Figure] = {s.figure.id: s.figure for s in statements}
        for card in cards:
            for fig in (*card.figures, card.impact, card.cost):
                if fig is not None:
                    figures.setdefault(fig.id, fig)
        modes = [r.data_mode for r in results.values()] or [ctx.data_mode]
        recommendation = Recommendation(
            id=rec_id, tenant_id=ctx.tenant_id, question=question,
            answer_text=answer if abstention is None else None,
            claims=tuple(s.claim for s in statements) if abstention is None else (),
            checks=checks,
            action_cards=cards if abstention is None else (),
            figures=tuple(figures.values()) if abstention is None else (),
            critic_objection=objection.text if objection and abstention is None else None,
            agreement=agreement.report if agreement is not None else None,
            stability=stability,
            abstention=abstention, tools_used=tuple(n for n in plan.tools if n in results),
            data_mode=most_cautious(modes) if modes else DataMode.synthetic,
            created_at=ctx.now)
        if abstention is not None:  # every abstention is logged and audited
            with ctx.db() as store:
                abstain.record(store.session, tenant_id=ctx.tenant_id,
                               recommendation_id=rec_id, question=question,
                               abstention=abstention, stakes=stakes, actor=actor, now=ctx.now)
        return Run(recommendation=recommendation, plan=plan, statements=tuple(statements),
                   results=dict(results), skipped=dict(skipped or {}), checks=checks,
                   dropped_cards=dropped_cards, stakes=stakes, objection=objection,
                   agreement=agreement, budget=budget.report(), trace=trace.events())
