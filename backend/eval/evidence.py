"""`npm run evidence`: write test counts per layer to docs/submission/evidence/.

WP-00 stub. WP-16 milestone 6 extends it with eval results, mutation score, backtests,
security scans and hosted e2e artefacts.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
OUT = REPO / "docs" / "submission" / "evidence"


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


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    backend = backend_counts()
    web = web_count()
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Test counts by layer",
        "",
        f"Generated {stamp} by `npm run evidence`.",
        "Every test runs offline: no real LLM call, no network.",
        "",
        "| Layer | Area | Tests |",
        "| --- | --- | --- |",
    ]
    lines += [f"| Backend (pytest) | {area} | {n} |" for area, n in sorted(backend.items())]
    lines.append(f"| **Backend total** | | **{sum(backend.values())}** |")
    lines.append(f"| Web units (Vitest) | all | {web if web is not None else 'n/a'} |")
    total = sum(backend.values()) + (web or 0)
    lines += [f"| **Total** | | **{total}** |", ""]
    (OUT / "test-counts.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
