# Hishab: security self-assessment (draft)

Deliverable 05 · FinTechathon 2026, Topic E · Draft by WP-11, 18 Oct 2026. The orchestrator
finalises it in WP-19. Every control below names the code that implements it and the tests that
check it. The known-risk list at the end is deliberately blunt.

**Status at this draft.** WP-11 is implemented on branch `wp-11-security`, with 400 automated
tests in `backend/tests/security/` (the whole backend suite, 1,463 tests, passes with the
security layer installed in every app). WP-03 (privacy) is merged. WP-10 (LLM gateway and
agents) and WP-16 (adversarial evaluation) are not built yet, so controls that live there are
marked *planned*. The web hardening is installed app-wide through `app/security/app_hooks.py`,
which `create_app` calls for every app.

---

## 1. Permission tiers

Every action an agent or a person can take has a tier. Two rules apply in this order.

1. **What the action needs.** `READ` to look. `DRAFT` to prepare something that stays inside
   Hishab. `EXECUTE` for anything that leaves Hishab: a message, a payment, or data shared with
   a lender. `DENY` for things nobody may do through Hishab.
2. **How far a role may take it.** A role that holds less than the action needs may still
   suggest or draft it for someone who holds more.

**EXECUTE always means four things.** An owner approved this exact action card. They confirmed
with a fresh TOTP code. The approval is less than 24 hours old. The policy still allows the
action at the moment it runs. An action card's own `tier` can raise the requirement but never
lower it, so a card written by a language model cannot talk its way down a tier.

Source: `backend/app/security/policy.py` (the only place tiers are decided). The table below
is generated from that file. `tests/security/test_policy.py` checks every role × action cell
against an independently written copy.

| Action | Needs | owner | accountant | staff | lender_viewer | compliance |
| --- | --- | --- | --- | --- | --- | --- |
| `view` | READ | READ | READ | READ | READ | READ |
| `record_dispute` | DRAFT | DRAFT | DRAFT | DRAFT | DENY | DENY |
| `draft_loan_application` | DRAFT | DRAFT | DRAFT | DENY | DENY | DENY |
| `propose_netting_round` | DRAFT | DRAFT | DRAFT | DENY | DENY | DENY |
| `send_reminder` | EXECUTE | EXECUTE | DRAFT | DRAFT | DENY | DENY |
| `send_message` | EXECUTE | EXECUTE | DRAFT | DRAFT | DENY | DENY |
| `retime_payable` | EXECUTE | EXECUTE | DRAFT | SUGGEST | DENY | DENY |
| `request_advance` | EXECUTE | EXECUTE | DRAFT | DENY | DENY | DENY |
| `offer_early_pay_discount` | EXECUTE | EXECUTE | DRAFT | SUGGEST | DENY | DENY |
| `approve_netting_round` | EXECUTE | EXECUTE | SUGGEST | DENY | DENY | DENY |
| `share_passport` | EXECUTE | EXECUTE | DRAFT | DENY | DENY | DENY |
| `set_credit_limit` | EXECUTE | EXECUTE | DRAFT | SUGGEST | DENY | DENY |
| `move_money` | EXECUTE | EXECUTE | DRAFT | DENY | DENY | DENY |
| `change_bank_details` | DENY | DENY | DENY | DENY | DENY | DENY |
| `add_payee` | DENY | DENY | DENY | DENY | DENY | DENY |
| `disable_audit` | DENY | DENY | DENY | DENY | DENY | DENY |
| `export_raw_pii` | DENY | DENY | DENY | DENY | DENY | DENY |

**DENY list.** The four DENY rows are refused for everyone, including the owner. A request for
one is refused before an approval exists, and the attempt is written to the audit chain. No
executor can be registered for a DENY action (`register_executor` raises).

**Approvals** (`backend/app/security/approvals.py`; `tests/security/test_approvals.py`):

- Requests and executions carry an idempotency key (`X-Idempotency-Key`). Repeating either
  with the same key returns the first result and runs the executor once. Reusing a key for a
  different card is refused (409).
- The approved card is stored with its SHA-256. If the stored card changes afterwards, it is
  not executed.
- At execution, the approval is checked again. Execution is refused if the policy changed, if
  the approver is no longer an active owner, or if the 24 hours have passed.
- **Money never moves without a human.** No executor in the codebase moves money. By default an
  executed action is only recorded. Other work packages may register real executors, and every
  one of them still sits behind the approval gate above.

### Roles and what each may see

