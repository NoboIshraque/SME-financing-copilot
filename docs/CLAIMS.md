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
| WP-06 milestone 8: financing API on the WP-11 principal + step-up | orch-C | wp-06-api | active | 2026-10-19 11:10 | — |
