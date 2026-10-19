# Claims

Who is working on what, so two sessions never do the same task. Protocol is in
`docs/ORCHESTRATOR.md`. Applies to orchestrator sessions; coding sessions (A1, B1, B2) are
already separated by their WP branches and owned paths.

## How to claim

1. `git pull`.
2. Check the table. If the task is already `active`, pick something else.
3. Add your row, commit `claims: orch-X claims <task>`, push.
4. Push rejected? `git pull --rebase`, check again, then push.
5. When done, set status to `done` with the PR or commit. If you stop early, set `paused`.

**Stale rule:** an `active` claim with no commit on its branch for 90 minutes may be taken
over. Set the old row to `taken over by orch-X` and add your own row.

## Table

| Task | Session | Branch | Status | Since (Dhaka) | Result (PR / commit) |
| --- | --- | --- | --- | --- | --- |
| example: finish WP-03 PR #9 | orch-A | wp-03-privacy | done | 2026-10-18 06:00 | #9 |
| WP-11 question for WP-01/WP-02: facts + ingest APIs use the signed-in principal (stubs gave anonymous callers a lender view; demo owners could not commit) | orch-A | wp-01-principal | done (merged by orch-C) | 2026-10-19 06:15 | #17 |
| WP-11 question for WP-00: `/api/docs` (Swagger from a CDN) off outside development | orch-A | wp-00-docs-off | done (merged by orch-C) | 2026-10-19 06:15 | #18 |
| WP-06 milestone 8: financing API on the WP-11 principal + step-up | orch-C | wp-06-api | done (merged) | 2026-10-19 11:10 | #20 |
| Integration: web ↔ live APIs (cash `/gaps` shape; WP-06 financing match/lender shapes, purpose keys, APR figure label) | orch-C | orch-web-integration | done (merged) | 2026-10-19 12:00 | #22 |
| Option A for the application tier: `submit_loan_application` (contract 1.2.0 + WP-11 policy + WP-06 card) | orch-C | orch-submit-application | done (merged) | 2026-10-19 12:20 | #23 |
| WP-19 drafts for the Mon 21:00 insurance submission: technical doc, README, security self-assessment final, video script, evidence bundle, deck, claims check (not the sending: Nobo sends) | orch-A | wp-19-submission | active | 2026-10-19 15:55 | — |
| WP-08 milestone 8: mesh API (obligations, propose, approve with step-up, verify) | orch-C | wp-08-api | active | 2026-10-19 13:15 | — |
| Record the scope cuts Nobo approved 19 Oct 22:19 (WP-05/09/12/13/15/16/17/18 shortened or cut; WP-10 kept whole) in WP files + FEATURES.md; real-data substitute in WP-20.md | orch-A | docs-scope-cuts | done (PR open; orch-C merges) | 2026-10-19 22:30 | #25 |