Source: `backend/app/security/roles.py`. Tests: `tests/security/test_roles.py` covers the
full role × permission matrix.

| Permission | owner | accountant | staff | lender_viewer | compliance |
| --- | --- | --- | --- | --- | --- |
| `ledger:read` | yes | yes | yes | no | yes |
| `source_rows:read` (unmasked provenance rows) | yes | yes | no | no | yes |
| `ingest:upload` | yes | yes | yes | no | no |
| `copilot:ask` | yes | yes | yes | no | no |
| `reports:read` | yes | yes | no | if consented | yes |
| `passport:read` | yes | yes | no | if consented | yes |
| `approvals:request` | yes | yes | yes | no | no |
| `approvals:decide` | yes | no | no | no | no |
| `audit:read`, `audit:verify` | yes | no | no | no | yes |
| `team:manage`, `lender_access:grant` | yes | no | no | no | no |

**Lender viewers** exist only through an owner's recorded consent. The consent names the
lender, the purpose and the scopes (at most `passport:read` and `reports:read`). Access lasts
at most 30 days. Creating it needs a fresh TOTP code, and the owner can revoke it at any time.
Revoking deactivates the account and ends its sessions at once. Every query is limited to the
caller's own tenant, and other tenants' records answer 404.

## 2. Authentication and sessions

Source: `backend/app/security/{passwords,totp,sessions,lockout,accounts}.py`, `app/api/auth.py`.
Tests: `test_passwords.py`, `test_totp.py`, `test_sessions.py`, `test_lockout.py`,
`test_auth_api.py`.

- **Passwords.** argon2id with the RFC 9106 low-memory profile (t=3, m=64 MiB, p=4), above the
  OWASP minimum. Older hashes are upgraded at the next sign-in. Policy: 12–128 characters, a
  deny list of common passwords, and the password may not equal the email.
- **Second factor.** RFC 6238 TOTP with one 30-second step of drift. A code is accepted once:
  an atomic conditional UPDATE blocks replays, even under concurrent requests. Codes typed in
  Bangla digits are accepted. TOTP secrets are stored sealed with AES-256-GCM, bound to the
  user, under a key derived with HKDF.
- **Step-up.** Every EXECUTE approval, every new team member and every lender grant needs a
  fresh code in `X-Step-Up-Code`. Wrong codes count towards the lockout.
- **Sessions.** The session lives server-side. The cookie is HttpOnly, SameSite=Strict, scoped
  to `/api`, and marked Secure when deployed. The database stores only the SHA-256 of the
  token. A session ends after 30 idle minutes or 12 hours. Every sign-in issues a fresh token,
  so session fixation does not work. Logout, a password change or deactivation revokes
  sessions on the server.
- **Lockout.** Five failures (password or TOTP) in 15 minutes lock the account for 15 minutes.
  Unknown emails behave identically and cost the same argon2 work, so neither the response nor
  its timing reveals whether an account exists.
- **Demo accounts** (one per role, plus an owner per synthetic SME) exist only in demo mode.
  They are refused at sign-in otherwise, and production refuses demo mode altogether.

## 3. Audit chain

Source: `backend/app/security/audit.py`, `jobs.py`. Tests: `test_audit.py`.

- **Chain.** Each tenant has an append-only chain of SHA-256 links. Each hash covers the
  sequence number, tenant, time, actor, action, tier, target, details digest and the previous
  hash.
- **Append-only.** The ORM refuses UPDATE and DELETE on audit rows. Database triggers refuse
  them too: on SQLite, and on PostgreSQL (TRUNCATE as well).
- **Verification.** `GET /api/audit/verify` recomputes every link and finds the first bad row.
  The tests tamper as an attacker who dropped the triggers would: edited fields, deleted rows,
  reordered rows, and a forged row with a recomputed hash. All four are detected.
- **Daily anchor.** The worker job `security.anchor_audit_heads` commits all chain heads to one
  digest. That digest is anchored on Ethereum Sepolia through WP-08's `app.chain.anchor`
  (hashes only). Verification then also catches history cut off after an anchor.
- **What gets logged.** Sign-ins and failures, lockouts, step-up failures, team and lender
  changes, every approval step, refused DENY requests, and guard quarantines. Details hold ids,
  counts and digests, never names, emails, phone numbers or message text.

## 4. Prompt-injection guard

Source: `backend/app/security/guard.py`, `guard_rules.py`. Tests: `test_guard.py`.

- **Where it runs.** On every user message, uploaded text and tool output, before any model
  sees it. Wiring it into the LLM path is WP-10's gateway job, which is *planned*. The guard
  itself and its HTTP endpoint are implemented.
