# Session A: make the DecisionGuard copilot answer properly

Paste this whole file into a new Claude Code session on the repo `NoboIshraque/SME-financing-copilot`.

## Who you are and the rules

You are a helper session for team DecisionGuard (FinTechathon 2026, Topic E). Deadline: **Tue 20 Oct
2026 21:59 Dhaka**; stop starting new work at **19:30 Dhaka**. Another helper (Session B) works in
parallel on sign-in, the cash slider and the market screen. You must not edit its files.

1. Read `CLAUDE.md` first. Its rules are absolute: no number from a model, typed facts only,
   every model call through `backend/app/llm/gateway.py`, tests never call a real model or the
   network, never read or print `.env`, synthetic data stays labelled synthetic.
2. Add a row to `docs/CLAIMS.md` ("Session A: copilot answers, role suggestions, AI-model doc"),
   commit, push. Work on branch `copilot-answers`. Small commits `WP-10: ...`.
3. **You own only:** `backend/app/llm/`, `backend/app/agents/`, `backend/tests/agents/`,
   `backend/eval/` (add tasks; never weaken one), `web/src/copilot/`, and the locale keys under
   `"copilot"` and `"abstain"` in `web/src/i18n/locales/{en,bn,zh}.json` (all three, same keys).
   New doc: `docs/handover/AI_MODELS.md`. Touch nothing else.
4. Never tune the injection guard (`backend/app/security/guard_rules.py`), never skip or weaken a
   test.
5. Before each PR: `npm run lint`, `cd backend && uv run pytest -q`, `npm run test:web`,
   `uv --directory backend run python -m eval.run` (must stay 62/62 or better; the run rewrites
   `docs/submission/evidence/eval/`, so restore that folder with `git checkout -- docs/submission/evidence`
   before committing). Open a PR to `main`; merge it yourself only when every CI check is green,
   after merging `main` into your branch (never force-push `main`). If the locale files conflict,
   keep both sides' keys.
6. Save tokens: use `grep -n` and read only the lines you need; run single test files while
   iterating; do not read the generated `web/src/api/contracts.ts` or `docs/api/contracts.json`.

## Background you need

- The hosted demo runs on Render with `LLM_MODE=fixtures` and no model keys (`render.yaml`). In
  that mode **no model is ever called**: the gateway replays recorded fixtures for tests and
  otherwise ends at the **deterministic planner** (`backend/app/llm/deterministic.py`), which
  maps a question to intents by **keywords** (`KEYWORDS`, `INTENT_TOOLS`). A question with no
  keyword gives intent `unknown`, and the orchestrator abstains with
  `abstain.out_of_scope` ("I can't answer that one yet…"). That is why the owner sees "I won't
  guess on this" so often.
- PR #46 (20 Oct) added salary/rent/bills/"who do I pay next" to `cash_outlook`. Look at
  `backend/tests/agents/test_deterministic.py` for the table style.
- With `LLM_MODE=live` and `GEMINI_API_KEY` / `GROQ_API_KEY` set, the roles in
  `backend/app/llm/providers.py` apply: **Gemini Flash plans** the question (brain), **Groq
  models vote and critique** (gpt-oss, Qwen, Gemma), and every chain still ends at the
  deterministic planner. Numbers always come from the engines and are re-checked by
  `backend/app/agents/checker.py`; anonymisation happens before any call.
- Intents and their tools: `cash_outlook`, `collect_receivables`, `find_financing`,
  `business_health`, `what_if`, `settle_debts`, `draft_message` (market intents were cut: the
  market router does not exist, so those must say so politely, not "won't guess").

## Tasks, in this order

### A1. Measure the problem first (30 min)
Write `backend/tests/agents/test_everyday_questions.py`: about 60 realistic questions an owner,
accountant or staff member of a small Bangladeshi shop would type, in English, Bangla, Banglish
and Chinese (cash, paying salaries/rent/suppliers, who owes me, loans, profit, "is my business
doing ok", what-ifs, debts with other shops, drafting a reminder, today's summary, greetings
like "hi"/"help"/"what can you do"). For each, the expected intent(s). Run it, list which ones
fall to `unknown`. Put the miss count in your PR.

### A2. Fix the misses without breaking precision
- Widen `KEYWORDS` per intent in all four writing styles. Bangla keywords match at word start,
  so avoid short stems that start unrelated words (the file explains this); Chinese matches
  anywhere, so guard compound words like `_CJK_NOT_AFTER` does.
- Add a `help` path: "hi", "help", "what can you do", "কী করতে পারো", "你能做什么" get a short
  list of what the copilot can do (text through i18n keys, no numbers), not an abstention.
- Add one tool where an engine already has the data and owners clearly ask for it: **upcoming
  payments** ("who do I pay next", "what bills are due"): read the tenant's bills/obligations
  from the fact store (`FactStore.bills`, `obligations`) for the next 30 days, sorted by due
  date, as engine-computed figures with provenance (see how `backend/app/agents/tools.py`
  builds tool results). Route "pay next / bills due / payable" to it.
- Make the abstention specific: when intent is unknown, suggest 2–3 questions that work for the
  user's role (reuse A3's lists).
- Every fixed question must also work through `/api/copilot/ask` (add 3–4 API-level cases).
- Eval: add the new questions as functional tasks in `backend/eval/tasks.py`; total must stay
  all-pass.

### A3. Suggested questions by role
`web/src/copilot/CopilotPanel.tsx` shows three fixed suggestions (`SUGGESTIONS`). Make them
depend on the signed-in role (`useRequiredSession().principal.role`):
- owner: cash this month, pay salaries on the 31st, best loan, approve pending actions
- accountant: profit and ratios this quarter, overdue receivables, upcoming bills, upload statement
- staff: today's cash position, who owes us, draft a reminder
- compliance: audit/abstentions overview (whatever the copilot can answer for that role)
- lender_viewer: hide the copilot or show only what their scopes allow (check `RequireAuth`
  / `navigation.ts` for what a lender may see)
Keys `copilot.suggest.<role>.<n>` in en/bn/zh. Add a backend test that loads the English
suggestion texts from `web/src/i18n/locales/en.json` and asserts each one plans to a known
intent (so a suggestion can never answer "won't guess"). Add a web unit test per role.

### A4. `docs/handover/AI_MODELS.md` (for Nobo, plain English)
Where Gemini and Groq come in (brain/voter/critic, what each sees: anonymised text only), what
happens with no keys (deterministic planner), what changes with `LLM_MODE=live`, free-tier
limits and fallbacks, and the exact Render steps to switch on live models (Environment tab:
`LLM_MODE=live`, fill both keys, save; check `/api/health` shows `gemini_key_set: true`).
Recommend live mode for judging only if A1's questions also pass in deterministic mode (the
fallback when a provider is rate-limited).

## Done means
PR merged with: A1 miss count before → after, eval result, test counts, and a 5-line note for
Nobo of what to try on the hosted site. Then remove your row's "active" in `docs/CLAIMS.md`.
