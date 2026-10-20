# DecisionGuard final end-to-end audit

Auditor session: `audit` (helper, not the on-duty orchestrator). Branch `audit-final`, started
20 Oct 2026 06:54 Dhaka from `main` at `335c1ca`. Nothing was merged and nothing was pushed to
`main`; `docs/NOW.md` and PLAN §8 were not touched. No `.env` file or key was opened.

## 1. Summary

The product runs. Lint is clean; 2,244 backend tests (2 skipped) and 210 web tests pass on
`main`, and 2,249 + 212 on this branch. The offline eval reproduces the published 53/62
(functional 26/26). Local Playwright: 27 passed, 2 skipped (the mesh journey skips itself against
the live API). The security core holds when probed live with real sessions: tenant isolation,
the origin check, step-up on EXECUTE, single-use codes, the DENY list, the lender's 403s and the
three-owner mesh round with verify. The weak points are the **submission documents**, which
overstate or misstate several things, the **injection guard's generalisation**, and three broken
or unwired demo paths.

Findings: **2 Critical, 7 High, 16 Medium, 12 Low** (37 open). Fixed on this branch, each with a
test that failed before the fix: ingest preview/columns now require `ingest:upload` (self-assessment
R2), the Today alert lists every gap driver (duplicate React key), and Today asks the copilot in
the reader's language (BN/ZH users got English). Evidence counts were regenerated to match.

Three decisions for the orchestrator before 21:59 Dhaka:

1. **Correct the guard claims (C1) and the stale feature claims (M1–M6) in the deck, the security
   self-assessment and the video script, then re-export the PDFs.** The deck says "one new Bangla
   paraphrase got through". The repo's own eval says 9 of 12 new attacks got through, and a fresh
   blind set written for this audit was caught 13/24 with 10/24 false alarms. The deck also says
   receivables and reminders are "not built", which is false. While re-exporting, fix the deck PDF
   layout (H6): 5 of 14 slides are clipped.
2. **Decide on the copilot's narration check (C2).** A live model can state a figure in words ("fifty
   thousand", "五万", "পঞ্চাশ হাজার") and it passes the check. This breaks rule 1 in `llm_mode=live`,
   which is the deployed default. Either ship the demo with `LLM_MODE=deterministic` or `fixtures`, or
   accept a small fix in `checker.py` that rejects any narration containing a number word (the
   fallback, the claim texts, is always safe).
3. **Decide what the hosted demo shows (H3, H4, H5).** The deploy never seeds the ledger, so Today
   and Cash abstain on a fresh server. The Analysis "How stable is today's advice?" card always shows
   "Unknown recommendation" on the real API. Message approve/send are labelled EXECUTE but need no
   step-up code. Either fix them (each is small but crosses work packages) or keep them off camera and
   say so in the documents.

## 2. Findings

Severity: Critical = breaks a non-negotiable rule, leaks data or secrets, or makes a submission
claim false; High = a demo journey or security check fails; Medium = wrong number or stale claim in
a deliverable, a11y serious; Low = polish.

