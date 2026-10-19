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