- **Rules layer.** English, Bangla, Banglish and Chinese rules run on normalised text (NFKC,
  case folding, zero-width and bidi controls removed, look-alike letters folded, Bangla digits
  read as ASCII). Spaced-out spellings are matched as well. The rules target Hishab's own
  invariants: approvals, step-up, payees, bank details, the audit log, the token vault, secrets
  and invented numbers.
- **Measured result.** On WP-17's 192-row corpus, the guard catches 96/96 attacks and flags
  0/96 benign texts. The benign texts include hard negatives such as "ignore the disputed
  invoice" and "how do I update my own bank details". Obfuscated variants are caught too:
  zero-width spaces, full-width letters, Cyrillic look-alikes and spaced letters.
  **Caveat:** the rules were written after seeing the corpus. These numbers show the guard has
  not regressed on known attacks. They do not show it will catch paraphrases it has never seen.
  WP-16's adversarial paraphrase suite will measure that.
- **Classifier.** WP-17's classifier plugs into a defined slot (ONNX + tokenizer). The CPU
  baseline separates attacks from benign text only weakly on unseen families (AUC 0.69,
  `ml/artifacts/injection_metrics_cpu_baseline.json`), so it is not deployed. The guard runs
  rules-only for now, and every verdict reports `classifier: null`.
- **On a hit.** The text is quarantined on the server for the owner to review or release, and
  the audit chain records only its SHA-256.

## 5. Privacy (WP-03, merged)

Only anonymised payloads may leave the server. Personal data is replaced by HMAC tokens, and
the originals are kept AES-256-GCM encrypted in a vault. A fail-closed gate
(`app.privacy.assert_safe`) refuses any payload where a detector fires. Its error names only
the kinds of data found and how many, never the values. WP-10's gateway must call it on every
request (*planned*). Source rows in explanations are masked for roles without
`source_rows:read`.

## 6. Web hardening

Source: `backend/app/security/web.py`, plus `infra/Caddyfile` (WP-18). Tests: `test_web.py`.

