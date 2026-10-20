# DecisionGuard — SME Finance Copilot (FinTechathon 2026, Topic E)

Mobile-first web app + API + agents that help a small Bangladeshi business with financing-option
matching, cash-flow management with alerts, and business financial analysis.
Features: `docs/FEATURES.md`. Why: `docs/CONTEXT.md`. Submission documents: `docs/submission/`.

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

Each area was built as a work package (WP); the shared contracts are owned by WP-00.

```
backend/app/contracts/     WP-00   Pydantic schemas shared by everyone (facts, API, agents)
backend/app/synthetic/     WP-00   load_universe(): the synthetic SMEs as typed contracts
backend/app/main.py, db.py, settings.py, api/health.py, tests/conftest.py   WP-00
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
npm run dev            # API on :8000, web on :5173 (seed first: uv --directory backend run python -m app.facts.seed)
npm run eval           # offline evaluation harness
npm run evidence       # writes docs/submission/evidence/
npm run contracts      # after a contract change (orchestrator only): schema JSON + web types
npm run synthetic      # regenerate data/synthetic/universe (deterministic, seed 20261020)
```

Root `package.json` scripts are the task runner (Windows has no `make`); they work in
PowerShell, CMD and Git Bash.

Run a single backend test: `cd backend && uv run pytest tests/cash/test_forecast.py -q`.

## How the scaffold works (read once)

- **Contracts:** `from app.contracts import Money, Transaction, ForecastBand, ...` (58 models,
  frozen, unknown fields rejected). Money is `Money.of("1250.50")`; floats are refused.
  `app/contracts/examples.py` has one valid example of every contract: reuse it in tests.
  The web gets the same types in `web/src/api/contracts.ts` (generated, never edit).
- **Synthetic data:** in tests use the `universe` fixture (`universe.smes["sme_grocery"]` has
  `.transactions .invoices .bills .obligations .parties .balance_on(day)`;
  `universe.mesh_obligations` is the open debt ring fabric -> garment -> hardware). As-of date
  2026-09-30. Raw export-format files (bKash, Nagad, bank, cash book, baki register) are in
  `data/synthetic/universe/<sme>/`; `transactions_truth.csv` is the typed ground truth.
- **Your API:** create `backend/app/api/<wp_name>.py` with a module-level `router = APIRouter(...)`.
  It is mounted under `/api` automatically. Do not edit `main.py`.
- **Your tables:** create `backend/app/<area>/models.py` subclassing `app.db.Base`. Tables are
  created automatically. Get a session in routes with `Depends(get_session)` from `app.main`.
- **App-wide hooks:** middleware, exception handlers or startup checks go in
  `backend/app/<area>/app_hooks.py` with `install(app, settings)`; `create_app` calls it after
  mounting every router and before CORS (CORS stays outermost). `api_routes(app)` from
  `app.main` lists every route (full path, methods, endpoint). Do not edit `main.py`.
- **Tests:** `client` fixture = app on in-memory SQLite. Any non-localhost network call fails
  the test on purpose. Hypothesis runs derandomised in CI (`HYPOTHESIS_PROFILE=ci`).
- **Festival calendar:** `data/public/calendar/bd_festivals.yaml` (Eid dates are +/- 1 day).
- **Dependencies** for every WP are already in `backend/pyproject.toml` and `web/package.json`
  (numpy, networkx, sympy, cryptography, argon2, pyotp, openpyxl, pytesseract, reportlab,
  openai, web3, apscheduler; react-router, react-query, recharts, i18next, Playwright, axe).
  Avoid adding more. If you must, expect a lockfile conflict: keep either side, re-run
  `uv lock` (backend) or `npm install` (web), and commit.
- **Web:** screens go in `web/src/routes.tsx` (replace the Placeholder for your screen). Strings
  go in all three of `web/src/i18n/locales/{en,bn,zh}.json` (a test checks they match). Format
  money with `formatTaka()` from `web/src/api/format.ts` (exact, lakh/crore grouping, Bangla
  digits). Call the API only with `apiGet`/`apiPost` from `web/src/api/client.ts`.

## Conventions

- Python 3.12, FastAPI, SQLAlchemy 2, Pydantic v2, ruff. Money = `Decimal`, 2 dp, currency
  `BDT` unless stated. Dates are `datetime.date`; timezone Asia/Dhaka.
- Engines are pure functions over contracts; no database or network inside an engine.
- React + TypeScript + Vite + Tailwind. All user-visible strings via `web/src/i18n`. No Google
  Fonts or third-party CDNs (China reachability): self-host all assets.
- Commit messages: `WP-XX: what changed`. Small commits.
