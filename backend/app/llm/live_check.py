"""Live LLM check: real calls to every provider, saved as evidence and as fixtures (WP-10).

    uv --directory backend run python -m app.llm.live_check [--slot groq_qwen] [--model slot=id]

Sends one synthetic, anonymised probe per task (plan, vote, critique) to each model slot
through the gateway (privacy gate included), pinned to that slot with no fallback. Each
answer is recorded as a fixture under `backend/tests/fixtures/llm/<slot>/` (source "live"),
which the offline tests then replay, and one JSON line per call goes to
`backend/tests/fixtures/llm/traces/live-<UTC time>.jsonl`: slot, model, task, outcome,
latency, tokens, prompt hash. Keys come from `backend/.env` through Settings and are never
printed. Tests never run this module (they cannot reach the network).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from app.llm.cache import MemoryCache
from app.llm.gateway import LLMGateway, NoProviderAvailable
from app.llm.messages import LLMRequest
from app.llm.prompts import critique_request, plan_request, vote_request
from app.llm.providers import PROVIDERS
from app.llm.transport import (
    FIXTURES_DIR,
    FixtureStore,
    OpenAICompatTransport,
    RecordingTransport,
    Transport,
)
from app.security.clock import Clock, system_clock
from app.settings import AppEnv, LLMMode, Settings

# Synthetic and anonymised already: labels instead of names, no dates, no identifiers.
PROBES: tuple[tuple[str, LLMRequest], ...] = (
    ("plan", plan_request("Will I have enough cash to pay Supplier 1 next month, or do I "
                          "need a loan?")),
    ("vote", vote_request(
        "Which financing option fits a short gap of Tk 80000 for 45 days best?",
        [{"id": "opt_overdraft", "summary": "bank overdraft, APR 14.5%, approval 7 days"},
         {"id": "opt_mfi", "summary": "microfinance loan, APR 24%, approval 2 days"},
         {"id": "opt_supplier", "summary": "supplier credit, 30 extra days, 2% fee"}],
        default="opt_overdraft")),
    ("critique", critique_request(
        "Take the bank overdraft of Tk 80000 to cover the gap starting day t+12.",
        ["cash gap of Tk 80000 from day t+12 to day t+57",
         "Customer 1 owes Tk 65000, 40 days overdue",
         "overdraft APR 14.5%, approval takes 7 days"])),
)


def run(settings: Settings, slots: Sequence[str], models: dict[str, str],
        store: FixtureStore, trace_dir: Path, *, transport: Transport | None = None,
        clock: Clock = system_clock) -> int:
    """Returns the exit code: 0 when every probe got an answer."""
    recorder = RecordingTransport(transport or OpenAICompatTransport(settings), store, clock)
    gateway = LLMGateway(settings, transport=recorder, cache=MemoryCache(), clock=clock,
                         models=models, enforce_budgets=True)
    trace_dir.mkdir(parents=True, exist_ok=True)
    trace = trace_dir / f"live-{clock().strftime('%Y%m%dT%H%M%SZ')}.jsonl"
    failures = 0
    with trace.open("w", encoding="utf-8", newline="\n") as out:
        for slot in slots:
            provider = gateway.table[slot]
            for task, request in PROBES:
                started = time.perf_counter()
                row: dict[str, object] = {"slot": slot, "model": provider.model, "task": task,
                                          "prompt_hash": request.prompt_hash()}
                try:
                    reply = gateway.complete(request, slots=[slot], rules_fallback=False)
                    row |= {"outcome": "ok", "tokens_in": reply.tokens_in,
                            "tokens_out": reply.tokens_out, "answer": reply.data}
                except NoProviderAvailable as exc:
                    failures += 1
                    row |= {"outcome": exc.attempts[-1].outcome.value if exc.attempts
                            else "skipped"}
                row["latency_ms"] = round((time.perf_counter() - started) * 1000)
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                print(f"{slot:<20} {task:<9} {row['outcome']:<14} {row['latency_ms']} ms")
    print(f"trace: {trace}\nfixtures recorded: {len(recorder.recorded)}")
    return 1 if failures else 0


def main(argv: Sequence[str] | None = None) -> int:
    model_slots = [s for s, p in PROVIDERS.items() if not p.deterministic]
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--slot", action="append", choices=model_slots,
                        help="check only this slot (repeatable); default: every model slot")
    parser.add_argument("--model", action="append", default=[], metavar="SLOT=MODEL",
                        help="override a slot's model id, e.g. gemini_flash=gemini-3-flash")
    parser.add_argument("--out", type=Path, default=FIXTURES_DIR,
                        help="fixture root (default: backend/tests/fixtures/llm)")
    args = parser.parse_args(argv)
    settings = Settings().model_copy(update={"llm_mode": LLMMode.live})
    if settings.app_env is AppEnv.test:
        print("refusing to call real models with APP_ENV=test", file=sys.stderr)
        return 2
    models = dict(item.split("=", 1) for item in args.model)
    return run(settings, args.slot or model_slots, models, FixtureStore(args.out),
               args.out / "traces")


if __name__ == "__main__":
    raise SystemExit(main())
