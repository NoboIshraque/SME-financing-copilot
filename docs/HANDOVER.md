# DecisionGuard — full handover (orchestrator chat → new chat)

> **Note (19 Oct 06:15 Dhaka, orch-A):** this is a snapshot from 18 Oct 06:10. Current state lives
> in `docs/ORCHESTRATOR.md` (baton), `docs/CLAIMS.md`, `docs/NOW.md` and PLAN §8. Since then:
> §7 orchestrator steps 1–4 are done (#9, #11, #12; PLAN refreshed). The §5 injection numbers
> (recall 96%, AUC 0.81) were measured with the threshold picked on the test split; the honest
> re-run is `ml/artifacts/injection_metrics_cpu_baseline.json` (AUC 0.69 on unseen families).

Written Sun 18 Oct 2026, 06:10 Dhaka, by the orchestrator (Claude, cloud session).
**Paste this whole file into a new Claude chat.** It is self-contained: who we are, what we are
building, every decision, what is done, what is pending, how the machinery works, and the
rules. The repo is the source of truth for code and the live status board.

---

## 0. First message to send the new chat

> You are the orchestrator for team DecisionGuard in the 2026 Shenzhen FinTechathon (Topic E, SME
> Finance Copilot). Read this handover fully. The repo is `NoboIshraque/SME-financing-copilot`
> (private). Attach it (add_repo with push access), clone it, read `CLAUDE.md`,
> `docs/PLAN.md` (§8 = live status board), `docs/NOW.md` (who does what next) and the WP files
> in `docs/packages/`. Then tell me the current state in five lines and what you will do next.
> Do not start any work package that belongs to a PC-2 session (WP-14, WP-15, WP-11, WP-10,
> WP-16); I start those myself.

---

## 1. Competition and team

- **Event:** 2026 Shenzhen International FinTech Competition (FinTechathon), International
  Track, **Topic E: SME Finance Copilot**. Hosts: Tsinghua PBCSF + WeBank. Theme: "AI as a
  Financial Participant".
- **Deadline:** **Tue 20 Oct 2026, 23:59 Beijing = 21:59 Dhaka.** Registration shares the
  deadline. Resubmissions allowed; the latest counts. Submit to `wangyr@pbcsf.tsinghua.edu.cn`.
- **Internal timeline:** insurance submission **Mon 19 Oct 21:00 Dhaka**; code freeze
  **Tue 14:00**; final submission **Tue 19:00**; repo made public **Tue 18:30** after a
  secret scan.
- **Scoring:** task completion 40%, security & compliance 30%, innovation & interaction 30%,
  plus an on-chain bonus of 0–5.
- **Six deliverables:** (1) technical document, (2) deck (≤ 10 min), (3) demo video (≤ 5 min),
  (4) source code + README + repo + deploy guide + tests, (5) security self-assessment
  (permission tiers + known-risk list), (6) execution evidence (sandbox logs + demo video).
  English only. Teams of 2–5, ≥ 60% non-Chinese.
- **Team (BUP, Bangladesh):**
  - **Nobo Ishraque** (lead, GitHub `NoboIshraque`): runs PC-1 (A1 session) and PC-2
    (B1 and B2 sessions); two Claude Pro accounts (account A on PC-1, account B on PC-2).
    Owns registration, DNS (Namecheap, `quadbits.net`), GitHub secrets, deck narration,
    submission.
  - **Amdad** (GitHub `amdad1203`): PC-3; server (Tencent Lighthouse Singapore), deploy keys,
    QA; optional Worker C (Antigravity CLI) for WP-09 / WP-12.
  - **Labib** (GitHub `lab-af`): PC-4 desktop (always on: Docker, Ollama, hourly integration
    + backup jobs), Kaggle/Colab runs, Sepolia wallet, real shop visits (WP-20).
- **Nobo's preferences:** concise, punchy, slightly playful; double-check and correct
  honestly; he catches mistakes and pushes back (directness is not hostility); confirm what is
  asked, check constraints, get it right first time; no guesswork; every earlier idea kept in
  the md files; back everything up continuously; prefers orchestration with multiple agents.
- **Nobo's standing instruction (18 Oct 06:06):** the orchestrator must **not** start PC-2's
  work packages. Nobo starts PC-2 himself around **09:00–10:00 Sunday** when the laptop
  arrives.

---

## 2. The product: DecisionGuard

Mobile-first PWA + FastAPI backend + agents for a small Bangladeshi business (grocery,
pharmacy, fabric wholesaler, garment subcontractor, hardware). Three official areas:
**A. financing-option matching, B. cash-flow management with alerts, C. business financial
analysis**, plus **D. the engine room** (reliability, privacy, security).

**Core principles (CLAUDE.md, non-negotiable):**
1. Code computes, the model narrates: no user-visible number comes from an LLM; every figure
   is `Decimal`, from a deterministic engine, with provenance (`formula_id` + input fact IDs).
2. Typed Fact Ledger only (no free text into engines).
3. Only anonymised data leaves the server; every LLM call goes through
   `backend/app/llm/gateway.py` which calls the privacy gate (fail closed).
4. Permission tiers READ / SUGGEST / DRAFT / EXECUTE / DENY; EXECUTE needs owner approval
   + step-up code; money never moves without a human.
5. Prefer abstaining to guessing.
6. Tests never call real LLMs or the network (a conftest guard enforces it).
7. No secrets in the repo; never read or print `.env`.
8. Synthetic data labelled `data_mode: "synthetic"` everywhere.
9. English for code/docs; UI strings via i18n (en, bn, zh).
10. No filler tests.

**Nobo's 20 features (all IN):** N1 expected-vs-reality; N2 ledger-based messages; N3 market
watch / price alerts / vendor routes; N4 lender report + simulated future; N5 typed facts;
N6 anonymised inputs; N7 code does the maths; N8 multi-agent + symbolic checker; N9
multi-model agreement; N10 self-loops with stressed inputs; N11 flaw-finder (critic) agent;
N12 multi-variable simulations; N13 clickable numbers (provenance); N14 liquidity mesh +
testnet hash of netting rounds (Nobo's own idea); N15 forecast evaluated on unseen data;
N16 decision stability score (stress vs irrelevant noise, ~10 variations); N17 required
"I don't know"; N18 privacy tokens; N19 negotiation with breakdowns; N20 lender check via
track record.

**Claude's proposals P1–P14:** all **IN** except **P10 (Telegram/WhatsApp) CUT** by Nobo on
17 Oct. P1 cost-transparent financing ranking (MUST), P2 security & permission tiers (MUST),
P3 eval harness + execution evidence (MUST), P4 mobile-money-first ingestion, P5
multilingual injection guard, P6 China-reachable hosting + Chinese UI, P7 real data from 3–5
Dhaka shops, P8 nightly audit drill, P9 "rails, not chat" action cards, P11 amount scaling,
P12 accessibility + PWA, P13 agent tool budget, P14 China jurisdiction pack (modelled).

**Answers Q1–Q4 (in FEATURES.md):** Q1 alert tiers — Watch: P(below buffer) > 20% within
22–90 days; Warning: > 20% within 8–21 days or > 50% within 22–45; Critical: > 20% within
7 days, > 60% within 21, or projected missed payroll/EMI; dedupe unless forecast moves > 10%
or > 3 days. Q2 receivables cause → counter table. Q3 gap detection (Monte Carlo, 1,000
paths, leading indicators, backtest). Q4 Trust Passport (counterparty attestations, anchored
versions, consented sharing, state-data adapter).

**Research done (in `docs/CONTEXT.md` and the Claude Doc research brief):** SME operations,
difficulties, current methods, why LLMs fail at financial analysis (with papers) and our
fixes, definitions (liquidity, liquidity mesh, netting), rival analysis.
**Rivals:** DuitDuit (Malaysia; 850 tests, 57 eval tasks, products "modelled on" schemes,
judges need a VPN), OneGate (India; LLM never run live, API key in git history, in-memory
audit), FlowWise, ururu9339 template. **We beat them on:** real BD products with sources, live
LLM traces, China reachability, real shop data, measured multilingual injection catch rate,
tests ≥ 1,000.

---

## 3. Architecture and stack (decided)

- Python 3.12, uv, FastAPI (app factory, routers auto-discovered from `app/api/*.py`, tables
  auto-discovered from `app/**/models.py`), SQLAlchemy 2, Pydantic v2 (frozen contracts),
  Postgres in deploy / SQLite in dev+tests. React 19 + TS + Vite 7 + Tailwind 4, i18next,
  react-query, recharts, Vitest 5, Playwright, ESLint 9. Task runner: root `package.json`
  npm scripts (Windows has no make).
- **LLMs ($0):** Gemini Flash = brain; Groq `gpt-oss-120b` + Qwen = voters/critic; Ollama
  `qwen2.5:3b` on PC-4 = private mode; deterministic planner fallback; recorded fixtures in
  tests; response cache. Free-tier limits indicative: Gemini ~10 RPM / ~1,500 RPD; Groq 30 RPM
  / 1,000 RPD / 8k TPM. Gemini is not available in HK/CN, so the server is in Singapore.
- **Hosting:** Tencent Lighthouse **Singapore** (Oracle Always Free SG as fallback), Docker
  Compose stack (Postgres, API, worker, Caddy with automatic HTTPS), domain
  **`hishab.quadbits.net`** (Namecheap A record `hishab` → server IP). Vercel mirror for the
  frontend only (later). No third-party hosts in the web app (China reachability); an e2e test
  fails if any page contacts another host.
- **Chain:** Ethereum **Sepolia** testnet; only 32-byte salted SHA-256 digests go on chain.
- **Docker** only on the SG server and Labib's PC-4; coding PCs use `npm run dev` + SQLite.
- **Machines:** PC-1 (knight-27, Nobo, A1, account A, `C:\hishab\repo`); PC-2 (Nobo, B1 in
  `C:\hishab\repo`, B2 in `C:\hishab\repo-b2`, account B); PC-3 Amdad; PC-4 Labib desktop
  (`C:\hishab\repo` for his work, `C:\hishab\integration` for hourly jobs). Claude accounts
  stay on Nobo's PCs only (ToS).

---

## 4. Repo, rules and machinery

- **Repo:** `NoboIshraque/SME-financing-copilot` (private). Collaborators to add (Nobo):
  `amdad1203`, `lab-af`.
- **Key files:** `CLAUDE.md` (rules + ownership map + "how the scaffold works"),
  `AGENTS.md` (copy for non-Claude agents), `docs/PLAN.md` (§8 status board),
  `docs/FEATURES.md`, `docs/CONTEXT.md`, `docs/RUNBOOK.md` (who does what, step by step;
  §4 Claude Code flow and start prompt; §5.2 server; §5.9 domain), `docs/team/NOBO.md`,
  `AMDAD.md`, `LABIB.md`, `docs/NOW.md` (do-this-next per person), `docs/packages/WP-00…WP-20.md`
  (each has owner, branch, owned paths, milestones, test quota, STATUS, Questions),
  `docs/DEPLOY.md`, `docs/api/contracts.json`.
- **Start prompt for a coding session (RUNBOOK §4):**
  ```
  Read CLAUDE.md and docs/packages/WP-XX.md. Work only inside the paths that WP owns.
  Implement the next unchecked milestone in its STATUS block, including its tests.
  Run the WP's test command until green. Commit with message "WP-XX: <milestone>" and push.
  Tick the milestone in the STATUS block and update the WP-XX row in docs/PLAN.md §8.
  Continue milestone by milestone until the WP is done. If you need a decision, write it under
  "Questions" in the WP file, commit, push, and stop.
  ```
- **Queues (updated 18 Oct):** A1 (PC-1): WP-01 ✅ → **WP-02** → WP-04 → WP-05 → WP-07 →
  (WP-09, WP-12 if Worker C is not used). B1 (PC-2): **WP-14** → WP-15. B2 (PC-2): **WP-11** →
  WP-10 → WP-16 (WP-03 moved to the orchestrator and is done). Orchestrator: WP-00, WP-03,
  WP-06, WP-08, WP-13, WP-17 notebooks, WP-18, WP-19, reviews and merges.
- **CI** (`.github/workflows/ci.yml`, on every push/PR): backend (ruff, pytest with CI
  Hypothesis profile, pip-audit), web (eslint, tsc, contracts-in-sync check, vitest, npm audit
  high, build), gitleaks over full history, and **Docker stack** (builds images, boots
  Postgres + API + worker + Caddy, smoke-tests TLS, CSP/HSTS/XFO headers, SPA fallback, API
  proxy). All green on main.
- **Deploy** (`.github/workflows/deploy.yml`): after CI succeeds on main → ships the exact
  commit via `git archive` over SSH to `~/hishab/releases/<sha>` → `infra/remote-deploy.sh`
  rebuilds → HTTPS health check → promotes to `~/hishab/current`, or **rolls back**. It is a
  no-op until the secrets `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_DOMAIN`
  exist. Hourly `pg_dump` backups (48 kept) via cron installed by each deploy.
- **Mission control** (live updates, built 18 Oct): GitHub **issue #8** "Mission control: who
  does what next", rebuilt by `.github/workflows/mission-control.yml` on every push to main,
  every CI/Deploy run and hourly (`scripts/mission_control.py`). Body = `docs/NOW.md`
  sections + build status + open PRs + PLAN §8. When a person's section in `docs/NOW.md`
  changes, a comment @mentions only them (GitHub Mobile push). Team handles in
  `.github/team.yml`. **To give someone new tasks: edit their section in `docs/NOW.md` and
  merge to main.** Nobo should pin the issue once.
- **Backups:** autosave scripts (`scripts/autosave.ps1/.sh`, commit+push every 5 min on WP
  branches, never `.env`), hourly git bundle to Google Drive (`scripts/bundle.ps1`), hourly
  integration test run on PC-4 (`scripts/integration.ps1`), GitHub itself, server pg_dumps.
- **Windows data fix:** `.gitattributes` marks `data/synthetic/universe/**` and
  `ml/artifacts/**` as `-text` (byte-exact). After pulling, each Windows folder runs once:
  `Remove-Item -Recurse -Force data\synthetic\universe; git checkout -- data/synthetic/universe`.

**Orchestrator environment quirks (cloud sandbox):**
- `gh` GraphQL is blocked: use REST (`gh api repos/.../pulls -f title=... -f head=... -f base=main -F body=@file`;
  merge with `gh api -X PUT repos/.../pulls/N/merge -f merge_method=merge`). The collaborators
  API is blocked through the proxy.
- The clone was shallow and single-branch: set
  `git config remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'` before `git fetch`.
- Docker Hub and ECR pulls are blocked/rate-limited here, so the Docker stack is verified in
  CI instead. Hugging Face and PyPI/npm are reachable. 2 CPU cores, 7 GB RAM.
- **Never `pkill -f <script name>` from a command that itself contains that name**: it kills
  itself (happened twice).
- A merge helper lives in the scratchpad (`merge_when_green.sh <pr> "<title>"`): it waits for
  ≥ 4 completed check runs on the PR head, then merges if all succeeded. Recreate it if needed.

---

## 5. What is built (state at 06:10 Sun 18 Oct)

`main` has **~600 backend tests + 34 web + 4 e2e**; with WP-03 it is **673 backend**. Target:
≥ 1,000 total (backend ≥ 850, web ≥ 110, e2e ≥ 45, eval ≥ 100 tasks, mutation ≥ 80%).

| WP | Owner | State | Tests | What exists |
| --- | --- | --- | --- | --- |
| WP-00 Foundation | orchestrator | **merged** | ~240 + 34 web + 4 e2e | scaffold, **contracts v1.1.0** (58 models, frozen, `examples.py` with one valid example each, JSON schema + generated TS types, drift tests), synthetic universe, CI, tooling, Mission control |
| WP-01 Facts | A1 | **merged** (PR #6) | 101 | fact store, versioned metric registry, provenance graph with masking hook, `GET /api/facts/{metric}`, `GET /api/explain/{figure_id}`; tenant/role stubs to be replaced by WP-11 |
| WP-03 Privacy | orchestrator | **PR #9 open** (needs main merged in, then CI, then merge) | 80 | detectors, token vault, anonymiser, gate, SQL vault store |
| WP-06 Financing | orchestrator | **merged** (PR #3), 7/8 | 123 | true-cost engine (EAR by IRR), real BD catalogue, eligibility, fit, lender score, ranking, non-loan options, application pack; API (milestone 8) waits for WP-01 facts (now merged) + WP-11 |
| WP-08 Mesh | orchestrator | **merged** (PR #1), 5/8 | 83 | obligation graph, min-cost-flow netting, consent, settlement receipts, attestations, salted anchors, offline + Sepolia anchorer, verify; pending: residual-gap routing, lender events, API |
| WP-13 Reports | orchestrator | **merged** (PR #5), 3/5 | 26 | Trust Passport versions (salted, anchored), consented sharing (scoped, ≤ 30 days, revocable, hashed tokens, view log), verification, state-data adapter mock; pending: lender report (needs WP-07), verify page/API |
| WP-17 ML | orchestrator + Labib | **merged** (PR #4), 2/4 | 6 | notebooks 01–04, payment-delay artefacts, injection corpus; Labib runs 01, 03, 04 on Kaggle |
| WP-18 Infra | orchestrator | **merged** (PR #2), 4/6 | 19 | compose stack, deploy with rollback, backups, DEPLOY.md, hosted demo env; pending: China checks (manual, RUNBOOK §5.6), Vercel mirror |
| WP-02, 04, 05, 07, 09, 10, 11, 12, 14, 15, 16, 19, 20 | various | not started | 0 | — |

### Details worth knowing

**Synthetic universe (`data/synthetic/universe/`, seed 20261020, deterministic):** 5 Dhaka
SMEs (`sme_grocery` Mirpur, `sme_pharmacy` Dhanmondi, `sme_fabric` Islampur,
`sme_garment` Ashulia, `sme_hardware` Nawabpur), 2025-04-01 → **2026-09-30 (as-of)**, 120-day
warm-up so baki is in flight on day one, real export formats (bKash/Nagad/bank statements,
cash book, baki register, bills, obligations, profile), `transactions_truth.csv` typed ground
truth, Eid/Boishakh seasonality, Friday effects, ~60% mobile money for retail, customer delay
habits incl. chronic late payers, Eid festival bonuses, owner draws, exactly 2 disputed
invoices, and an **open circular debt ring** (garment owes fabric 4.5 lakh; hardware owes
garment 3.2 lakh; fabric owes hardware 3.8 lakh). Loader: `app.synthetic.load_universe()`.
Festival calendar: `data/public/calendar/bd_festivals.yaml` (Eid ±1 day).

**Mesh demo result:** Tk 11.5 lakh of circular debt cleared with **Tk 1.9 lakh** of cash along
existing debts, or **Tk 1.3 lakh** with opt-in new links (`allow_new_links=True`).

**Financing catalogue (`data/public/financing/bd.yaml`, checked 2026-10-18 by a research
sub-agent, every row with source URL + verbatim quote):** 13 priced — Prime Bank Prime Chalti
(15% rate-sheet upper), Bank Asia SME term & micro WC (13%) and lease (12.5%), SBAC CMSME
(15.25%), Mercantile ANANNYA women (5%), City Bank–bKash loan (9% last published, 0.575% fee,
≤ Tk 50k, 6 months), Bangladesh Bank schemes (2026 CMSME WC refinance cap 9%, Tk 25,000 cr
pre-finance 7%, women refinance 5%, startup 4%, closed-industry 7%), PKSF microenterprise at
the **MRA 24% cap**. 5 unpriced ("ask the lender", never ranked on a guessed cost): Prime
Shongjog, BRAC–bKash merchant loan, BRAC Shafollo, BRAC supplier financing, Mercantile
factoring. `bd_regulatory.yaml`: MRA 24% cap, market-based rates since SMART was scrapped
(8 May 2024), 4-point spread cap (29 Jun 2026), e-loan rule (≤ Tk 50k, ≤ 12 months, ≤ 9% if
refinanced), processing fee ≤ 0.5% (max Tk 15k). `cn.yaml`: P14 modelled China pack. Contract
field `rate_basis` says how each rate is known. Ranking: 45% cost (100 − 2.5 × EAR) + 25% fit
+ 15% approval + 10% speed + 5% lender record; ineligible options last with reasons; purpose
matching (leasing only for equipment/vehicles). For a grocery needing Tk 2 lakh for 6 months,
the 4% startup refinance ranks first and microfinance at 24% sits well below.

**Cost engine checks (independent float calc + numpy):** 12% reducing = 12.68% EAR; 12% flat
= 23.70%; 2% off for 20 days early = 44.59% a year.

**ML findings (honest):**
- Payment delay (notebook 02, synthetic): LightGBM **does not beat** the customer-history
  baseline (MAE 2.92 vs 2.83 days) → rule picks the baseline; WP-05 uses it until real data.
- Injection classifier CPU baseline (DistilBERT-multilingual, run here, 4 epochs): on unseen
  attack families **recall 96%**, precision 62%, AUC 0.81; by language en/bn/bl recall 100%,
  zh 83%; it over-flags benign "share report with lender" (100% false positives in that family)
  and statement rows (62%); public English test F1 0.88. Metrics file:
  `scratchpad/inj/hishab_ml/injection_metrics.json` (not yet committed; commit to
  `ml/artifacts/injection_metrics_cpu_baseline.json`). Labib's Kaggle GPU run with mDeBERTa
  should improve precision; WP-11's rules layer runs first.
- Forecast backtest (01) and price-alert backtest (04): code verified end to end on
  look-alike data; real results come from Labib's Kaggle runs (UCI Online Retail II via
  `mashlyn/online-retail-ii-uci`; AgriPriceBD from Mendeley DOI 10.17632/bkmxnrn3hn.1).

**Injection corpus (`data/public/injection/`):** 192 rows, 12 attack + 12 benign families ×
EN/BN/Banglish/ZH, hard negatives, stratified family-held-out test split (24 attack + 24
benign test rows). Reused by WP-11 (guard) and WP-16 (adversarial eval).

**WP-03 interfaces:** `anonymise(text, vault=, tenant=, anchor=, roles=, scale_amounts=)` →
`Anonymised.text/labels/restore()`; `assert_safe(payload)` (raises `PrivacyViolation` naming
kinds only); `TokenVault.from_setting(vault_key, authoriser)`, `.put(tenant, Kind, value)` →
`PERSON_xxxxxxxxxx`; `SqlVaultEntries(session)` for persistence.

---

## 6. Secrets and keys (rules)

- Nobo has: Groq key, Gemini key, MetaMask (Sepolia) private key + RPC URL.
- **Never paste any key into chat, a file in the repo, or a commit.** Hand over in person.
- GitHub Actions secrets (Nobo only, he is the repo owner): `GEMINI_API_KEY`, `GROQ_API_KEY`
  (for the live-LLM check), and later `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`,
  `DEPLOY_DOMAIN`. **The Sepolia private key does not go into GitHub or the PCs** — only into
  the server's `~/hishab/shared/.env` (with `CHAIN_MODE=sepolia`).
- PCs: `backend\.env` (from `.env.example`) holds only Gemini/Groq; `LLM_MODE=fixtures`.
- The orchestrator never enters credentials anywhere itself.

---

## 7. Next steps

**Nobo (now):** add collaborators `amdad1203`, `lab-af`; pin Mission control (#8); Actions
secrets `GEMINI_API_KEY`, `GROQ_API_KEY`; `.env` on PCs; GitHub Mobile; Windows data fix; A1 →
WP-02 (`wp-02-ingest`); **~09:00–10:00: start PC-2 himself** — B1 on WP-14 (`wp-14-web`),
B2 on WP-11 (`wp-11-security`); DNS + deploy secrets when Amdad has the server.

**Amdad:** accept invite; server per RUNBOOK §5.2 (SG Lighthouse, Ubuntu 22.04, 2 vCPU/4 GB,
ports 22/80/443), send IP; Docker; `~/hishab/shared/.env` (DEPLOY_DOMAIN, POSTGRES_PASSWORD,
SECRET_KEY, VAULT_KEY via `openssl rand -hex 32`; LLM + Sepolia keys typed in with Nobo;
`CHAIN_MODE=sepolia`); deploy key; hand Nobo DEPLOY_HOST/USER/SSH_KEY in person.

**Labib:** accept invite; shops 10:00–14:00 (WP-20 consent text + interview in WP-20.md);
afternoon Kaggle notebooks 01, 03, 04 (table in `docs/team/LABIB.md`); PC-4 hourly jobs.

**Orchestrator (new chat):**
1. Finish PR #9 (WP-03): `git merge origin/main` into `wp-03-privacy`, resolve the PLAN §8
   WP-03 row (keep "done … 80 …"), push, wait for CI, merge.
2. Commit the CPU injection baseline metrics to `ml/artifacts/`.
3. Build the **anonymiser CLI for Labib's shop files** (WP-20): input a folder of raw
   CSV/XLSX, output tokenised files to `data/real_anonymised/<shop>/` + a report of
   detection counts by kind (no values); vault entries saved to a local SQLite file kept out
   of git. Post the exact command in Labib's NOW.md section.
4. Refresh PLAN §8 (stale rows: WP-16 "needs P3 approval" and WP-20 "needs P7 approval" are
   approved — clear them) and update `docs/NOW.md` after every merge.
5. Review and merge PRs from A1/B1/B2 as they come (check owned paths, CLAUDE.md rules, CI).
6. WP-06 milestone 8 (financing API) and WP-08 milestone 8 (mesh API) once WP-11 provides the
   principal and step-up check; WP-13 report once WP-07 lands.
7. **Mon 10:00:** WP-19 — run sub-agents in parallel for the six deliverables; insurance
   submission Mon 21:00. Every number in the deck/docs must trace to evidence or a source.
8. Mission control works; keep check-ins light. Do not start PC-2 packages.

**Open items / risks:** PC-2 started late (biggest risk: WP-14 web and WP-11 security are
long); registration email + on-chain bonus question email (status unknown — ask Nobo);
server not yet created; Kaggle runs pending; real shop data pending; WP-10 (agents) depends
on WP-11 and WP-03.
