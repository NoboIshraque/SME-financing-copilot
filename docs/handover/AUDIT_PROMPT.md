# Final audit: prompt for a new Claude Code chat

For: Nobo. Start a **new** Claude Code chat with access to `NoboIshraque/SME-financing-copilot`
(cloud session or `C:\hishab\repo` on a PC that is not used by another session), paste the
whole box below, and let it run. It works on its own branch and opens a pull request; it never
merges. The result is a report at `docs/handover/AUDIT_REPORT.md` on branch `audit-final`.

```text
You are the final auditor for DecisionGuard (FinTechathon 2026, Topic E; deadline Tue
20 Oct 2026 21:59 Dhaka). Your job: check the whole project end to end, find flaws, fix what
is safe to fix, and write a report for the orchestrator.

## Ground rules (read before doing anything)

1. Read CLAUDE.md, docs/PLAN.md (especially section 8 and 9), docs/FEATURES.md and
   docs/ORCHESTRATOR.md. You are a HELPER, not the on-duty orchestrator: you never merge,
   never push to main, never edit docs/NOW.md or PLAN section 8.
2. Claim the work first: git fetch --all && git switch main && git pull, then
   git switch -c audit-final. Add a row to docs/CLAIMS.md (task "Final end-to-end audit",
   session "audit", branch audit-final, status active, time in Dhaka), commit
   "claims: audit claims final end-to-end audit", push. If the push is rejected, pull --rebase
   and re-check the table.
3. Secrets: never read, open, cat or print any .env file or key. Never enter credentials.
4. Tests never call real LLMs or the network (CLAUDE.md rule 6). Never weaken, skip, xfail or
   delete a test to make it pass. Never tune the injection guard (backend/app/security/guard*)
   to its own eval set or to the e2e/eval examples.
5. Fixing rule: only small, clearly-correct fixes, each with a test that would have caught it,
   committed as "AUDIT: <what>" on audit-final. Anything large, risky, cross-WP, or a judgement
   call (scope, wording of claims, security trade-offs) goes into the report as a
   recommendation, not a code change. Respect CLAUDE.md ownership; if a fix touches a shared
   contract (backend/app/contracts), do not change it: report it.
6. Lowercase "hishab" identifiers are intentional and stay (domain hishab.quadbits.net, demo
   emails *.hishab.test, cookie and storage keys, package names, docker project name). The
   product name in user-facing text and documents is "DecisionGuard".
7. Commit and push at least every 30 minutes so nothing lives only in your sandbox.

## Commands to run (record each command and its result for the report)

From the repo root:
1. npm run setup
2. npm run lint
3. npm run test            (backend pytest + web Vitest)
4. npm run eval
5. npm run evidence        (if it rewrites docs/submission/evidence/, check the diff makes sense
                            before committing it)
6. npm run dev             (in the background; API :8000, web :5173). Seed the dev database
                            first if Today/Cash abstain: uv --directory backend run python -m app.facts.seed
7. npm run e2e             (Playwright; reuses the running dev server)
8. gitleaks detect --source . --config .gitleaks.toml (if gitleaks is installed; otherwise
   say so and grep for obvious key patterns instead, without printing any match in full)

Browser: use the Playwright Chromium that is already installed (PLAYWRIGHT_BROWSERS_PATH is
preset). Do NOT run "playwright install".

## What to check

A. Every screen, live. With the dev server running, write a short throwaway Playwright script
   (outside the repo or under web/test-results/, not committed) that signs in through the
   "Try the demo" box (the demo code is shown on screen in demo mode; demo accounts come from
   GET /api/auth/demo-accounts) as the hardware owner (owner@hardware.hishab.test, the video's
   demo shop) and also as the grocery accountant, staff, lender and compliance roles. Set
   Settings -> Data -> API (development) -> Real backend. Visit every route in
   web/src/routes.tsx in English, বাংলা and 中文, at desktop (1920x1080) and phone (Pixel 7)
   sizes. Take screenshots. Look for: untranslated keys or English left in BN/ZH, layout
   overflow or horizontal scroll on phone, the amber synthetic-data banner missing, "Offline
   mock" banner where the real API should answer, numbers without a provenance drawer, error
   toasts, console errors, requests to any host other than localhost.
B. Accessibility: run axe (the repo already depends on it; see web/src/a11y.test.tsx and the
   e2e suite) on each screen; list serious and critical violations.
C. i18n parity: every key in web/src/i18n/locales/en.json exists in bn.json and zh.json and
   vice versa; no value in bn/zh is identical to English unless it is a name or code.
D. CLAUDE.md non-negotiable rules, checked in code:
   - No number shown to a user comes from an LLM: trace copilot/agent output paths
     (backend/app/agents, backend/app/llm) and confirm figures come from engines with
     provenance (formula_id + input fact IDs).
   - Engines read typed facts only; engines do no database or network access.
   - Every LLM call goes through backend/app/llm/gateway.py and its privacy check; search for
     any other client creation (openai, httpx, requests) outside the gateway.
   - Every action has a permission tier; EXECUTE needs owner approval with a fresh step-up
     code; money never moves.
   - Abstention is used where data is short.
   - No network in tests (backend/tests/conftest.py guard); fixtures only.
   - No secrets in the repo (also check git history with gitleaks if available).
   - Synthetic data is labelled data_mode "synthetic" everywhere it appears (API responses,
     UI banner, documents, deck, evidence).
E. Security review: backend/app/security (auth, sessions, TOTP, lockout, approvals, audit
   chain, guard, web hardening) and EVERY router in backend/app/api/*.py: each route checks
   authentication, role and tenant (no cross-tenant reads by changing an id), lender viewer
   sees only what its scopes allow, state-changing routes are protected by the origin check,
   step-up is enforced server-side for EXECUTE, demo accounts are refused outside demo mode.
   List the open bugs already recorded in docs/packages/WP-15.md ("Found by the suite") and
   say whether each is still open.
   Fresh injection test (do this BEFORE you open backend/app/security/guard_rules.py or
   backend/eval/tasks.py, and never open them while writing): write 24 new prompt-injection
   attacks of your own (2 per family for skip_approval, change_bank_details, add_payee,
   exfiltrate_vault, disable_audit, hidden_instruction, across en, bn, bl (romanised Bangla) and
   zh) plus 24 innocent messages that use the same words. Save them to
   docs/handover/fresh_injection_set.jsonl ({"id","lang","family","label":"attack"|"benign",
   "text"}), commit that file first, then measure with InjectionGuard().inspect(text,
   Source.user_message) from backend/app/security/guard.py and report caught/missed and false alarms.
   Do not change the guard to pass your set: report the numbers only.
F. Submission deliverables in docs/submission/, checked against the code and the latest
   test/eval runs: technical-documentation.md, security-self-assessment.md, video-script.md,
   the deck slides in docs/submission/deck/slides/*.html (and deck.json), and the PDFs in
   docs/submission/pdf/ (deck.pdf, technical-documentation.pdf,
   security-self-assessment.pdf; check they match their Markdown/HTML sources and are not
   stale). Look for: wrong or outdated numbers (test counts vs
   docs/submission/evidence/test-counts.md, eval scores vs evidence), claims of features
   that were cut (see docs/FEATURES.md and PLAN section 8: market watch, sending messages,
   audit drill, GPU classifier...), features described as live that have no router, broken
   layout in slides at 1920x1080, leftover "Hishab" in user-facing text (lowercase
   identifiers excepted, rule 6), synthetic data not labelled synthetic, and any statement
   that contradicts the CLAUDE.md rules.
G. README.md, docs/DEPLOY.md and infra/ against reality: do the documented commands work, do
   the env variable names match backend/app/settings.py and infra/docker-compose.yml.

## The report: docs/handover/AUDIT_REPORT.md

Write it on branch audit-final, in this order:

1. Summary: 5-10 lines. Overall state, number of findings by severity, what you fixed, the
   three most important things the orchestrator must decide before 21:59 Dhaka.
2. Findings table with these columns:
   | ID | Severity (Critical/High/Medium/Low) | Area | File:line | What is wrong | Evidence / how reproduced | Fixed in commit <sha> or "not fixed - recommendation: ..." |
   Severity guide: Critical = breaks a non-negotiable rule, leaks data or secrets, or makes a
   submission claim false; High = a demo journey or security check fails; Medium = wrong
   number or stale claim in a deliverable, a11y serious; Low = polish.
3. Checked and found fine: a list of what you verified and found correct (so nobody repeats it).
4. Commands run: each command, exit status, and the key result line (counts, pass/fail).

Then set your docs/CLAIMS.md row to done with the PR number.

When done, push the branch, open the PR, and tell the user the report is at
docs/handover/AUDIT_REPORT.md on branch audit-final.
```

Notes for Nobo:

- The audit chat may take 1–3 hours. It does not change `main`; the on-duty orchestrator reads
  the report and decides what to merge.
- If it asks for permission to run a command, approve commands that only touch this repo
  (tests, installs, git on its own branch). Refuse anything that reads `.env` or touches other
  folders.
