"""`npm run evidence`: the execution evidence bundle (deliverable 06; WP-16 milestone 6).

    npm run evidence              # runs the offline eval, counts the tests, writes the index
    npm run evidence -- --no-eval # reuse the eval logs already in docs/submission/evidence/eval

Writes to docs/submission/evidence/:
    README.md        the index: what each file is, the eval results, honest limits
    test-counts.md   tests per layer (backend pytest areas, web Vitest)
    eval/<mode>/     the eval logs (`npm run eval`), one JSONL file per task

Mutation score and the nightly audit drill were cut on 19 Oct; backtests, security scans and
the hosted e2e run are published by their own work packages (e2e/ is WP-15's).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
OUT = REPO / "docs" / "submission" / "evidence"
EVAL = OUT / "eval"

FEATURES = {
    "Q1": "Cash-flow alerts (no false alarm)", "Q3": "Cash gaps found before they happen",
    "P1": "Financing options ranked by true cost", "C": "Business financial analysis",
    "N12": "What-if simulation", "N14": "Liquidity mesh: netting round",
    "N8": "Multi-agent orchestration", "N17": "Required \"I don't know\"",
    "P13": "Tool budget per run", "P2": "Permission tiers (no money moves)",
    "N18": "Anonymised model inputs", "P5": "Multilingual injection guard",
    "Q2": "Unpaid receivables, chased one by one", "N3": "Market watch (published prices)",
    "N19": "Negotiation support",
}
LANGUAGES = {"en": "English", "bn": "Bangla", "bl": "Banglish", "zh": "Chinese"}
SOURCES = {"corpus_test": "Corpus test split (regression)",
           "new": "New attacks, written blind (generalisation)"}


def backend_counts() -> Counter[str]:
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=BACKEND, capture_output=True, text=True, check=False,
    )
    counts: Counter[str] = Counter()
    for line in result.stdout.splitlines():
        match = re.match(r"tests/([^/:]+)/", line)
        if match and "::" in line:
            counts[match.group(1)] += 1
    return counts


def web_count() -> int | None:
    npm = shutil.which("npm")
    if npm is None:
        return None
    report = OUT / "vitest-report.json"
    subprocess.run(  # noqa: S603 - fixed argv, no shell
        [npm, "exec", "--", "vitest", "run", "--reporter=json", f"--outputFile={report}"],
        cwd=REPO / "web", capture_output=True, text=True, check=False,
    )
    try:
        return int(json.loads(report.read_text(encoding="utf-8"))["numTotalTests"])
    except (OSError, ValueError, KeyError):
        return None
    finally:
        report.unlink(missing_ok=True)


def counts_table(backend: Counter[str], web: int | None) -> list[str]:
    lines = ["| Layer | Area | Tests |", "| --- | --- | --- |"]
    lines += [f"| Backend (pytest) | {area} | {n} |" for area, n in sorted(backend.items())]
    lines.append(f"| **Backend total** | | **{sum(backend.values())}** |")
    lines.append(f"| Web units (Vitest) | all | {web if web is not None else 'n/a'} |")
    lines.append(f"| **Total** | | **{sum(backend.values()) + (web or 0)}** |")
    return lines


# ---------------------------------------------------------------- the index


def load(mode: str) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    folder = EVAL / mode
    try:
        summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
        results = [json.loads(line) for line in
                   (folder / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    except OSError:
        return None
    return summary, results


def pct(rate: dict[str, Any]) -> str:
    if not rate["total"]:
        return "n/a"
    return f"{rate['passed']}/{rate['total']} ({round(100 * rate['passed'] / rate['total'])}%)"


def eval_section(mode: str, summary: dict[str, Any], results: list[dict[str, Any]]) -> list[str]:
    title = "offline: recorded fixtures" if mode == "offline" else "live models"
    out = [f"## Evaluation harness ({title})", ""]
    if mode == "offline":
        out += [
            "The real copilot (its agent orchestrator) answers each task over the synthetic "
            "ledger. Model calls replay recorded answers; a prompt with no recording falls "
            "through the gateway's chain to the deterministic planner, exactly as when every "
            "model is down, and each step log shows those attempts. Nothing touches the "
            "network.", ""]
    out += [f"Run of commit `{summary.get('commit') or '?'}` at {summary['generated_at']}, "
            f"ledger as of {summary['as_of'][:10]}, all data synthetic.", "",
            "| Suite | Passed |", "| --- | --- |",
            f"| Functional | {pct(summary['functional'])} |",
            f"| Adversarial | {pct(summary['adversarial'])} |",
            f"| **All tasks** | **{pct(summary['tasks'])}** |", "",
            "### Functional tasks by feature", "",
            "| Feature | | Passed |", "| --- | --- | --- |"]
    out += [f"| {k} | {FEATURES.get(k, '')} | {pct(v)} |"
            for k, v in summary["by_feature"].items()]
    out += ["", "### Adversarial tasks", "",
            "Caught = quarantined by the injection guard before any model or tool saw it "
            "(the task's pass rule). Contained = got nothing back even where the guard "
            "missed: an abstention, no engine result. Approval held = no card let the caller "
            "skip the owner's approval with a step-up code.", "",
            "| Attacks | Caught | Contained | Approval held |", "| --- | --- | --- | --- |"]
    attacks = summary.get("attacks", {})
    for source, report in attacks.items():
        out.append(f"| {SOURCES.get(source, source)} | {pct(report['caught'])} | "
                   f"{pct(report['contained'])} | {pct(report['approval_held'])} |")
    out += ["", "| Language | " + " | ".join(SOURCES.get(s, s).split(" (")[0] for s in attacks)
            + " |", "| --- |" + " --- |" * len(attacks)]
    for lang, name in LANGUAGES.items():
        cells = [pct(r["by_language"][lang]) if lang in r["by_language"] else "-"
                 for r in attacks.values()]
        out.append(f"| {name} | " + " | ".join(cells) + " |")
    if "corpus_test" in attacks:
        out += ["", "Honest limit: the guard's rules were written with sight of the whole "
                "injection corpus (see `backend/app/security/guard_rules.py`), so the corpus "
                "test split measures regressions, not generalisation. The new attacks were "
                "written for this suite without reading the rules; their catch rate is the "
                "one to quote."]
    missed = [r for r in results if r["suite"] == "adversarial" and not r["passed"]]
    if missed:
        out += ["", "Attacks the guard missed, and what they reached:", ""]
        out += [f"- `{r['task']}`: {r['outcome']}"
                + (f", tools called {', '.join(r['tools'])}" if r["tools"] else ", no tool")
                for r in missed]
    out += ["", "### Reliability", ""]
    ab = summary["abstention"]
    out.append(f"- Abstention: {ab['did_abstain']} of {ab['should_abstain']} tasks that should "
               f"abstain did, {ab['with_the_right_reason']} with the expected reason; "
               f"{ab['abstained_anyway']} of {ab['should_answer']} answerable tasks abstained.")
    claims = summary["claims"]
    out.append(f"- Numbers shown: {claims['shown']} claims, {claims['verified_by_checker']} "
               "recomputed by the symbolic checker to the same value.")
    rel = summary["reliability"]
    out.append(f"- Noise (N16): {rel['noise_flips']} of {rel['noise_variations']} irrelevant "
               "variations in the self-loops flipped a decision.")
    if rel["agreement_votes"]:
        out.append(f"- Agreement (N9): {rel['agreement_votes']} votes taken, mean agreement "
                   f"{rel['agreement_rate_mean']}.")
    else:
        out.append("- Agreement (N9): no vote offline (the voters have no recordings); the "
                   "live run measures it.")
    lat = summary["latency_ms"]
    out += [f"- Latency per task: median {lat['median']} ms, max {lat['max']} ms.", "",
            "### Every task", "", "| Task | What it checks | Result | Outcome |",
            "| --- | --- | --- | --- |"]
    for r in results:
        link = f"[`{r['task']}`](eval/{mode}/tasks/{r['task']}.jsonl)"
        mark = "pass" if r["passed"] else "**FAIL**"
        out.append(f"| {link} | {r['title']} | {mark} | {r['outcome']} |")
    failures = [r for r in results if not r["passed"] and r["suite"] == "functional"]
    if failures:
        out += ["", "### Functional failures", ""]
        for r in failures:
            out.append(f"- `{r['task']}`: " + "; ".join(
                f"{c['name']}: {c.get('detail', '')}" for c in r["failed"]))
    return out + [""]


def readme(backend: Counter[str], web: int | None, stamp: str) -> str:
    lines = [
        "# Execution evidence (deliverable 06)", "",
        f"Generated {stamp} by `npm run evidence`. Every figure below comes from a run in "
        "this repository; all data is synthetic (`data_mode: \"synthetic\"`). The hand-written "
        "index (freeze record, sandbox operation log, worked examples, what the evidence does "
        "not show) is [`INDEX.md`](INDEX.md).", "",
        "| Path | What |", "| --- | --- |",
        "| `eval/offline/tasks/<task>.jsonl` | Step log of one eval task, one JSON object per "
        "line: the input and expected outcome, every orchestrator step (injection guard, "
        "plan, each tool call with the figures and formulas it produced, checker, narration, "
        "critic, votes, self-loop), what the owner would see, and the score with every check |",
        "| `eval/offline/results.jsonl` | One line per task: passed, outcome, tools, failed "
        "checks |",
        "| `eval/offline/summary.json` | Totals, attack catch rates, reliability metrics, model "
        "usage |"]
    if (EVAL / "live").is_dir():
        lines.append("| `eval/live/` | The same, with live models (`npm run eval -- --live`) |")
    lines += ["| `test-counts.md` | Tests per layer |"]
    if (OUT / "e2e").is_dir():
        lines.append("| `e2e/` | Hosted end-to-end browser runs (Playwright journeys) |")
    lines.append("")
    for mode in ("offline", "live"):
        loaded = load(mode)
        if loaded is not None:
            lines += eval_section(mode, *loaded)
    lines += [
        "## Not in this bundle", "",
        "- Mutation score and the nightly audit drill (P8): cut on 19 Oct.", "",
        "## Tests", "", *counts_table(backend, web), "",
        "## Reproduce", "", "```",
        "npm run eval                  # offline, from the recorded fixtures (about 2 minutes)",
        "npm run eval -- --live        # live models; keys in backend/.env",
        "npm run eval -- --only F.mesh.netting",
        "npm run evidence              # runs the offline eval, then writes this file", "```",
        ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evidence", description=__doc__.split("\n\n")[0])
    parser.add_argument("--no-eval", action="store_true",
                        help="reuse the eval logs instead of running the offline eval")
    args = parser.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    if not args.no_eval:
        from eval import run

        run.main([])
    backend = backend_counts()
    web = web_count()
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    counts = ["# Test counts by layer", "", f"Generated {stamp} by `npm run evidence`.",
              "Every test runs offline: no real LLM call, no network.", "",
              *counts_table(backend, web), ""]
    (OUT / "test-counts.md").write_text("\n".join(counts), encoding="utf-8", newline="\n")
    (OUT / "README.md").write_text(readme(backend, web, stamp), encoding="utf-8",
                                   newline="\n")
    print(f"evidence: wrote {OUT / 'README.md'} and {OUT / 'test-counts.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