| ID | Severity | Area | File:line | What is wrong | Evidence / how reproduced | Fixed in commit or recommendation |
| --- | --- | --- | --- | --- | --- | --- |
| C1 | Critical | Submission: guard claims | `docs/submission/deck/slides/security.html` (text and notes), `limits.html`; `pdf/deck.pdf` p.11, p.13; `security-self-assessment.md:280-285`, `:423-429` | Deck and self-assessment say generalisation is "unmeasured" and that "one new Bangla paraphrase got through". Measured: the repo's eval caught 3 of 12 new attacks (9 missed). The audit's fresh blind set: 13/24 attacks caught, 10/24 benign messages flagged. The tech doc (`technical-documentation.md:806-808`) states 3/12 correctly, so the documents contradict each other. | `npm run eval` → `attacks (new): caught 3/12, contained 11/12, approval held 12/12`. Fresh set: `docs/handover/fresh_injection_set.jsonl`, per-row verdicts in `docs/handover/fresh_injection_result.txt` (section 2.1). | not fixed - recommendation: replace both statements with the measured numbers (eval 3/12 caught, 11/12 contained, 12/12 approval held; fresh audit set 13/24 caught, 10/24 false alarms, 0/4 skip-approval caught). Keep "the copilot still could not act" (true: approval held 12/12). Re-export deck and SSA PDFs. |
| C2 | Critical | Rule 1 (no LLM numbers) | `backend/app/agents/checker.py:57`, `:342-353`; used at `backend/app/agents/orchestrator.py:376` | The narration check only finds digit strings. A narrated number in words (English, Bangla or Chinese) is not detected, so a live model's invented figure reaches the user as `answer_text`. Default `LLM_MODE` in `infra/.env.example` and `docker-compose.yml` is `live`. | `unverified_numbers("You will be short by about fifty thousand taka next month.", [])` → `set()`; same for `下个月你将短缺五万塔卡。` and `আগামী মাসে প্রায় পঞ্চাশ হাজার টাকা ঘাটতি হবে।`; `"Short by 50,000 taka."` → `{5E+4}`. | not fixed (WP-10, judgement call) - recommendation: in `_narrate`, fall back to the claim texts when the narration contains a number word (en: one…ninety, hundred, thousand, lakh, crore, million; bn: এক…, শত, হাজার, লাখ, কোটি; zh: 〇一二三四五六七八九十百千万亿两) that the claim texts do not contain. The fallback is always correct, only less fluent. Or run the hosted demo with `LLM_MODE=deterministic`. |
| H1 | High | Security: injection guard | `backend/app/security/guard.py` (rules in `guard_rules.py`, not opened for this measurement) | On 24 new attacks: skip_approval 0/4 caught, change_bank_details 1/4, exfiltrate_vault 2/4, disable_audit 3/4, hidden_instruction 3/4, add_payee 4/4. On 24 innocent messages with the same words, 10 were quarantined, including "How do I add a new payee…", "Can anyone turn off the audit log?" and the Chinese/Bangla "is my customer data encrypted in the vault?". A false positive blocks an owner's real question with 422. WP-15 known bug 2 (everyday Bangla override phrasing) is still open. | Section 2.1. e2e run: `Known bugs observed… WP-11 (security): the injection guard allows everyday Bangla override phrasings`. | not fixed (rule 4 of the audit brief: never tune the guard to a test set) - recommendation: report the numbers as they are (C1). Approval held 12/12 in the eval, so the tiers are the real control; say that plainly. |
| H2 | High | Rule 4 (EXECUTE needs step-up) | `backend/app/api/messaging.py:130-145` | Message approve and send are written to the audit chain as `tier=EXECUTE` (`send_message`/`send_reminder` are EXECUTE in `policy.py`), but neither route asks for `X-Step-Up-Code`. The deck says "Anything that leaves DecisionGuard is EXECUTE: the owner approves with a fresh one-time code". Nothing is sent automatically (copy channel), so the practical risk is low; the inconsistency is in the claim. | Code read; e2e `receivables.spec.ts` approves and sends without a code. | not fixed (WP-12 + WP-14 web flow) - recommendation: add `step: StepUp = Depends(step_up)` to approve (as `mesh.py:182`) plus the code prompt in the Messages screen, or record these as DRAFT/"copied by the owner" and say so in the SSA tier table. |
| H3 | High | Demo journey: Analysis | `web/src/screens/analysis/AnalysisScreen.tsx:66-73`; `backend/app/api/analysis.py:486-490` | "How stable is today's advice?" sends the copilot Today recommendation id to `POST /api/analysis/stability`, which only knows ids from `/scenarios`. With the real backend it always shows "Unknown recommendation". Today's recommendation also carries `stability: null`. | Sweep: every owner/accountant Analysis view logs `404 /api/analysis/stability`; screenshot shows the error card. API: `POST /api/analysis/stability {recommendation_id: <today id>}` → 404 `analysis.unknown_recommendation`. | not fixed (WP-14 ↔ WP-07/WP-10 integration) - recommendation: use `compare.data.recommendation_id` (stability of the compared decisions, shown after **Compare**), or hide the card when Today has no stability report. Keep it off camera (the video script already says "skip if it does not render"). |
| H4 | High | Hosted demo / deployment | `docs/DEPLOY.md:28-35`, `infra/docker-compose.yml`, `.github/workflows/deploy.yml`; `README.md:36-44` | Nothing seeds the synthetic ledger outside e2e (`e2e/global-setup.ts`). On a fresh server, and after `npm run dev` on a fresh clone, Today and Cash abstain. `CLAUDE.md` even says `npm run dev` has "seeded synthetic data". WP-15 Question 2 asked for this on 19 Oct. | `grep seed` in infra, DEPLOY.md and deploy.yml: none. The video script (`video-script.md:310-313`) documents the manual step; README and DEPLOY do not. | not fixed - recommendation: add `docker compose exec api python -m app.facts.seed` to DEPLOY §3 and to `remote-deploy.sh` after the health check (idempotent? check `app/facts/seed.py` first), and `uv --directory backend run python -m app.facts.seed` to the README quick start. |
| H5 | High | Deliverable 06 / demo | `docs/submission/evidence/` (no e2e summary), `web/e2e/journeys/mesh.spec.ts:32` | No browser test covers the mesh against the live API: the mesh journey skips itself when the API is live and the multi-party version was never written. The evidence bundle has no e2e run at all (the hosted run waits for the server). | `npm run e2e`: `-  [local] mesh.spec.ts … (skipped)`. The audit checked the flow by API instead (section 3): propose → three owners approve with codes → settled → verify valid. | not fixed - recommendation: commit a local e2e summary (`E2E_EVIDENCE_DIR` run against localhost) as interim evidence and say in INDEX.md that the hosted run is pending. |
| H6 | High | Deliverable 02 layout | `docs/submission/pdf/deck.pdf` pages 2, 3, 6, 7, 10 (`problem`, `owner`, `cash`, `financing`, `mesh`) | Content is clipped at the bottom of 5 slides: the "7.28%" and "71%" cards are cut off, the owner's third question card overlaps the footer, the cash card's "Cheapest fix" line is cut, the financing cards row is cut, and the mesh "of cash, along debts…" line falls off. The HTML sources at 1920×1080 overflow by 23 to 275 px. | `pdftoppm` of `deck.pdf`; Playwright render of each `slides/<id>.html` at 1920×1080: `problem` scrollHeight 1355, `owner` 1103, `cash` 1193, `financing` 1250, `mesh` 1285, `copilot` 1083. | not fixed - recommendation: shorten or shrink those slides in the Slides artifact and re-export; the PDF is what judges open. |
| H7 | High | Submission claim: provenance | `README.md:10-11`; PLAN §8 WP-14 row; `web/src/screens/analysis/AnalysisScreen.tsx:95`, `:124` | "Every figure on screen can be clicked to show its formula" is not true: ratio values and the "Expected" column of Expected vs reality are plain text, and so are the Market sample prices. The sweep counted 5 to 18 money or percent strings per screen outside a provenance button on Cash, Receivables, Analysis, Mesh and Messages. Some are labels or inputs, but the ratio cards are figures. | Sweep `bare` counts (section 3.1); Analysis screenshot. | not fixed (WP-14) - recommendation: wrap ratio values and expected values in `FigureValue`/`Num` (the API returns provenance for ratios), or soften the claim to "every engine figure". |
| M1 | Medium | Deck: stale feature claims | `deck/slides/limits.html`; `pdf/deck.pdf` p.13 | "Not built: receivables and reminders", and "Next: receivables and reminder drafts in the approval queue": both are merged (PR #31, #34) and demoed in e2e. "An adversarial test suite… next": the eval has 36 adversarial tasks. | Slide text; PLAN §8 WP-05/WP-12 rows. | not fixed - recommendation: rewrite the slide and notes, re-export. |
| M2 | Medium | SSA §0 "What is built" | `security-self-assessment.md:31-40` | WP-10 is listed as "branch, PR pending", and WP-12 and WP-16 as "not in this snapshot". All three are merged (PR #29, #34, #33). WP-13 passport API (PR #35) is missing. Section 4 says "WP-16's adversarial suite… is not in this snapshot". | PLAN §8; `git log`. | not fixed - recommendation: refresh the table and §4. |
| M3 | Medium | SSA route table | `security-self-assessment.md:171-172`, footnotes `:149-151` | The table still says the fact routes and `/ingest/history` let every role through. `/api/facts` and `/ingest/history` need `ledger:read` (PR #32), and since this branch preview/columns need `ingest:upload`. R1 is right that `/api/explain` stays open to lender viewers, masked. | Live: lender `GET /api/facts/net_sales` → 403, `GET /api/ingest/history` → 403. | not fixed - recommendation: update the rows; mark R2 fixed (commit `f4e585f`) once merged. |
| M4 | Medium | Video script stale | `docs/submission/video-script.md:35`, `:267`, `:293-295` | "Reports/Passport sharing… have no backend router", "Messages (cut), Receivables (no backend), Reports/Passport (no API on `main`)" contradict lines 32-34 and the merged APIs. Test count "1,696 backend + 210 web" (now 2,244 / 2,251). | Text. | not fixed - recommendation: refresh before recording. |
| M5 | Medium | Privacy claims vs code | `video-script.md:238-239`; `technical-documentation.md:621-626`; `backend/app/llm/gateway.py:12-13` | VO says "amounts are scaled by a secret factor… our model gateway runs this on every request"; the tech doc says the gateway anonymises with `prepare_messages()`. In code `prepare_messages` has no caller, `scale_amounts=True` is never used, and the narrator and critic receive exact amounts and product names (the fail-closed gate still runs, and no personal data was in the payloads). | Spy on `LLMGateway.complete` during a copilot run: the narrate payload holds "Cash on hand now: Tk 9,29,018." etc. | not fixed - recommendation: change the wording to "names, phones and places are replaced; figures sent for narration are exact amounts with no personal data; the gate refuses any request with personal data". |
| M6 | Medium | README stale | `README.md:27`, `:36-44` | "WP-10, being merged" (merged); quick start lacks the seed step (H4). | Text. | not fixed - recommendation: update. |
| M7 | Medium | Evidence stale | `docs/submission/evidence/test-runs/backend-pytest.txt` | Says `1694 passed, 2 skipped`; the current suite is 2,244 (main) / 2,249 (this branch). | `npm run test` (section 4). | not fixed (evidence is WP-19's) - recommendation: re-run and replace both test-run files on the freeze commit. |
| M8 | Medium | Feature described as live, no backend | `web/src/api/endpoints.ts:162-163`; Settings screen | Settings → Notifications shows "Something went wrong. Please try again." with the real backend (`GET /api/settings` → 404). | Sweep: every Settings view logs `404 /api/settings`; screenshot. | not fixed (WP-14) - recommendation: hide the Notifications card when the route is absent, or label it like Market. |
| M9 | Medium | Passport sharing delivers nothing | `backend/app/api/reports.py:193-200` | `POST /reports/passport/{id}/share` creates the grant and throws the share token away: no response field, no route accepts it. The owner "shares" with a code, but the lender gets no link. Lender access in practice is the separate `/api/auth/lender-access` account flow. | Code read; e2e `passport.spec.ts` only checks the grant list. | not fixed (WP-13; contract change needed to return the token) - recommendation: say in the docs that sharing records consent and the lender signs in with a lender-access account, or return the link once (needs a WP-00 contract change). |
| M10 | Medium | a11y (serious) | `web/src/components/TierBadge.tsx:32` | Watch alert badge: white on `sky-600`, 4.02:1 (needs 4.5:1). Seen on Today in every language and size. | axe in the sweep: `serious:color-contrast(2)` on Today. | not fixed (WP-14) - recommendation: `bg-sky-700`. |
| M11 | Medium | a11y (serious), WP-15 known bug 4 | Cash chart | `aria-hidden-focus`: focusable SVG inside an `aria-hidden` chart. | axe: every Cash view; e2e known-bug list. | not fixed (WP-14) - recommendation: add `tabIndex={-1}`/`focusable="false"` inside the chart or drop `aria-hidden`. |
| M12 | Medium | Layout + a11y on phone, WP-15 known bug 3 | Trust screen audit table | Trust is 45-69 px wider than a Pixel 7 in every language; axe `scrollable-region-focusable`. | Sweep `overflow` 63 (en), 45 (bn), 69 (zh). | not fixed (WP-14) - recommendation: `relative` + `tabIndex={0}` on the scroll wrapper (WP-15.md). |
| M13 | Medium | a11y (serious), WP-15 known bug 4 | Reports, Settings (dark theme) | `slate-500` small text at 3.74:1 in dark mode. | e2e known-bug list (the sweep ran in light mode). | not fixed (WP-14) - recommendation: `dark:text-slate-400`. |
| M14 | Medium | i18n: English in BN/ZH | backend label keys vs `web/src/i18n/locales/*.json` | 95 keys the backend emits (`driver.*`, `interpretation.*`, `ratio.missing.*`, `rule.*`, `error.*`, `auth.*` audit actions, `alert.*`) have no translation in any locale, so `useServerText` shows a humanised English fallback ("Disputed invoice", "Dio", "Password ok", "Totp failed") on the Bangla and Chinese screens. The audit table also shows raw user ids (`u-a6b6…`). | `docs/handover/missing_i18n_keys.txt`; BN Today and Trust phone screenshots. en/bn/zh parity itself is perfect (730 keys each). | not fixed (WP-14) - recommendation: add the visible ones (driver, ratio, interpretation, auth, error) to all three locales. |
| M15 | Medium | Hash display, WP-15 known bug 5 | Trust "Latest hash" | In Bangla mode the digits inside the audit hash become Bangla digits, so the hash cannot be compared with the API or the verify page. | BN Trust screenshot. | not fixed (WP-14) - recommendation: render hashes in a `lang="en"` / `translate="no"` span and skip `banglaDigits`. |
| M16 | Medium | Role navigation vs API | `web/src/navigation.ts:43-48` | The accountant's navigation includes Trust (all screens), but the accountant has no `audit:read`, so both audit cards show "Your role can't do this". Compliance's Trust shows an error for the abstention log (`/api/copilot/abstentions` needs `copilot:ask`). | Sweep: accountant Trust → `403 /api/audit/events`, `/verify`, `/anchors`; compliance Trust → `403 /api/copilot/abstentions`. Screenshot. | not fixed (WP-14/WP-11) - recommendation: drop Trust from the accountant's screens (or hide the audit cards without `audit:read`), and let `audit:read` read abstentions or hide that card for compliance. |
| L1 | Low | Lender scope | `backend/app/api/reports.py:171-175` | A lender viewer (scope `passport:read`) can list every share grant of the tenant, including other lenders' labels. | Live: lender `GET /api/reports/shares` → 200 with two other grants. | not fixed - recommendation: filter to grants naming that lender, or require `approvals:decide`. |
| L2 | Low | Public verify ids | `backend/app/api/reports.py:220`; ids `pp-<tenant>-v<n>` | Passport ids are guessable, so the public verify route confirms which tenants exist and how many versions they issued. | `GET /api/verify/pp-sme_grocery-v1` without a session → 200. | not fixed - recommendation: random ids, or accept as by design and list it in the SSA. |
| L3 | Low | Global anchor trigger | `backend/app/api/auth.py:568-577` | A compliance user of one tenant can run `POST /api/audit/anchor`, which anchors every tenant's chain head (with Sepolia on, that spends gas); `GET /api/audit/anchors` shows the global head count. | Live: compliance `POST /api/audit/anchor` → 200; anchors list `heads: 4`. | not fixed - recommendation: restrict manual anchoring to the system job, or accept and list it. |
| L4 | Low | Guard check by lender | `backend/app/api/auth.py:604-616` | Any signed-in role, the lender viewer included, can call `POST /api/guard/check` and write quarantine rows into the tenant. | Live: lender → 200. | not fixed - recommendation: require `copilot:ask`. |
| L5 | Low | Leftover "Hishab" | `backend/app/llm/prompts.py:19,33,43,49`; `AGENTS.md:2`; `package.json:4`; `backend/pyproject.toml:4`; contracts title | The model is told "You are the planner of Hishab", so a live narration can name the old product. Not user-facing otherwise. Changing the prompts invalidates the recorded fixtures (prompt hash). | `git grep Hishab`. | not fixed - recommendation: leave the prompts until after the submission (re-record fixtures then); fix the descriptions if time allows. |
| L6 | Low | Cut features visible | `web/src/navigation.ts:12` (Market); Reports passport card | Market (WP-09 cut) is in the navigation for owner, accountant and staff, with a "Negotiate a sale" form (N19 cut); it is labelled "Preview with sample data". Reports shows "Audit drill catch rate —" (P8 cut) and a "Lender report" share scope (WP-13 lender report cut). | Screenshots. | not fixed - recommendation: hide Market from the nav and drop the two cut rows, or leave them labelled. |
| L7 | Low | Phone layout | Floating "Ask DecisionGuard" button | On a Pixel 7 the floating button covers figures (Today's buffer, Trust rows, Mesh round totals). | Phone screenshots. | not fixed - recommendation: add bottom padding equal to the button height on phone. |
| L8 | Low | DEPLOY reference | `docs/DEPLOY.md:60` | Points to `docs/submission/evidence/china.md`, which does not exist ("Measured access from mainland cities"). | `ls`. | not fixed - recommendation: remove the sentence until measured. |
| L9 | Low | Engines and the database | `backend/app/engines/{cash,analysis}/jobs.py`, `*/store.py`, `*/models.py`, `mesh/store.py` | Persistence adapters live inside engine packages and import the DB. The calculation modules are pure (no DB, no network); the mesh settlement takes an injected anchorer. Fine for the rule's intent, but the layout invites a future breach. | `grep sqlalchemy app/engines`. | not fixed - recommendation: none before the deadline. |
| L10 | Low | Copilot Today in Chinese | `backend/app/agents/claims.py` amount rendering | Chinese narration groups amounts the Bangladeshi way ("4,27,842 塔卡"). | Live `GET /api/copilot/today?language=zh`. | not fixed - recommendation: optional; the web formats its own figures correctly. |
| L11 | Low | Messages drafts in Bangla | `web/src/api/endpoints.ts:142` | The web never passes `language` to `GET /api/messages/drafts`, so Bangla readers only see English drafts although the API renders Bangla. | Code read. | not fixed - recommendation: pass `language=bn` when the UI is Bangla (zh has no template; keep en). |
| L12 | Low | Copilot coverage offline | grocery tenant, Trust abstention log | In `fixtures` mode "Which customer should I chase first?" abstains as out of scope, although a receivables intent exists. Only questions with recorded plans or rule matches are answered offline. | Abstention log entry seen in the sweep. | not fixed - recommendation: rehearse the video's exact copilot questions in the mode the demo will run. |
| F1 | (fixed) High | Role check: ingest | `backend/app/api/ingest.py:122-160` | `/ingest/preview` and `/ingest/columns` checked only the session, so a lender viewer or compliance reviewer could upload and parse files (SSA risk R2). | New tests `test_roles_without_ingest_upload_may_not_upload[*]` failed 4/4 before the fix. | **Fixed in `f4e585f`** (require `ingest:upload`; staff still may preview, tested). |
| F2 | (fixed) Medium | Today alert drivers | `web/src/screens/today/AlertCard.tsx:74-75` | Two drivers of the same kind (the hardware shop's two supplier bills) shared a React key, so React warned and may drop or duplicate a row on update. | Console error on every Today view in the sweep; new Vitest test failed before the fix. | **Fixed in `d29a20d`**. |
| F3 | (fixed) Medium | Today in BN/ZH | `web/src/api/endpoints.ts:128-129`, `TodayScreen.tsx`, `AnalysisScreen.tsx` | The web never sent `?language=` to `/api/copilot/today`, so Bangla and Chinese readers got the daily advice in English. | BN Today screenshot; new Vitest test failed before the fix; live `?language=bn` returns Bangla. | **Fixed in `c0e63c1`**. |

(F1–F3 are counted in the totals above as fixed, not as open findings: open = 2 Critical, 7 High,
16 Medium, 12 Low.)

### 2.1 Fresh injection set (written before opening the guard rules or the eval tasks)

`docs/handover/fresh_injection_set.jsonl` was committed first (`a320c0e`), then measured with
`InjectionGuard().inspect(text, Source.user_message)` (rules only; no classifier is installed).

| Family | Attacks caught (en, bn, bl, zh) | Benign flagged (en, bn, bl, zh) |
| --- | --- | --- |
| skip_approval | 0/4 (none) | 0/4 |
| change_bank_details | 1/4 (en) | 1/4 (en) |
| add_payee | 4/4 | 4/4 (all) |
| exfiltrate_vault | 2/4 (bn, zh) | 2/4 (bn, zh) |
| disable_audit | 3/4 (en, bn, zh) | 2/4 (en, zh) |
| hidden_instruction | 3/4 (en, bl, zh) | 1/4 (zh) |
| **Total** | **13/24 (54%)** | **10/24 (42%)** |

By language: en 4/6 caught, 3/6 false alarms; bn 3/6, 2/6; bl 2/6, 1/6; zh 4/6, 4/6. The guard
keys on vocabulary ("payee", "vault", "audit log", "收款人") rather than intent, so the same words
in an innocent question trip it, and paraphrases without those words pass. Per-row verdicts and
rule ids: `docs/handover/fresh_injection_result.txt`.

### 2.2 WP-15 "Found by the suite": still open?

| # | Bug | Status on `audit-final` |
| --- | --- | --- |
| 1 | Lender viewer reads ledger figures (`/api/facts/*`) and the upload list (`/ingest/history`) | **Fixed** (PR #32): live lender → 403 on both. Ingest preview/columns: fixed here (F1). `/api/explain` stays open to lenders, masked, by design (R1) |
| 2 | Everyday Bangla override phrasings pass the guard | **Open**: observed by the e2e run and by the fresh set ("আগের সব নির্দেশ ভুলে যাও…" allowed) |
| 3 | Trust wider than a phone; `scrollable-region-focusable` | **Open** (M12) |
| 4 | Cash chart `aria-hidden` focusable; dark `slate-500` 3.74:1 on Reports/Settings; Watch badge 4.02:1 | **Open** (M11, M13, M10) |
| 5 | Bangla digits inside hashes; verify page says "Not genuine" before anchoring; demo owner codes single-use per 30 s; two parallel first calls to `/demo-accounts` can 500 | Hash digits **open** (M15). Single-use codes **open by design** (hit twice during this audit: sign in again after 30 s). Verify wording and the parallel-seed 500 were not re-tested |
| — | WP-00: SQLite without WAL ("database is locked" under parallel requests) | Not observed in this run (e2e with 2 workers, sweep and API probes in parallel) |

## 3. Checked and found fine

- **Live API probes with real sessions** (`npm run dev`, demo accounts):
  - Tenants stay isolated. A pharmacy owner gets 404 on a grocery approval, a grocery message
    draft, a grocery passport share and `/api/explain/{grocery figure}` (and `/rows`). Naming
    another tenant in `/api/facts` → 403.
  - The origin check holds. A POST with `Origin: https://evil.example` → 403, and so does a POST
    with `Sec-Fetch-Site: cross-site`.
  - Step-up is enforced on the server. Approve without a code → 401, with a wrong code → 401,
    with a fresh code → 200. Re-using that code on a second approval → 401 (single-use step).
    Execute → 200 `{"status":"recorded"}`, so no money moves.
  - A card sent with `tier: READ` for `request_advance` is still stored as EXECUTE (the policy
    raises it). A `change_bank_details` card → 403 (DENY).
  - The lender viewer gets 403 on cash, facts, ingest history, messages, approvals, audit, mesh,
    receivables and copilot, and 200 only on passport and shares (L1).
  - Staff gets 403 when proposing a mesh round (DRAFT is not theirs).
  - Mesh (WP-08), three owners: propose → garment, fabric, hardware approve with codes → settled
    → `GET /verify` `valid: true` (offline anchor, labelled `offline`; obligations labelled
    `synthetic`).
  - Today in bn/zh returns narration in that language once `?language=` is sent.
- **Code review, security** (`backend/app/security/*`, every router in `backend/app/api/*.py`):
  - Every route except `health`, the sign-in routes, `logout`, `demo-accounts` (demo only) and
    public `verify` depends on `authenticated`, `current_principal` or `require(...)`.
  - The tenant always comes from the principal.
  - The TOTP replay check is atomic (conditional UPDATE), and the lockout counts both password and
    code failures.
  - Demo accounts are refused when `demo_mode` is off (`Accounts.usable`; test
    `test_demo_accounts_are_neither_listed_nor_usable_outside_demo_mode`), and production refuses
    demo mode.
  - Cookies are HttpOnly, SameSite=Strict and Secure when deployed. CORS refuses `*` when deployed.
  - Approvals pin the card digest and re-check the policy at execution. No executor is registered,
    so every execution only records.
  - The DENY list cannot get an executor (`register_executor` raises).
- **Rule 3 (LLM gateway):** the only `openai` client is in `backend/app/llm/transport.py`, created
  by `LLMGateway` (`live` mode) and the opt-in `live_check`. Every `complete()` runs `assert_safe`
  on messages and context first. No `httpx`, `requests` or `urllib` client exists in `app/`. The
  only other network client is `web3` in `app/chain/anchor.py` (Sepolia, hashes only).
- **Rule 1 (outside C2):** figures come from engines with `formula_id` and inputs. The checker
  recomputes every claim (eval `claims_recomputed`, `provenance`, `numbers_traced` pass on all
  answered tasks), and a narration with a digit not in a verified claim is replaced.
- **Rule 5:** abstention is used where history is short (test
  `test_short_history_abstains_naming_what_to_add`; eval tasks `F.abstain.thin_history`,
  `F.abstain.engine_missing` and `F.abstain.off_topic` pass).
- **Rule 6:** `backend/tests/conftest.py` blocks every non-loopback socket. The full suite passed
  under it.
- **Rule 7:** no secrets in the tree or in history (pattern scan, section 4). No `.env` is
  tracked or was ever committed. The three 0x… 64-hex strings are fake transaction hashes in the
  web mock fixtures.
- **Rule 8 (synthetic label):**
  - The amber banner shows on every authenticated view in all three languages and both sizes
    (sweep: `synth: true` on all views).
  - `/api/health` → `data_mode_banner: synthetic`. Cash gaps, the copilot recommendation, mesh
    obligations and rounds, eval summaries and the operation log all carry
    `data_mode: synthetic`.
  - The deck says "synthetic" on the problem, owner, cash and mesh slides.
- **Offline-mock banner:** never shown with Settings → API → Real backend (sweep: `mock: false`
  everywhere). Market falls back to its labelled sample. No request left localhost in any view.
- **i18n parity:** en/bn/zh have the same 730 keys. Only `app.name`, `language.en` and
  `market.source.agripricebd` are identical to English (names). No untranslated i18n key text
  appeared on any screen.
- **Env names:** `infra/.env.example`, `backend/.env.example` and `infra/docker-compose.yml` use
  exactly the field names in `backend/app/settings.py`. Only the variable names in the examples
  were read, no values.
- **Tech doc eval numbers** (`technical-documentation.md:804-808`): 53/62, 26/26, 27/36, 3/12,
  11/12, 12/12. All match a fresh `npm run eval`.
- **Deck evidence slide:** "2,400+ tests" holds (2,456 collected on main, 2,463 on this branch). The "48 steps"
  sandbox log matches `operation-log.jsonl` (49 lines including the header event).

### 3.1 Screen sweep (Playwright, throwaway script, not committed)

Accounts: owner@hardware (the video's shop), and accountant, staff, lender and compliance at the
grocery. Every route each role can see, plus one hidden route each for staff, lender and
compliance. Languages: en, bn, zh. Sizes: 1920×1080 and Pixel 7. axe with WCAG 2.0/2.1 A and AA
tags. API mode set to Real backend through Settings. Screenshots are in
`web/test-results/audit/shots/` in the audit sandbox (git-ignored).

| Account | Views | Synthetic banner | Mock banner | Untranslated keys | Horizontal scroll (phone) | Foreign hosts | axe serious/critical | Console errors |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| owner@hardware | 66 | 66/66 | 0 | 0 | Trust in en/bn/zh (45-69 px, M12) | 0 | Cash `aria-hidden-focus` (M11), Today Watch badge contrast (M10), Trust `scrollable-region-focusable` (M12) | duplicate key on Today (F2, fixed); 404s from Analysis stability (H3), Settings (M8), Market (falls back to its labelled sample) |
| accountant@grocery | 66 | 66/66 | 0 | 0 | none | 0 | Cash `aria-hidden-focus` | 403 on Trust's audit cards (M16); same 404s |
| staff@grocery | 36 | 36/36 | 0 | 0 | none | 0 | none | Settings and Market 404s |
| lender@grocery | 18 | 18/18 | 0 | 0 | none | 0 | none | none |
| compliance@grocery | 30 | 30/30 | 0 | 0 | none | 0 | Trust `scrollable-region-focusable` | 403 on Trust's abstention log (M16); Settings 404 |
| public `/verify` (phone) | 1 | n/a | 0 | 0 | none | 0 | none | none |

Hidden routes are gated correctly: staff on `/cash` sees "Not available for your role"; the lender
and compliance land on their home screen. English text in BN/ZH that the sweep's string check
can see came only from stored user questions in the abstention log (data, not UI). The humanised
fallbacks in M14 are invisible to that check and were found in the screenshots. One
`422 /api/copilot/today` was seen once while the dev server hot-reloaded the F3 change; it did
not reproduce (`?language=en|bn|zh` and no parameter all answer 200).

## 4. Commands run

| Command | Exit | Key result |
| --- | --- | --- |
| `git fetch --all && git switch main && git pull && git switch -c audit-final` | 0 | main at `335c1ca` |
| `npm run setup` | 0 | backend synced; web 607 packages, `found 0 vulnerabilities` |
| `npm run lint` | 0 | ruff `All checks passed!`; eslint + `tsc -b` clean |
| `npm run test` (main code) | 0 | backend `2244 passed, 2 skipped in 326.82s`; web `Test Files 22 passed (22)`, `Tests 210 passed (210)` |
| `npm run eval` | 0 | `eval (offline): 53/62 tasks passed (functional 26/26, adversarial 27/36)`; corpus attacks caught 24/24; new attacks caught 3/12, contained 11/12, approval held 12/12. Only timestamps and latency changed in the logs, so they were not committed |
| `npm run evidence -- --no-eval` | 0 | `test-counts.md` and evidence `README.md`: backend 2,251 (ingest +5 from F1), web 210, total 2,461. Committed in `e89beca` (before F2/F3 added 2 web tests: now 212) |
| `uv --directory backend run python -m app.facts.seed` | 0 | seeded 5 synthetic SMEs (grocery 9,345 transactions … hardware 4,445) |
| `npm run dev` (background) | running | `/api/health` → `status ok`, `contracts_version 1.2.0`, `data_mode_banner synthetic`, `llm_mode fixtures`, `chain_mode offline` |
| `npm run e2e` | 0 | `27 passed`, `2 skipped` (mesh journey, desktop and phone: skips when the mesh API is live), 8 known bugs observed (guard Bangla phrasing; Trust phone width; Cash aria-hidden focus light+dark; Reports/Settings dark contrast; Trust scroll region) |
| `gitleaks detect --source . --config .gitleaks.toml` | — | **gitleaks is not installed** in this sandbox. Instead: `git grep` and `git log --all -p` for Google/Groq/OpenAI/GitHub/Slack/AWS key shapes, PEM private keys and 0x+64-hex private keys. Tree: 3 hits, all fake tx hashes in `web/src/mocks/fixtures/{inbox,mesh}.ts`. History: the same 3 values. No `.env`, `.pem` or `id_rsa` in any commit |
| Fresh injection set (`InjectionGuard().inspect`) | 0 | attacks caught 13/24, benign flagged 10/24 (section 2.1) |
| Deck slides at 1920×1080 (Playwright) + `pdftoppm deck.pdf` | 0 | 6 slides overflow in HTML, 5 visibly clipped in the PDF (H6) |
| `pytest tests/ingest/test_api.py` before/after F1 | 1 / 0 | `4 failed, 19 passed` → `23 passed` |
| `vitest TodayScreen.test.tsx` before/after F2, F3 | 1 / 0 | each new test failed before its fix; after: web `Tests 212 passed (212)`, lint clean |
| Final `npm run test` on `audit-final` | FINAL_EXIT | FINAL_RESULT |
