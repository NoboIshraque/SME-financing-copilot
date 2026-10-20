"""Server label keys the demo API returns, for the web's i18n check (final audit, M14).

    npm run dev                                   # API on :8000, seeded demo data
    uv --directory backend run python ../scripts/server_keys.py

Signs in as three demo owners, calls the read routes, a financing match, a scenario comparison
with its stability re-run and three copilot questions, and collects every i18n key the answers
carry (label/title/reason/message/name/interpretation keys, ratio and metric names, audit
actions, variation names). Writes them to web/src/i18n/server-keys.json; the Vitest i18n suite
then checks each one is translated in en, bn and zh, so no screen falls back to English.
Uses only the local dev server; nothing leaves localhost.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

BASE = "http://localhost:8000"
OUT = Path(__file__).resolve().parents[1] / "web" / "src" / "i18n" / "server-keys.json"
OWNERS = ("owner@hardware.hishab.test", "owner@grocery.hishab.test", "owner@garment.hishab.test")
KEY_FIELDS = {"label_key", "title_key", "reason_key", "message_key", "name_key",
              "interpretation_key"}
READS = ("/api/cash/forecast", "/api/cash/gaps", "/api/cash/alerts", "/api/receivables",
         "/api/receivables/plan", "/api/analysis/statements", "/api/analysis/ratios",
         "/api/analysis/variance", "/api/mesh/obligations", "/api/mesh/rounds",
         "/api/reports/passport", "/api/copilot/today", "/api/copilot/today?language=bn",
         "/api/copilot/abstentions", "/api/messages/drafts", "/api/approvals",
         "/api/audit/events?limit=500")
QUESTIONS = ("Will I run out of cash next month?", "Which customer should I chase first?",
             "How is my business doing?")
DECISIONS = ["retime_supplier", "take_loan", "offer_discount", "do_nothing"]


def demo_code(email: str) -> str:
    accounts = httpx.get(f"{BASE}/api/auth/demo-accounts").json()
    return next(a["totp_hint"] for a in accounts if a["email"] == email)


def sign_in(email: str, password: str) -> httpx.Client:
    client = httpx.Client(base_url=BASE, headers={"Origin": "http://localhost:5173"}, timeout=300)
    answer = client.post("/api/auth/login", json={"email": email, "password": password})
    if answer.json().get("status") == "totp_required":
        for _ in range(3):  # a demo code is single-use per 30-second step
            if client.post("/api/auth/login/totp", json={"code": demo_code(email)}).is_success:
                break
            time.sleep(31)
    return client


def collect(value: object, keys: set[str]) -> None:
    if isinstance(value, dict):
        for name, item in value.items():
            if name in KEY_FIELDS and isinstance(item, str):
                keys.add(item)
            elif name == "reason_keys" and isinstance(item, list):
                keys.update(k for k in item if isinstance(k, str))
            else:
                collect(item, keys)
    elif isinstance(value, list):
        for item in value:
            collect(item, keys)


def main() -> None:
    passwords = {a["email"]: a["password"]
                 for a in httpx.get(f"{BASE}/api/auth/demo-accounts").json()}
    keys: set[str] = set()
    for email in OWNERS:
        client = sign_in(email, passwords[email])
        for path in READS:
            answer = client.get(path)
            answer.raise_for_status()
            body = answer.json()
            collect(body, keys)
            if path == "/api/analysis/ratios":
                keys.update(f"ratio.{r['name']}" for r in body)
            elif path == "/api/analysis/variance":
                keys.update(f"metric.{v['metric']}" for v in body["variances"])
            elif path.startswith("/api/audit/events"):
                keys.update(f"audit.{e['action']}" for e in body)
        collect(client.post("/api/financing/match", json={
            "amount": "50000", "purpose": "working_capital", "term_days": 180,
            "needed_by": "2026-10-25"}).json(), keys)
        comparison = client.post("/api/analysis/scenarios", json={"decisions": DECISIONS})
        if comparison.is_success:
            collect(comparison.json(), keys)
            stability = client.post("/api/analysis/stability", json={
                "recommendation_id": comparison.json()["recommendation_id"]})
            if stability.is_success:
                collect(stability.json(), keys)
                keys.update(f"variation.{r['name']}" for r in stability.json()["results"])
        for question in QUESTIONS:
            collect(client.post("/api/copilot/ask", json={"question": question}).json(), keys)
    OUT.write_text(json.dumps(sorted(keys), indent=2) + "\n", encoding="utf-8")
    print(f"{len(keys)} server keys written to {OUT}")


if __name__ == "__main__":
    main()
