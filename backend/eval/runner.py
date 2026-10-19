"""Runs the evaluation tasks and writes the step logs (WP-16 milestone 1; deliverable 06).

    bench = Bench.build(settings)          # the five synthetic shops + a 30-day shop, in memory
    record = run_task(bench, task)         # the real orchestrator answers; the rules score it
    write_logs(out_dir, records, summary)  # one JSONL file per task, results.jsonl, summary.json

Every task goes through the same path as `POST /api/copilot/ask`: the injection guard, the
planner (a recorded model answer when one exists, else the deterministic planner), the
engine tools, the checker, the critic, the agreement vote and the self-loop. Offline (the
default) the gateway replays the recorded fixtures and never opens a socket; `--live` calls
the configured providers through the same gateway, with the same privacy gate.

Log format, one JSON object per line, in order:

    {"seq": 0, "event": "task", ...}      the input, the role and the expected outcome
    {"seq": n, "event": "step", ...}      one per orchestrator step: guard, plan, tool, check,
                                           narrate, critique, vote, selfloop; a tool step
                                           lists the figures it produced (value, formula)
    {"event": "answer" | "abstain", ...}  what the owner would see (claims with their checks,
                                           cards with their tiers) or why it abstained
    {"event": "score", ...}               every check, passed or not, with its detail
"""

from __future__ import annotations

import json
import time
import traceback
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agents.budget import Budget
from app.agents.orchestrator import Orchestrator, Run
from app.agents.tools import ToolContext, ToolResult
from app.contracts import VariationKind
from app.db import init_db, make_engine, session_factory
from app.facts import FactStore
from app.facts.seed import load_sme_into
from app.llm import LLMGateway
from app.privacy import TokenVault
from app.settings import Settings
from app.synthetic import Universe, load_universe
from eval.scoring import Check, score
from eval.tasks import THIN_TENANT, Task

# The universe's as-of day, evening in Dhaka: fixed, so recommendation ids and logs repeat.
NOW = datetime(2026, 9, 30, 18, 0, tzinfo=UTC)
THIN_DAYS = 30
THIN_SOURCE = "sme_grocery"


def offline_settings() -> Settings:
    """Recorded fixtures only: no key, no socket (CLAUDE.md rule 6)."""
    return Settings(_env_file=None, app_env="test", demo_mode=True, database_url="sqlite://",
                    llm_mode="fixtures", chain_mode="offline")


def live_settings() -> Settings:
    """The configured providers; keys come from backend/.env, read by Settings only."""
    return Settings(app_env="development", demo_mode=True, database_url="sqlite://",
                    llm_mode="live", chain_mode="offline")


@dataclass
class Bench:
    """The system under test: an in-memory ledger with the synthetic shops, one orchestrator."""

    settings: Settings
    universe: Universe
    store: FactStore
    session: Session
    orchestrator: Orchestrator

    @classmethod
    def build(cls, settings: Settings, universe: Universe | None = None) -> Bench:
        universe = universe or load_universe()
        engine = make_engine("sqlite://")
        init_db(engine)
        session = session_factory(engine)()
        store = FactStore(session)
        for sme in universe.smes.values():
            load_sme_into(store, sme, universe.start, universe.as_of)
        recent = [t for t in universe.smes[THIN_SOURCE].transactions
                  if (universe.as_of - t.day).days < THIN_DAYS]
        store.add_transactions(t.model_copy(update={"tenant_id": THIN_TENANT,
                                                    "id": f"thin-{t.id}"}) for t in recent)
        session.commit()
        # A fixed vault key keeps the anonymised question (and so the prompt hash) repeatable.
        orchestrator = Orchestrator(LLMGateway(settings), vault=TokenVault(b"\x16" * 32))
        return cls(settings, universe, store, session, orchestrator)

    def close(self) -> None:
        bind = self.session.get_bind()
        self.session.close()
        bind.dispose()


@dataclass
class Record:
    task: Task
    run: Run | None
    checks: list[Check]
    ms: int
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.error is None and all(c.passed for c in self.checks)


def run_task(bench: Bench, task: Task) -> Record:
    ctx = ToolContext(bench.store, task.tenant, NOW)
    budget = Budget() if task.max_tool_calls is None else Budget(
        max_tool_calls=task.max_tool_calls)
    started = time.perf_counter()
    try:
        run = bench.orchestrator.ask(ctx, task.question, role=task.role,
                                     actor=f"eval:{task.id}", budget=budget)
    except Exception as exc:  # one broken task must not stop the suite
        bench.session.rollback()
        ms = round((time.perf_counter() - started) * 1000)
        error = f"{type(exc).__name__}: {exc}"
        tb = traceback.format_exception_only(type(exc), exc)[-1].strip()
        return Record(task, None, [Check("ran", False, tb)], ms, error)
    ms = round((time.perf_counter() - started) * 1000)
    bench.session.commit()
    return Record(task, run, score(task, run, bench), ms)


