# Session B: fix sign-in, the cash slider and the market screen

Paste this whole file into a new Claude Code session on the repo `NoboIshraque/SME-financing-copilot`.

## Who you are and the rules

You are a helper session for team DecisionGuard (FinTechathon 2026, Topic E). Deadline: **Tue 20 Oct
2026 21:59 Dhaka**; stop starting new work at **19:30 Dhaka**. Another helper (Session A) works in
parallel on the copilot. You must not edit its files.

1. Read `CLAUDE.md` first. Its rules are absolute (no secrets, never read `.env`, tests offline,
   synthetic data labelled synthetic, EXECUTE needs the owner's step-up code).
2. Add a row to `docs/CLAIMS.md` ("Session B: sign-in, cash slider, market label, hosting doc"),
   commit, push. Branch `app-fixes`. Small commits `WP-14: ...` (web) / `WP-04: ...` (cash API).
3. **You own only:** `web/src/auth/`, `web/src/screens/cash/`, `web/src/screens/market/`,
   `web/src/components/`, `backend/app/api/cash.py`, `backend/app/security/demo.py` (only if the
   sign-in bug is there), `backend/tests/cash/`, `backend/tests/security/` (new tests only),
   `web/e2e/` (only the journeys you change), `render.yaml`, `docs/handover/FREE_SERVER.md`,
   `docs/NOW.md`, `docs/PLAN.md` §8, and locale keys **outside** `"copilot"` and `"abstain"`.
   Do not touch `backend/app/llm/`, `backend/app/agents/`, `web/src/copilot/`.
4. Before each PR: `npm run lint`, `npm run test`, and `npm run e2e` when web screens changed (needs
   `npm run dev` running; Playwright's Chromium is preinstalled, do not run `playwright install`).
   Open a PR to `main`; merge it yourself only when every CI check (including "Playwright (local
   target)") is green, after merging `main` into your branch. If locale files conflict, keep both
   sides' keys.
5. Save tokens: `grep -n` first, read only what you need, run single test files while iterating.

Ask Nobo once for the hosted web address (`https://…-web.onrender.com`) so you can reproduce on
the real server too (open it with Playwright; the free server sleeps after 15 minutes and the
first request can take about a minute).

## Tasks, in this order

### B1. "The very first owner sign-in doesn't work" (highest priority)
Reproduce first, locally (`npm run dev`, then sign-in page → "Try the demo" → first row, which is
the grocery owner) and on the hosted site. Likely causes to check, in this order:
- **Stale demo code:** `web/src/auth/LoginScreen.tsx` loads `/api/auth/demo-accounts` once
  (`retry: false`) and shows `totp_hint` from that moment. A TOTP code lives 30 seconds, so if the
  page was open for a while the shown code is already wrong. Fix: fetch a fresh hint when the
  owner reaches the code step (refetch the query in `signInWithDemo` / on entering the `totp`
  step), and refresh it every ~20 s while that step is open.
- **Cold start:** the first request after the free server slept may time out or fail; check
  `web/src/api/client.ts` for a timeout and give sign-in a clear "server is waking up, try again"
  message instead of a generic error.
- **Demo seeding race:** `_ensure_demo` in `backend/app/api/auth.py` seeds demo accounts on the
  first login call (`backend/app/security/demo.py`). Check that the very first login after a
  fresh start succeeds (write a test: fresh app, first call is the owner's login).
- Lockout after wrong codes (5 tries, 15 minutes) makes later tries fail too; make the message say so.
Write a test for the cause you find (backend or web, plus an e2e step if it is a UI timing bug).

### B2. Cash what-if slider lags
`web/src/screens/cash/CashScreen.tsx` (`WhatIfPanel`) calls `POST /api/cash/whatif` as the slider
moves. Each call runs a 1,000-path simulation, and the free server has a slow CPU; the API also
rate-limits simulations (bucket `simulate`, 120/min, `backend/app/security/web.py`).
- Debounce: send only after the slider is still for ~400 ms or on release (`onPointerUp` /
  `onKeyUp`), keep showing the previous result while a new one loads (react-query
  `placeholderData: keepPreviousData`), and cancel or ignore stale responses.
- Show a small "updating…" state; keep the slider itself instant.
- Optional backend: cache what-if results per (tenant, ledger revision, shock values) in
  `backend/app/api/cash.py` the way `analyse` caches analyses.
- Tests: a web unit test that rapid slider changes produce one request; keep `tests/cash` green.

### B3. Market screen: say clearly where its data comes from
Market watch, vendors and negotiation were **cut** (WP-09, 19 Oct). The screen shows a labelled
preview from sample data bundled in the web app (`web/src/mocks/fixtures/market`, loaded by
`orSample` in `web/src/api/endpoints.ts` when `/api/market/*` does not exist). No API, Gemini or
Groq fills it, and nothing comes from the web or the user's location. Make that unmistakable on
the screen in en/bn/zh ("Sample data: a preview of a planned feature, not live prices"), on every
card, and make sure a self-service shop (data mode `live`) never sees sample vendors presented as
its own. Add a web test.

### B4. Hosting doc and status
- Update `docs/handover/FREE_SERVER.md` with whatever B1/B2 changed for the hosted site, and a
  "test it" checklist (sign in as each demo role, create your own shop, move the slider).
- At the end: update `docs/NOW.md` (what Nobo must do next) and PLAN §8 rows you changed.

## Done means
PR merged with: the root cause of B1 and the test that proves it, the slider's request count
before → after, test counts, and a 5-line note for Nobo of what to check after redeploying both
Render services (Manual Deploy → Deploy latest commit on `decisionguard-api` and
`decisionguard-web`).
