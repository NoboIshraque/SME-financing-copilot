# Hishab — SME Finance Copilot (FinTechathon 2026, Topic E)

Mobile-first web app + API + agents that help a small Bangladeshi business with financing-option
matching, cash-flow management with alerts, and business financial analysis.
Deadline: **Tue 20 Oct 2026 21:59 Dhaka**. Plan: `docs/PLAN.md`. Features: `docs/FEATURES.md`.
Why: `docs/CONTEXT.md`. Your task: the WP file you were pointed at in `docs/packages/`.

## Non-negotiable rules

1. **Code computes, the model narrates.** No number shown to a user may come from an LLM. Every
   figure comes from a deterministic engine using `Decimal`, and carries provenance
   (`formula_id` + input fact IDs).
2. **Typed facts only.** Engines read the Typed Fact Ledger (`backend/app/facts`), never free text.
3. **Only anonymised data leaves the server.** Every LLM call goes through
   `backend/app/llm/gateway.py`, which refuses payloads that fail the privacy check.
4. **Every action has a permission tier** (READ, SUGGEST, DRAFT, EXECUTE, DENY). EXECUTE needs
   owner approval with a step-up code. Money never moves without a human.
5. **Prefer abstaining to guessing.** Use `agents/abstention.py` when data or agreement is short.
6. **Tests never call real LLMs or the network.** Use the recorded fixtures in `backend/tests/fixtures`.
7. **No secrets in the repo.** Keys live in `backend/.env` (git-ignored). Never read or print `.env`.
8. **Synthetic data is labelled synthetic** (`data_mode: "synthetic"`) everywhere it appears.
9. **English** for code, comments, docs and commit messages. UI strings go through i18n (en, bn, zh).
10. **No filler tests.** Each test asserts real behaviour. Parametrised rows must be distinct cases.

## Repo layout and ownership

Only edit paths your WP owns. Shared contracts belong to WP-00 (orchestrator): to change one,
write the request under "Questions" in your WP file and stop.

```
backend/app/contracts/     WP-00   Pydantic schemas shared by everyone (facts, API, agents)
backend/app/facts/         WP-01   Typed Fact Ledger, provenance graph
backend/app/ingest/        WP-02   bKash/Nagad/bank CSV, Excel, OCR, Bangla/Banglish
backend/app/privacy/       WP-03   detectors, token vault, anonymiser
backend/app/engines/cash/  WP-04   forecast, Monte Carlo, gaps, alerts, smoothing
backend/app/engines/receivables/ WP-05
backend/app/engines/financing/   WP-06   catalogue, APR, eligibility, ranking, lender check
backend/app/engines/analysis/    WP-07   P&L, ratios, variance, scenarios, stability
backend/app/engines/mesh/        WP-08   netting, consent, attestations
backend/app/chain/               WP-08   Sepolia anchoring
backend/app/engines/market/      WP-09   prices, vendors, negotiation
backend/app/llm/  backend/app/agents/  WP-10
backend/app/security/            WP-11   auth, roles, tiers, approvals, audit, injection guard
backend/app/messaging/           WP-12
backend/app/reports/             WP-13   lender report, Trust Passport, verify page
backend/app/api/                 each WP adds its own router file: api/<wp_name>.py
backend/tests/<area>/            tests live next to their WP's area name
backend/eval/                    WP-16
web/                             WP-14 (screens), WP-15 (web/e2e)
ml/                              WP-17 notebooks and artefacts
data/synthetic/  data/public/  data/real_anonymised/   WP-00 / WP-17 / WP-20
infra/  .github/workflows/       WP-18
docs/submission/                 WP-19
```

## Commands

```
npm run setup          # install backend (uv) and web (npm) dependencies
npm run test           # everything: backend + web unit tests
npm run test:backend   # cd backend && uv run pytest -q
npm run test:web       # cd web && npm test -- --run
npm run e2e            # Playwright (needs `npm run dev` running)
npm run lint           # ruff + eslint + tsc
npm run dev            # API on :8000, web on :5173, seeded synthetic data
npm run eval           # offline evaluation harness
npm run evidence       # writes docs/submission/evidence/
```

Root `package.json` scripts are the task runner (Windows has no `make`); they work in
PowerShell, CMD and Git Bash.

Run a single backend test: `cd backend && uv run pytest tests/cash/test_forecast.py -q`.

## Conventions

- Python 3.12, FastAPI, SQLAlchemy 2, Pydantic v2, ruff. Money = `Decimal`, 2 dp, currency
  `BDT` unless stated. Dates are `datetime.date`; timezone Asia/Dhaka.
- Engines are pure functions over contracts; no database or network inside an engine.
- React + TypeScript + Vite + Tailwind. All user-visible strings via `web/src/i18n`. No Google
  Fonts or third-party CDNs (China reachability): self-host all assets.
- Commit messages: `WP-XX: what changed`. Small commits; autosave also commits every 5 minutes.
- Before starting a milestone: `git fetch && git rebase origin/main`.
- After each milestone: tick it in the WP file's STATUS block and update `docs/PLAN.md` §8.
- If blocked or a decision is needed: write it under "Questions" in the WP file, commit, stop.
