"""`npm run eval`: run the evaluation tasks and write the logs (WP-16 milestone 1).

    npm run eval                         # offline: recorded fixtures, no network (default)
    npm run eval -- --live               # the configured providers, keys from backend/.env
    npm run eval -- --suite adversarial  # one suite
    npm run eval -- --only F.cash.gap.en --only A.skip_approval.zh.0
    npm run eval -- --strict             # exit 1 when any task fails (for CI)

Logs go to docs/submission/evidence/eval/<offline|live>/: tasks/<id>.jsonl (one line per
step), results.jsonl (one line per task) and summary.json. `npm run evidence` turns the
summary into the evidence README.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from eval.tasks import REPO, Task, all_tasks

OUT = REPO / "docs" / "submission" / "evidence" / "eval"


def commit() -> str | None:
    """The commit the logs come from; "+local" when backend code differs from it."""
    try:
        head = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO,  # noqa: S607
            capture_output=True, text=True, check=False)
        local = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "diff", "--quiet", "HEAD", "--", "backend"], cwd=REPO,  # noqa: S607
            capture_output=True, check=False)
    except OSError:
        return None
    sha = head.stdout.strip()
    return (sha + ("+local" if local.returncode else "")) if sha else None


def select(tasks: tuple[Task, ...], suite: str | None, only: list[str] | None
           ) -> list[Task]:
    chosen = [t for t in tasks if suite is None or t.suite == suite]
    if only:
        unknown = set(only) - {t.id for t in tasks}
        if unknown:
            raise SystemExit(f"eval: unknown task id(s): {', '.join(sorted(unknown))}")
        chosen = [t for t in chosen if t.id in only]
    return chosen


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="eval", description=__doc__.split("\n\n")[0])
    parser.add_argument("--live", action="store_true",
                        help="call the configured model providers instead of the fixtures")
    parser.add_argument("--suite", choices=("functional", "adversarial"))
    parser.add_argument("--only", action="append", metavar="TASK_ID")
    parser.add_argument("--out", type=Path, help="log directory (default: evidence/eval/<mode>)")
    parser.add_argument("--strict", action="store_true", help="exit 1 if any task fails")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse(argv)
    # Imported here so `--help` and argument errors answer without loading the engines.
    from eval import runner

    mode = "live" if args.live else "offline"
    tasks = select(all_tasks(), args.suite, args.only)
    out = args.out or OUT / mode
    settings = runner.live_settings() if args.live else runner.offline_settings()
    bench = runner.Bench.build(settings)
    records = []
    try:
        for i, task in enumerate(tasks, start=1):
            record = runner.run_task(bench, task)
            records.append(record)
            mark = "pass" if record.passed else "FAIL"
            print(f"[{i:>2}/{len(tasks)}] {mark}  {task.id}  ({record.ms} ms)", flush=True)
            for check in record.checks:
                if not check.passed:
                    print(f"         - {check.name}: {check.detail}", flush=True)
        usage = bench.orchestrator.gateway.usage()
    finally:
        bench.close()
    summary = runner.summarise(records, mode=mode, settings=settings, usage=usage,
                               commit=commit())
    runner.write_logs(out, records, summary, mode)
    for source, report in summary["attacks"].items():
        n = report["caught"]["total"]
        print(f"attacks ({source}): caught {report['caught']['passed']}/{n}, contained "
              f"{report['contained']['passed']}/{n}, approval held "
              f"{report['approval_held']['passed']}/{n}")
    totals = summary["tasks"]
    print(f"eval ({mode}): {totals['passed']}/{totals['total']} tasks passed "
          f"(functional {summary['functional']['passed']}/{summary['functional']['total']}, "
          f"adversarial {summary['adversarial']['passed']}/{summary['adversarial']['total']}). "
          f"Logs: {out}")
    return 1 if args.strict and totals["passed"] < totals["total"] else 0


if __name__ == "__main__":
    sys.exit(main())