- **Headers.** Strict CSP (`default-src 'none'` on API responses), HSTS, `nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, a permissions policy, COOP/CORP,
  and `Cache-Control: no-store` on API data.
- **CORS.** An explicit origin list with credentials; CORS is the outermost layer, so even
  a 429 or 403 from the security middleware carries CORS headers. Wildcard origins are refused when
  deployed, and a foreign-origin preflight is rejected (tested).
- **CSRF.** SameSite=Strict cookies, plus an Origin check that refuses cross-site requests that
  change state.
- **Rate limits.** Token buckets per client IP and route group. Sign-in is the tightest at 10
  per minute; copilot is 20, guard 60, and everything else 300. Over the limit, the API answers
  429 with `Retry-After`.

## 7. Threat model (STRIDE)

| Threat | Example against Hishab | Mitigation | Residual risk |
| --- | --- | --- | --- |
| **S**poofing | Stolen password; someone claiming to be the owner in chat; replayed TOTP code | argon2id; TOTP for owners; single-use TOTP steps; lockout; "fake owner" guard rules; approvals need a fresh code, not a chat claim | A phished password **and** a live TOTP code still get through, since there is no phishing-resistant factor (WebAuthn) |
| **T**ampering | Editing a stored action card after approval; rewriting the audit log; changing a supplier's bank details | Card digest checked at execution; hash chain with triggers and a daily anchor; `change_bank_details` is DENY | A database administrator can rewrite history consistently after the last anchor (window up to 24 h) |
| **R**epudiation | Owner denies approving a payment | Audit event with approver id, step-up flag and time, hash-chained and anchored | The audit log is per tenant and not countersigned by the user's device |
| **I**nformation disclosure | Model provider sees customer names; lender sees more than consented; session theft | Anonymiser plus fail-closed gate (WP-03); scoped, expiring lender access; HttpOnly/Strict cookies; tenant isolation (404 across tenants); no-store; masked source rows | Free-tier providers may train on the anonymised text; the quarantine keeps raw text server-side |
| **D**enial of service | Password spraying; flooding the copilot to burn the free LLM quota; locking the owner out | Rate limits; lockout that attempts do not extend; per-route budgets; WP-10 tool budget (*planned*) | In-memory limits are per process; an attacker who knows the owner's email can lock them out for 15 minutes |
| **E**levation of privilege | The model emits a card with tier READ for `move_money`; staff calls the approve endpoint; prompt injection in an uploaded statement | Policy tier overrides the card's tier; `approvals:decide` plus EXECUTE tier plus step-up; DENY list; injection guard on uploads and tool output | Guard generalisation is not yet measured (WP-16) |

## 8. OWASP Top 10 for LLM Applications (2025)

| Risk | How Hishab addresses it | Status |
| --- | --- | --- |
| LLM01 Prompt Injection | Multilingual guard on user, upload and tool text; quarantine plus audit; tiers mean an injected instruction still needs an owner's TOTP to have any effect | Guard implemented; WP-10 wiring planned |
| LLM02 Sensitive Information Disclosure | Only anonymised payloads leave (WP-03 gate, fail closed); vault encrypted; lender scopes; masked source rows | Implemented (gateway call planned in WP-10) |
| LLM03 Supply Chain | Pinned dependencies in `uv.lock` and the npm lockfile; pip-audit, npm audit and gitleaks in CI (WP-00/18); no third-party CDN in the web app | Implemented in CI; the API docs page still loads Swagger UI from jsdelivr (see risks) |
| LLM04 Data and Model Poisoning | No model is trained on user data; the injection classifier trains only on public and synthetic data (WP-17); ingested data is typed facts, not instructions | By design |
| LLM05 Improper Output Handling | The model never produces numbers shown to users: engines compute, and a checker recomputes every claim (WP-10); action cards are re-tiered by policy; output is not executed as code | Policy implemented; checker planned (WP-10) |
| LLM06 Excessive Agency | Permission tiers; DENY list; EXECUTE needs owner plus fresh TOTP plus a re-check at run time; no executor moves money | Implemented |
| LLM07 System Prompt Leakage | No secrets in prompts; keys live only in the server environment; guard rules for secret and system-prompt requests | Guard implemented; prompts in WP-10 |
| LLM08 Vector and Embedding Weaknesses | No vector store or RAG over user data in the current design | Not applicable |
| LLM09 Misinformation | Code computes and the model narrates; claims checked symbolically; multi-model agreement and abstention when unsure (WP-10); `fake_numbers` guard rules | Guard implemented; checker and abstention planned |
| LLM10 Unbounded Consumption | Rate limits per route (copilot 20/min); tool budget per run and per-provider usage counters (WP-10) | Rate limits implemented; budgets planned |

## 9. Known-risk list

1. **The fact API still uses a development stub for the caller** (`app/api/facts.py`,
   WP-01) until it switches to the authenticated principal; outside development and test, that
   stub only ever grants masked, lender-level access.
2. **Rate limits live in process memory.** They reset on restart and are per process. The
   demo runs one API process; scaling out would need a shared store.
3. **Guard generalisation is unmeasured.** The rules were written with sight of the corpus they
   are tested on, so 96/96 measures regressions only. The ML classifier is not deployed
   because the CPU baseline AUC on unseen families is 0.69.
4. **Owner lockout as denial of service.** Anyone who knows the owner's email can lock the
   account for 15 minutes. Locks are not extended by further attempts, and per-IP limits slow
   this down.
5. **Demo mode publishes credentials.** Demo passwords and each owner's current TOTP code are
   shown on purpose, so judges can sign in, and only on synthetic tenants. Production refuses
   demo mode (`Settings` validator), and demo accounts are refused at sign-in outside demo mode.
6. **Audit window between anchors.** Someone with full database access could drop the triggers
   and consistently rewrite events written since the last daily anchor. In offline chain mode
   (development and tests), anchors are not independent evidence.
7. **One key protects sessions and TOTP.** TOTP secrets are encrypted under a key derived from
   `SECRET_KEY`. Leaking both `SECRET_KEY` and the database exposes them.
8. **No phishing-resistant second factor** (WebAuthn), **no TOTP recovery codes**, and **no
   self-service password reset.** An operator resets these by hand.
9. **Lender access limits.** A lender email can hold access to only one SME. The one-time
   initial password is shown to the owner, who passes it on; the lender should change it.
10. **API docs** (`/api/docs`) load Swagger UI from a third-party CDN under a relaxed CSP. That
    CDN may be blocked in China. Recommendation: disable the docs in production.
11. **Free-tier LLM providers** may use inputs to improve their models. Only anonymised text
    leaves, and the optional paid tier during judging avoids this (PLAN §6).
12. **Controls that live in WP-10** (gateway privacy call, checker, critic, abstention, tool
    budget) are designed but not yet built at the time of this draft. Their tests will be added
    with WP-10.