# ---------------------------------------------------------------- JSON


def plain(value: Any) -> Any:
    """JSON-ready: Decimals as exact strings, dates ISO, contracts as their JSON form."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [plain(v) for v in value]
    return value


def dumps(obj: dict[str, Any]) -> str:
    return json.dumps(plain(obj), ensure_ascii=False, separators=(", ", ": "))


# ---------------------------------------------------------------- per-task log


def _tool_output(result: ToolResult | None) -> dict[str, Any]:
    if result is None:
        return {}
    out: dict[str, Any] = {
        "figures": [{"id": f.id, "label": f.label_key, "value": f.value, "unit": f.unit,
                     "formula": f.provenance.formula_id} for f in result.figures]}
    if result.notes:
        out["notes"] = list(result.notes)
    if result.cards:
        out["cards"] = [{"id": c.id, "action": c.action_type, "tier": c.tier}
                        for c in result.cards]
    return out


def _steps(run: Run) -> Iterable[dict[str, Any]]:
    planned = False
    for event in run.trace:
        step: dict[str, Any] = {"event": "step", "step": event.step, "name": event.name,
                                "outcome": event.outcome, "ms": event.ms}
        if event.detail:
            key = {"guard": "rules", "plan": "attempts", "narrate": "attempts",
                   "critique": "attempts"}.get(event.step, "detail")
            step[key] = event.detail
        if event.step == "plan" and not planned:
            planned = True
            plan = run.plan
            step["plan"] = {"planner": plan.planner, "intents": list(plan.intents),
                            "tools": list(plan.tools), "language": plan.language,
                            "params": plan.params, "model_saw": plan.asked}
            if plan.dropped:
                step["plan"]["dropped"] = list(plan.dropped)
        if event.step == "tool" and event.outcome == "ok":
            step.update(_tool_output(run.results.get(event.name)))
        yield step


def _outcome(run: Run) -> dict[str, Any]:
    rec = run.recommendation
    if rec.abstention is not None:
        return {"event": "abstain", "reason": rec.abstention.reason,
                "missing": list(rec.abstention.missing), "detail": rec.abstention.detail,
                "message_key": rec.abstention.message_key, "data_mode": rec.data_mode,
                "budget": run.budget}
    checks = {c.claim_id: c for c in rec.checks}
    out: dict[str, Any] = {
        "event": "answer", "language": run.plan.language, "answer": rec.answer_text,
        "claims": [{"id": c.id, "value": c.value, "unit": c.unit, "formula": c.formula_id,
                    "check": checks[c.id].status if c.id in checks else None}
                   for c in rec.claims],
        "cards": [{"id": c.id, "action": c.action_type, "tier": c.tier,
                   "needs_owner_approval": c.requires_approval} for c in rec.action_cards],
        "tools_used": list(rec.tools_used), "data_mode": rec.data_mode,
        "stakes": run.stakes, "budget": run.budget}
    if run.dropped_cards:
        out["dropped_cards"] = list(run.dropped_cards)
    if rec.critic_objection:
        out["critic"] = {"objection": rec.critic_objection,
                         "by": run.objection.family if run.objection else None}
    if rec.agreement is not None:
        out["agreement"] = {"rate": rec.agreement.agreement_rate,
                            "threshold": rec.agreement.threshold,
                            "votes": [{"model": v.model, "choice": v.choice}
                                      for v in rec.agreement.votes]}
    if rec.stability is not None:
        out["stability"] = {"score": rec.stability.score,
                            "what_would_flip": list(rec.stability.what_would_flip),
                            "variations": [{"name": r.name, "kind": r.kind, "held": r.held}
                                           for r in rec.stability.results]}
    if run.skipped:
        out["skipped"] = dict(run.skipped)
    return out


def task_lines(record: Record, mode: str) -> list[str]:
    task = record.task
    header: dict[str, Any] = {
        "event": "task", "task": task.id, "suite": task.suite, "feature": task.feature,
        "title": task.title, "tenant": task.tenant, "role": task.role, "mode": mode,
        "as_of": NOW, "input": task.question, "expected": task.expect.as_json(),
        "data_mode": "synthetic"}
    if task.max_tool_calls is not None:
        header["max_tool_calls"] = task.max_tool_calls
    if task.tags:
        header["tags"] = dict(task.tags)
    events = [header]
    if record.run is not None:
        events += list(_steps(record.run))
        events.append(_outcome(record.run))
    else:
        events.append({"event": "error", "error": record.error})
    events.append({"event": "score", "passed": record.passed, "ms": record.ms,
                   "checks": [c.as_json() for c in record.checks]})
    return [dumps({"seq": i, **e}) for i, e in enumerate(events)]


def result_line(record: Record) -> dict[str, Any]:
    run = record.run
    rec = run.recommendation if run else None
    got = None if rec is None else (rec.abstention.reason.value if rec.abstention else "answer")
    return {"task": record.task.id, "suite": record.task.suite,
            "feature": record.task.feature, "title": record.task.title,
            "passed": record.passed, "outcome": got,
            "tools": sorted({e.name for e in run.trace if e.step == "tool"}) if run else [],
            "failed": [c.as_json() for c in record.checks if not c.passed], "ms": record.ms,
            **({"tags": dict(record.task.tags)} if record.task.tags else {})}


# ---------------------------------------------------------------- summary


def _rate(passed: int, total: int) -> dict[str, Any]:
    return {"total": total, "passed": passed,
            "rate": str((Decimal(passed) / total).quantize(Decimal("0.001"))) if total else None}


def _group(records: list[Record], key: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[Record]] = {}
    for record in records:
        groups.setdefault(record.task.tags[key], []).append(record)
    return {k: _rate(sum(r.passed for r in v), len(v)) for k, v in sorted(groups.items())}


def summarise(records: list[Record], *, mode: str, settings: Settings,
              usage: dict[str, Any], commit: str | None) -> dict[str, Any]:
    functional = [r for r in records if r.task.suite == "functional"]
    attacks = [r for r in records if r.task.suite == "adversarial"]
    features: dict[str, list[Record]] = {}
    for record in functional:
        features.setdefault(record.task.feature, []).append(record)
    runs = [r.run for r in records if r.run is not None]
    should_abstain = [r for r in functional if r.task.expect.abstain is not None]
    should_answer = [r for r in functional if r.task.expect.abstain is None]
    abstained = [r for r in should_abstain if r.run and r.run.recommendation.abstention]
    false_abstain = [r for r in should_answer if r.run and r.run.recommendation.abstention]
    claims = [c for run in runs for c in run.recommendation.claims]
    verified = [c for run in runs for c in run.recommendation.checks
                if c.status.value == "verified"]
    votes = [run.recommendation.agreement for run in runs if run.recommendation.agreement]
    noise = [v for run in runs if run.recommendation.stability
             for v in run.recommendation.stability.results if v.kind is VariationKind.noise]
    times = sorted(r.ms for r in records)
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "mode": mode, "llm_mode": settings.llm_mode.value, "commit": commit,
        "as_of": NOW.isoformat(), "data_mode": "synthetic",
        "tasks": _rate(sum(r.passed for r in records), len(records)),
        "functional": _rate(sum(r.passed for r in functional), len(functional)),
        "adversarial": _rate(sum(r.passed for r in attacks), len(attacks)),
        "by_feature": {k: _rate(sum(r.passed for r in v), len(v))
                       for k, v in sorted(features.items())},
        "attacks_caught": {
            "by_language": _group(attacks, "lang"), "by_paraphrase": _group(attacks, "paraphrase"),
            "by_family": _group(attacks, "family")} if attacks else {},
        "abstention": {
            "should_abstain": len(should_abstain), "did_abstain": len(abstained),
            "with_the_right_reason": sum(
                1 for r in abstained
                if r.run.recommendation.abstention.reason is r.task.expect.abstain),
            "should_answer": len(should_answer), "abstained_anyway": len(false_abstain)},
        "claims": {"shown": len(claims), "verified_by_checker": len(verified)},
        "reliability": {
            "agreement_votes": len(votes),
            "agreement_rate_mean": str(sum((v.agreement_rate for v in votes), Decimal(0))
                                       / len(votes)) if votes else None,
            "noise_variations": len(noise),
            "noise_flips": sum(1 for v in noise if not v.held)},
        "latency_ms": {"median": times[len(times) // 2] if times else None,
                       "max": times[-1] if times else None},
        "models": usage,
        "failures": [{"task": r.task.id, "failed": [c.as_json() for c in r.checks
                                                     if not c.passed]}
                     for r in records if not r.passed],
    }


def write_logs(out: Path, records: list[Record], summary: dict[str, Any], mode: str) -> None:
    logs = out / "tasks"
    logs.mkdir(parents=True, exist_ok=True)
    for stale in logs.glob("*.jsonl"):
        stale.unlink()
    for record in records:
        (logs / f"{record.task.id}.jsonl").write_text(
            "\n".join(task_lines(record, mode)) + "\n", encoding="utf-8", newline="\n")
    (out / "results.jsonl").write_text(
        "".join(dumps(result_line(r)) + "\n" for r in records), encoding="utf-8", newline="\n")
    (out / "summary.json").write_text(
        json.dumps(plain(summary), ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        newline="\n")
