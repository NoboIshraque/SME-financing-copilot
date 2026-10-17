"""Rebuild the pinned "Mission control" GitHub issue (run by .github/workflows/mission-control.yml).

Body = each person's "Do this next" section from docs/NOW.md, the status board (docs/PLAN.md
section 8), open pull requests, the latest CI and Deploy runs on main, and the hosted site's
health. When a person's section changes, a comment @mentions only that person, so GitHub
Mobile pushes it to their phone. Standard library only; needs GITHUB_TOKEN and GITHUB_REPOSITORY.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LABEL = "mission-control"
TITLE = "Mission control: who does what next"
STATE_RE = re.compile(r"<!-- mission-state: (\{.*?\}) -->")
DHAKA = timedelta(hours=6)


def api(method: str, path: str, body: dict | None = None) -> object:
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed https host
        text = resp.read().decode()
    return json.loads(text) if text else None


def load_team(text: str) -> dict[str, str]:
    team = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" in line:
            key, value = (part.strip() for part in line.split(":", 1))
            team[key] = value
    return team


def split_sections(now_md: str) -> dict[str, str]:
    """`<!-- section: name -->` markers split NOW.md into per-person sections."""
    parts = re.split(r"<!-- section: ([a-z]+) -->", now_md)
    return {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}


def status_board(plan_md: str) -> str:
    match = re.search(r"## 8\. Status board.*?\n(\|.*?)(?:\n\n|\Z)", plan_md, re.S)
    return match.group(1).strip() if match else "_status board not found in docs/PLAN.md_"


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def site_health(domain: str) -> str:
    if not domain:
        return "not deployed yet (DEPLOY_DOMAIN not set)"
    try:
        with urllib.request.urlopen(f"https://{domain}/api/health", timeout=10) as resp:  # noqa: S310
            body = json.loads(resp.read().decode())
        return f"up at https://{domain} (contracts {body.get('contracts_version')})"
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return f"DOWN or unreachable: https://{domain} ({exc.__class__.__name__})"


def run_line(repo: str, workflow: str) -> str:
    runs = api("GET", f"/repos/{repo}/actions/workflows/{workflow}/runs?branch=main&per_page=1")
    items = runs.get("workflow_runs", []) if isinstance(runs, dict) else []
    if not items:
        return "no runs yet"
    run = items[0]
    result = run.get("conclusion") or run.get("status")
    icon = {"success": "✅", "failure": "❌", "cancelled": "⚪", "skipped": "⚪"}.get(result, "⏳")
    return f"{icon} {result} — [{run['head_sha'][:7]}]({run['html_url']})"


def build_body(repo: str, now_md: str, plan_md: str, team: dict[str, str],
               prs: list[dict], ci: str, deploy: str, health: str,
               sections: dict[str, str], state: dict[str, str]) -> str:
    stamp = (datetime.now(UTC) + DHAKA).strftime("%a %d %b %H:%M")
    lines = [f"_Updated automatically {stamp} Dhaka. Source: `docs/NOW.md` + `docs/PLAN.md`._", ""]
    for key in sections:
        lines += [sections[key], ""]
    lines += ["---", "### Build", f"- CI on main: {ci}", f"- Deploy: {deploy}",
              f"- Hosted site: {health}", "", "### Open pull requests"]
    if prs:
        lines += [f"- #{p['number']} {p['title']} (`{p['head']['ref']}`)" for p in prs]
    else:
        lines.append("- none")
    lines += ["", "### Status board", status_board(plan_md), "",
              f"<!-- mission-state: {json.dumps(state, sort_keys=True)} -->"]
    return "\n".join(lines)


def main() -> int:
    repo = os.environ["GITHUB_REPOSITORY"]
    now_md = (REPO_ROOT / "docs/NOW.md").read_text(encoding="utf-8")
    plan_md = (REPO_ROOT / "docs/PLAN.md").read_text(encoding="utf-8")
    team = load_team((REPO_ROOT / ".github/team.yml").read_text(encoding="utf-8"))
    sections = split_sections(now_md)
    state = {key: digest(text) for key, text in sections.items()}

    issues = api("GET", f"/repos/{repo}/issues?labels={LABEL}&state=open&per_page=5")
    issue = issues[0] if issues else None
    previous: dict[str, str] = {}
    if issue:
        found = STATE_RE.search(issue.get("body") or "")
        previous = json.loads(found.group(1)) if found else {}

    prs = api("GET", f"/repos/{repo}/pulls?state=open&per_page=30")
    health = site_health(os.environ.get("DEPLOY_DOMAIN", ""))
    body = build_body(repo, now_md, plan_md, team, prs, run_line(repo, "ci.yml"),
                      run_line(repo, "deploy.yml"), health, sections, state)
    if issue is None:
        issue = api("POST", f"/repos/{repo}/issues", {"title": TITLE, "body": body,
                                                     "labels": [LABEL]})
        print(f"created issue #{issue['number']} (pin it once: issue page → Pin issue)")
    else:
        api("PATCH", f"/repos/{repo}/issues/{issue['number']}", {"body": body})
        print(f"updated issue #{issue['number']}")

    changed = [key for key in sections if previous.get(key) != state[key]]
    if previous and changed:
        mentions = " ".join(f"@{team[k]}" for k in changed if k in team)
        names = ", ".join(k.capitalize() for k in changed)
        api("POST", f"/repos/{repo}/issues/{issue['number']}/comments",
            {"body": f"{mentions} your next steps changed ({names}). See the top of this issue."})
        print("notified:", mentions)
    return 0


if __name__ == "__main__":
    sys.exit(main())
