# Master plan — Hishab (SME Finance Copilot)

Owner: Nobo (lead) · Team: Nobo, Amdad, Labib · Orchestrator: Claude (cloud chat session)

**Hard deadline: Tue 20 Oct 2026, 23:59 Beijing = 21:59 Dhaka.** Registration and submission
share it. Submissions can be replaced until then; the latest one counts.

Read with: `docs/FEATURES.md` (what), `docs/RUNBOOK.md` (who does what, step by step),
`docs/CONTEXT.md` (everything we learned), `docs/packages/WP-*.md` (build specs).

---

## 1. Decisions (final unless Nobo overrides)

| # | Decision | Why |
| --- | --- | --- |
| D1 | **We build a mobile-first web app (PWA) + API + agents.** Not a model | Judges need a live link, repo, video. An LLM is a component, not the product |
| D2 | **We do not train an LLM.** We call hosted models through one gateway and train *small* models on Kaggle/Colab (injection classifier, payment-delay model, forecaster backtests) | Training an LLM needs thousands of GPU-hours; small task models train in < 1 h on a free T4 |
| D3 | **Code computes, the model narrates.** Every number comes from a deterministic engine | Research (CONTEXT §4); judges will probe numbers |
| D4 | **Stack:** Python 3.12 + FastAPI + SQLAlchemy 2 + PostgreSQL (SQLite in tests) · React + TypeScript + Vite + Tailwind · pytest + Hypothesis + Vitest + Playwright · Docker Compose + Caddy | One backend language shared with Kaggle notebooks; fastest path for Claude Code; easy test volume |
| D5 | **LLM providers ($0 path):** brain = **Gemini Flash** (free tier, Google AI Studio key); voters = **Groq gpt-oss-120b** and **Groq Qwen** (free tier); local private mode = **Ollama + small Qwen** on PC-4; always-on **deterministic fallback planner** | Free; three model families for agreement (N9); works from Bangladesh and Singapore; demo never breaks |
| D6 | **Host in Singapore** (not Hong Kong): primary Tencent Cloud Lighthouse SG; fallback Oracle Cloud Always Free SG; Vercel mirror for the frontend only | Gemini API is not served in Hong Kong or mainland China, but is in Singapore and Bangladesh; Tencent's network has good China routes; vercel.app is mostly blocked in China |
| D4b | **Docker: yes, in two places only.** (1) The Singapore server runs everything in Docker Compose: API, background worker, PostgreSQL, Caddy (HTTPS + serves the web app). (2) Labib's PC-4 runs the same Compose stack as a dress rehearsal and for the hourly integration run. **Coding PCs (PC-1, PC-2, PC-3) don't need Docker:** `npm run dev` uses SQLite and runs natively | Same stack on server and rehearsal box = no "works on my machine" surprises; coding PCs stay light and fast |
| D6b | **Domain:** subdomain `hishab.quadbits.net` (Nobo's existing domain), DNS only | No purchase; renewed through 30 Nov (finals 21–23 Nov); setup in RUNBOOK §5.9 |
| D7 | **Testnet:** Ethereum **Sepolia**, hashes only | Free faucets with no mainnet balance needed; real tx hashes for the on-chain bonus |
| D8 | **One private GitHub repo** is the single source of truth; each work package on its own branch; autosave pushes every 5 min | Coordination without remote desktops; backup |
| D9 | **Contract-first:** the orchestrator writes shared schemas and API contracts (WP-00) before parallel work starts | Lets four sessions build in parallel without collisions |
| D10 | **Test target: ≥ 1,000 automated tests + ≥ 100 eval tasks + mutation score ≥ 80% on core engines** | Beat DuitDuit's 850 tests / 57 eval tasks on count *and* on what they admit they never measured |
| D11 | **Insurance submission Mon 19 Oct 21:00 Dhaka**, final Tue 20 Oct 19:00 (3 h buffer) | Latest submission counts |
| D12 | All docs, deck and video in **English**. App UI in English, Bangla and Chinese | Official language rule; judges in China |

## 2. Architecture

```
Browser (PWA: EN/BN/ZH)  ── email alerts
        │ HTTPS
   Caddy (TLS, CSP, rate limit)  ── static web build
        │
   FastAPI ── auth/RBAC/permission tiers/approvals ── audit chain ──► Sepolia anchor
        │
   Orchestrator agent ─┬─ sub-agents: cash · receivables · financing · analysis · market · messaging
                       ├─ checker (symbolic recompute vs fact ledger)
                       ├─ critic ("case against", different model family)
                       ├─ agreement (multi-model vote) · stability (10 variations) · abstention
                       └─ LLM gateway ─► Gemini | Groq gpt-oss | Groq Qwen | Ollama | deterministic
        │  (tools only — no number ever comes from a model)
   Engines (pure Python, Decimal): forecast · gaps/alerts · receivables · financing · analysis ·
   scenarios · stability · mesh/netting · market · negotiation · reports/passport
        │
   Typed Fact Ledger + provenance graph   ◄── Ingest (bKash/Nagad/bank CSV, Excel, ledger photo OCR)
        │                                       ▲
   PostgreSQL                              Privacy vault (tokens, AES-256-GCM) — only tokens leave
```

Repo layout and ownership are in `CLAUDE.md`.

## 3. Work packages

| WP | Name | Owner session | Wave | Test quota |
| --- | --- | --- | --- | --- |
| WP-00 | Foundation: scaffold, contracts, CI, seed data, autosave | Orchestrator | 0 | 40 |
| WP-01 | Typed Fact Ledger + provenance (N5, N13 backend) | A1 | 1 | 60 |
| WP-02 | Ingestion: bKash/Nagad/bank CSV, Excel, OCR, Bangla/Banglish (P4) | A1 | 1 | 80 |
| WP-03 | Privacy vault, detectors, anonymiser, amount scaling (N6, N18, P11) | Orchestrator | 1 | 70 |
| WP-04 | Cash engine: forecast, Monte Carlo, gaps, alerts, smoothing (Q1, Q3) | A1 | 1–2 | 120 |
| WP-05 | Receivables & collections: aging, risk, limits, ladder, disputes (Q2) | A1 | 2 | 60 |
| WP-06 | Financing: catalogue, effective APR, eligibility, ranking, lender check (P1, N20, P14) | Orchestrator | 2 | 90 |
| WP-07 | Analysis: P&L, ratios, variance, scenarios, stability score (N1, N12, N16) | A1 | 2 | 90 |
| WP-08 | Liquidity mesh: netting, consent, attestations, Sepolia anchor (N14, Q4) | Orchestrator | 2 | 70 |
| WP-09 | Market watch, vendor ranking, negotiation (N3, N19) | Worker C* | 2 | 50 |
| WP-10 | LLM gateway + agents: orchestrator, checker, critic, agreement, abstention (N7–N11, N17, P13) | B2 | 2 | 90 |
| WP-11 | Security: auth, roles, tiers, approvals, audit chain, injection guard (P2, P5) | B2 | 1–2 | 110 |
| WP-12 | Messaging & automation: templates, approval queue, email + in-app (N2; P10 cut) | Worker C* | 2 | 40 |
| WP-13 | Reports + Trust Passport + verify page (N4, Q4) | Orchestrator | 3 | 30 |
| WP-14 | Frontend: all screens, provenance drawer, i18n, PWA, a11y (P6, P9, P12) | B1 | 1–3 | 110 (Vitest) |
| WP-15 | E2E Playwright on local + hosted | B1 | 3 | 45 |
| WP-16 | Eval harness: ≥ 100 tasks, adversarial multilingual, nightly audit drill (P3, P8) | B2 | 3 | 100 tasks |
| WP-17 | ML on Kaggle/Colab: forecaster backtest, delay model, injection classifier (N15, P5) | Human PC-4 + notebooks from orchestrator | 1–2 | 20 |
| WP-18 | Infra & deploy: Docker, Caddy, SG server, CI/CD, China tests (P6) | Orchestrator + Amdad | 2–3 | 15 |
| WP-19 | Submission: 6 deliverables, built by parallel agents | Orchestrator + all | 3 | — |
| WP-20 | Real-shop data collection and anonymisation (P7) | Labib (human) | 1–2 | — |

\* **Worker C** = Google's free coding CLI on Amdad's PC-3 (optional third coder; see §5). If it isn't
available or its output is weak, WP-09 and WP-12 move to A1 after WP-05.

Totals: ≈ 1,190 automated tests planned (≥ 1,000 target) + ≥ 100 eval tasks.
Items tied to PENDING proposals are built only after approval; their test quotas move elsewhere if cut.

## 4. Timeline (Dhaka time)

| When | Phase | Exit criteria |
| --- | --- | --- |
| Sat 17 Oct 19:00–22:00 | **Wave 0** — setup (all), WP-00 (orchestrator) | Repo scaffold on `main`, CI green, every machine can run `npm run test` |
| Sat 22:00 – Sun 10:00 | **Wave 1** — WP-01, 02, 03, 11 (core), 14 (shell), 17 (data + notebooks), 20 (plan visits) | Facts, ingest, privacy, auth merged; web shell renders seeded data |
| Sun 10:00 – Sun 24:00 | **Wave 2** — WP-04, 05, 06, 07, 08, 09, 10, 12 | All engines + agents merged; ≥ 600 tests |
| Mon 00:00 – Mon 14:00 | **Wave 3a** — WP-13, 14 (all screens), 16, 18 (deploy) | Hosted on SG server; eval harness runs in CI |
| Mon 14:00 – Mon 21:00 | **Wave 3b** — hosted E2E (WP-15), China tests, docs drafts (WP-19) | **21:00 insurance submission sent** |
| Mon 21:00 – Tue 14:00 | **Hardening** — test push to ≥ 1,000, mutation tests, bug bash, deck, video recording | Evidence report generated |
| Tue 14:00 | **Code freeze** | Only doc/video fixes after this |
| Tue 14:00 – 18:30 | Final evidence run, video edit, deck polish, repo made public after secret scan | All 6 deliverables final |
| **Tue 19:00** | **Final submission email** | 3 h buffer to 21:59 |

Sleep: each person gets ~5 h in staggered blocks (RUNBOOK §6). Claude sessions keep running
overnight only inside pre-approved permissions.

## 5. Machines, accounts and how they connect

| Machine | Person | Runs | Account |
| --- | --- | --- | --- |
| **PC-1** = `knight-27` (linked to the orchestrator chat) | Nobo | Claude Code session **A1** in `C:\hishab\repo` (WP-01, 02, 04, 05, 07) | **A** |
| **PC-2** (Nobo's second PC) | Nobo | Two Claude Code sessions in two folders: **B1** in `C:\hishab\repo` (WP-14, 15) and **B2** in `C:\hishab\repo-b2` (WP-03, 11, 10, 16) | **B** |
| **PC-3** (Amdad's PC) | Amdad | Optional **Worker C** — Google's free coding CLI on Amdad's own Google account (WP-09, 12, extra tests) · API keys · hosting server · manual QA of every merged screen | Amdad's Google account |
| **PC-4** (Labib's desktop, always on) | Labib | Docker integration stack · scheduled full test + eval runs · Ollama private mode · Kaggle/Colab notebooks (WP-17) · testnet wallet · field data (WP-20) | none |
| Orchestrator (this cloud chat) | — | WP-00, 06, 08, 13, 18, 19 · reviews and merges every PR · sub-agents for submission docs · can operate PC-1 directly | **A** |

**Both Claude accounts stay on Nobo's own two PCs.** A Claude account is for its owner's use,
so we don't log Nobo's accounts into Amdad's or Labib's machines. Amdad and Labib contribute
through their own free tools, manual tasks, QA and the desktop's always-on jobs.

**Connection model: GitHub, not remote desktop.** Every machine clones the repo and works on
its own branch; work flows through pull requests that the orchestrator reviews and merges.
Humans coordinate in one WhatsApp/Discord group. No remote-desktop software is needed:
Claude sessions run under the pre-approved permissions in `.claude/settings.json`, so they
rarely stop to ask.

**Where the `.md` files live:** in the repo — `CLAUDE.md` (and `AGENTS.md`, a copy for
non-Claude agents) at the root, everything else in `docs/`. Claude Code reads `CLAUDE.md`
automatically. **Building happens in Claude Code (terminal).** The orchestrator stays in this
chat; if it ever has to restart, paste `docs/HANDOVER.md` into a new chat. Per-person
instructions: `docs/team/NOBO.md`, `docs/team/AMDAD.md`, `docs/team/LABIB.md`.

### How the two Pro accounts work together

Facts (Anthropic support): Pro usage is **shared between claude.ai chat and Claude Code**;
Pro gets roughly **10–40 Claude Code prompts per 5-hour window**; Pro uses **Sonnet only**
in Claude Code; there is also a weekly cap.

Rules that follow:
1. **Two accounts = two quota pools.** Account A powers the orchestrator + A1; Account B
   powers B1 + B2. Never log the same account into more sessions than this table says.
2. **Stagger windows:** A1 starts first, B1/B2 about 2.5 h later, so the two pools reset at
   different times and one is usually fresh. B1 and B2 share account B: if B runs dry,
   pause B1 (frontend can wait on mocks) and keep B2 (security/agents) going.
3. **Big prompts, few prompts.** One prompt = one whole WP chunk ("implement §2–§3 of
   WP-04, write the tests, run until green, commit, update STATUS"). No chit-chat, no
   "looks good, continue" — the WP file says what "done" means.
4. **`/clear` between work packages**; keep `CLAUDE.md` short; point Claude at specific
   files instead of letting it read the whole repo.
5. **When an account hits its limit:** its machines switch to non-Claude work in the RUNBOOK
   (manual QA, Kaggle runs, data collection, recording) until reset; urgent WPs move to the
   other account's next free slot (the orchestrator re-queues them in §8).
6. **Check usage** at claude.ai → Settings → Usage before each wave.
7. Optional **Worker C**: Google's free coding CLI (free accounts were moved from Gemini CLI to
   Antigravity CLI in June 2026; Gemini Code Assist for individuals lists 1,000 requests/day —
   confirm on install). It reads `AGENTS.md`. Every one of its PRs gets orchestrator review.

## 6. LLM integration (exact)

- **Gateway** (`backend/app/llm/`): one OpenAI-compatible client, base URL per provider.
  Gemini has an OpenAI-compatible endpoint; Groq and Ollama speak the same API.
- **Roles:**
  - *Brain* (planning, tool choice, explanations, drafts): Gemini Flash.
  - *Voters* for agreement (N9) and *critic* (N11): Groq `gpt-oss-120b` and Groq Qwen
    (Qwen is a preview model; fallback `gpt-oss-20b`, then Gemma via the Gemini API).
  - *Private mode*: Ollama + small Qwen on PC-4, for the "data never leaves the machine" demo.
  - *Fallback*: deterministic planner (rule-based intent → tool), always on; tests run against it.
- **Free-tier limits (indicative, confirm in each console):** Gemini Flash ~10 RPM / ~1,500
  requests/day; Groq free 30 RPM / 1,000 requests/day / 8,000 tokens/min per organisation.
  The gateway tracks usage per provider and degrades gracefully.
- **Cost controls:** response cache keyed by the hash of the anonymised prompt; agreement and
  critic only above a stakes threshold; tool budget per run (P13).
- **Privacy:** free tiers may use inputs to improve the provider's products, so **only
  anonymised payloads** leave the server (N18). Stated in the security self-assessment.
- **Optional upgrade:** $5–10 of paid credit on one provider during the review window
  (20–31 Oct) for higher limits and no training use. Not required.
- **Tests never call real models:** recorded responses (fixtures) replay in CI; a separate
  `npm run live-llm-check` runs real calls and saves traces as evidence (OneGate never did this).
- **Keys:** created by Amdad (RUNBOOK), stored only in each machine's `backend/.env`, in the
  server's `.env`, and in GitHub Actions secrets. Never in the repo, never pasted into chat.

## 7. Testing strategy (D10)

| Layer | Tool | Target |
| --- | --- | --- |
| Unit + parametrised scenario tables | pytest | ≥ 850 backend |
| Property-based invariants (netting conserves money, bands never cross, tokens round-trip) | Hypothesis | included above, ≥ 60 properties |
| Frontend units | Vitest | ≥ 110 |
| End-to-end, local **and hosted** | Playwright | ≥ 45 |
| Eval harness: functional tasks | custom runner | ≥ 50 |
| Eval harness: adversarial (prompt injection in EN/BN/Banglish/ZH, approval bypass, data exfiltration, paraphrases) | custom runner | ≥ 50 |
| Mutation testing on forecast, financing, netting engines | mutmut | kill score ≥ 80% |
| Forecast backtest on real public data | notebook + pytest | reported MAPE + gap lead time |
| Reliability metrics: flip rate, abstention precision, agreement rate | eval runner | reported |
| Security scans: secrets (gitleaks), dependencies (pip-audit, npm audit), DAST (OWASP ZAP baseline) | CI | 0 high findings |

Rules: no filler tests — every test asserts behaviour; parametrised rows must be distinct
cases. CI prints counts per layer; `npm run evidence` writes the report used in deliverable 06.

## 8. Status board (update after every merge)

| WP | Status | Branch | Tests | Notes |
| --- | --- | --- | --- | --- |
| WP-00 | done | merged + PR #15 | 248 backend + 34 web + 4 e2e | contracts v1.1.0 (58 models), synthetic universe, CI, Mission control (issue #8); app-wide hooks (`app/<area>/app_hooks.py`) + `api_routes()` for WP-11 (PR #15); `/api/docs` only in development/test (PR #18) |
| WP-01 | done | merged | 143 | fact store, registry, provenance, API; fixes merged 18 Oct: ledger revisions (no stale figures), caller-scoped + masked explain/facts, race-safe inserts, rows endpoint, record_computed, profile facts + snapshot; facts + ingest APIs take the signed-in principal (PR #17) |
| WP-02 | done | merged | 294 | parsers (bKash/Nagad/bank/ledger/registers, CSV+XLSX), Bangla/Banglish normaliser + Bengali calendar, dedupe, party clustering, OCR drafts (Tesseract ben+eng), preview/commit with keyed digest, API |
| WP-03 | done (5/5) | merged | 105 | detectors (EN/BN, Bangla digits), HMAC token vault + AES-GCM + SQL store, anonymiser (relative dates, P11 amount scaling), fail-closed gate; shop-file anonymiser for WP-20; built by the orchestrator |
| WP-04 | done (8/8), PR #19 open for the on-duty orchestrator | wp-04-cash | 191 | forecast (seasonality incl. festivals, per-customer delays, supplier habits), Monte Carlo (1,000 seeded integer paths, block bootstrap, common random numbers), gaps + 5 leading indicators, Q1 alert tiers with dedupe/cooldown, 6 measured levers as action cards (WP-06/WP-08 interfaces), buffer target + surplus sweep, walk-forward backtest, API (forecast/gaps/alerts/what-if) + daily alert scan |
| WP-05 | not started | — | 0 | |
| WP-06 | done (8/8) | merged (PR #20) | 142 | engine + real BD catalogue; API (PR #20): match, lender check, application draft. Open: application card tier vs WP-11 policy (WP-06.md Questions); fit waits for WP-04 forecast |
| WP-07 | not started | — | 0 | |
| WP-08 | in progress (7/8) | merged | 100 | engine, consent, attestations, anchor, residual-gap routing (cheapest eligible), lender events from peer-verified loans; API (milestone 8) unblocked by WP-11 |
| WP-09 | not started | — | 0 | |
| WP-10 | not started | — | 0 | |
| WP-11 | done (7/7) | merged (PR #16) | 400 | auth (argon2id, TOTP step-up, strict cookies, lockout), roles + consented lender access, tier policy + approvals, hash-chained audit + daily anchor, multilingual injection guard, web hardening, self-assessment draft; installed app-wide through `app/security/app_hooks.py` |
| WP-12 | not started | — | 0 | |
| WP-13 | in progress (3/5) | merged | 26 | passport, sharing, verify, state adapter merged; report waits for WP-07 |
| WP-14 | in progress (0/11) | wp-14-web | — | B1 (PC-2) started 18 Oct ~11:00 |
| WP-15 | not started | — | 0 | |
| WP-16 | not started | — | 0 | P3 approved |
| WP-17 | in progress (2/4) | merged | 7 | 02 done (baseline beats LightGBM); 03 threshold now off the test split, CPU baseline AUC 0.69 on unseen families; Labib runs 01/03/04 on Kaggle |
| WP-18 | in progress (4/6) | merged + PR #14 | 19 + CI stack boot | compose, deploy+rollback, backups, DEPLOY.md; CI on main + PRs only; secret scan scoped to the tested commit (PR #14, all-refs scan before going public); China checks + mirror pending |
| WP-19 | not started | — | — | |
| WP-20 | in progress | wp-20-data | — | P7 approved; Labib at shops 18 Oct 10:00–14:00; anonymiser ready (PR #12) |

## 9. Submission (the 6 official deliverables)

| # | Deliverable | Source in repo | Builder |
| --- | --- | --- | --- |
| 01 | Technical documentation: architecture, core algorithms, security design | `docs/submission/technical-documentation.md` → PDF | Orchestrator sub-agent (from WP specs + code) |
| 02 | Presentation deck, ≤ 10 min | Slides artifact → PPTX/PDF | Orchestrator + Nobo |
| 03 | Demo video, ≤ 5 min (treated as required: deliverable 06 asks for it) | `docs/submission/video-script.md`; recording by Nobo | Orchestrator script; humans record |
| 04 | Source code + README + repo link + deployment instructions + test cases | repo; `README.md`; `docs/DEPLOY.md` | All; orchestrator writes README |
| 05 | Security self-assessment: permission tiers + known-risk list | `docs/submission/security-self-assessment.md` | Orchestrator sub-agent with B2 |
| 06 | Execution evidence: sandbox operation logs + demo video | `npm run evidence` → `docs/submission/evidence/` | B2 (harness) + orchestrator |

Submission email to wangyr@pbcsf.tsinghua.edu.cn: deck, tech doc, security self-assessment,
evidence bundle, video (MP4 attachment or link served from our SG server — YouTube and Google
Drive are blocked in China), repo link. **Repo:** private until Tuesday; the insurance
submission attaches a source zip; the final makes the repo public after a secret scan.

## 10. Backups (every few minutes, everywhere)

| What | How | Frequency |
| --- | --- | --- |
| Code on every machine | `scripts/autosave.ps1` commits to the current WP branch and pushes | every 5 min |
| Claude Code session state | `claude --continue` resumes the last session; each WP file's STATUS block is updated and committed at every milestone, so a fresh session can resume from the repo alone | each milestone |
| Kaggle | notebooks live in `ml/`; "Save Version" after each run; checkpoints each epoch to `/kaggle/working`; final artefacts pushed to the repo (< 50 MB) or Google Drive | each epoch / run |
| Colab | mount Google Drive; checkpoint to Drive each epoch | each epoch |
| Whole repo, off GitHub | `git bundle` to Google Drive (PC-4 scheduled task) | hourly |
| Hosted database | `pg_dump` on the server + copy to Drive; demo data is always re-seedable by script | hourly |
| Docs, deck | Claude Docs (autosaves); deck exports to Drive | continuous |
| Power / internet | laptops charged, phone hotspots as backup Wi-Fi, desktop on UPS if available; the orchestrator runs in the cloud and is unaffected by local outages | — |

## 11. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Pro quota runs out mid-wave | Stagger windows; big prompts; re-queue to the other account; humans switch to non-Claude tasks |
| Free LLM limits during judging | Cache, deterministic fallback, optional $5–10 paid credit |
| Judges in China can't open the site | SG host with good China routes, self-hosted fonts, no Google/Vercel assets, test from inside China |
| Parallel sessions collide | Contract-first, directory ownership map, one branch per WP, orchestrator merges |
| Hosting signup fails (card) | Fallback Oracle Always Free; last resort Render + Vercel |
| Field data not collected in time | Synthetic SME universe (labelled), real public datasets for backtests |
| Scope creep | PENDING items need approval; P-items marked "nice" are first to cut |
| Secret leak (OneGate's mistake) | gitleaks in CI from commit one, `.env` in `.gitignore`, deny-read rule in Claude settings |
