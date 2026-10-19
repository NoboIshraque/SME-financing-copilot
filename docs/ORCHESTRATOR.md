# Orchestrator baton

DecisionGuard has more than one orchestrator session (one per Claude account). They cannot see
each other's chats, so **this file is how they talk**. The repo is the only shared memory.
Nothing important may live only inside a session's sandbox.

Accounts: **A** = PC-1 account, **B** = PC-2 account (B1/B2 coding sessions; avoid
orchestrating here, it eats the WP-14/WP-11 budget), **C** = third account.
Session names: `orch-A`, `orch-C` (`orch-B` only in an emergency).

---

## Baton (edit this block on every take-over and handover)

| Field | Value |
| --- | --- |
| On duty | orch-C |
| Since (Dhaka) | 2026-10-19 10:55 |
| Merge authority | the on-duty orchestrator only |
| Working on | handover 20 Oct ~01:00: everything merged or cut; WP-19 final pass merged; renamed DecisionGuard |
| Next 3 steps | 1. Nobo records the video and republishes the deck (NOW.md). 2. Amdad's server, then the hosted E2E and `CHAIN_MODE=sepolia`. 3. Labib's notebook 01 on Kaggle (datasets blocked from the cloud). |
| Open PRs and their state | none |
| Waiting on (people / CI / limits) | Nobo (video, deck, sending), Amdad (server), Labib (notebook 01) |
| Lives only in a sandbox (must be committed) | nothing (orch-A's CPU runner is on main since af37713) |
| Off-duty orchestrator | orch-A (limit reset time not recorded) |

---

## Rules

1. **One driver.** Only the on-duty orchestrator merges PRs, edits `docs/NOW.md`, and edits
   PLAN §8. A second orchestrator running at the same time is a *helper*: it works only on
   tasks it has claimed in `docs/CLAIMS.md`, on its own branch, and opens PRs. It never merges.
2. **Claim before work.** Add a row to `docs/CLAIMS.md`, commit, push. If the push is
   rejected, `git pull --rebase` and re-check: someone may have claimed it first. Git is the lock.
3. **Pull before every decision.** `git fetch --all && git pull` before reading status or
   choosing a task.
4. **Nothing sandbox-only.** Metrics, helper scripts, notes: commit them (scripts to
   `scripts/`, notes to this file or the WP file). Sandboxes vanish.
5. **Do not start PC-2 work packages** (WP-14, WP-15, WP-11, WP-10, WP-16). Nobo starts those.
6. **Secrets:** never read, print, or commit `.env` or any key. Never enter credentials.
7. All CLAUDE.md rules apply.

## Taking the baton ("take the baton")

1. Pull. Read `CLAUDE.md`, this file, `docs/CLAIMS.md`, `docs/NOW.md`, PLAN §8, open PRs.
2. Fill the Baton block with your name and the time; move the previous driver to
   "Off-duty orchestrator".
3. Recreate anything listed under "Lives only in a sandbox" that you need, or note that it
   is still stuck in the other session.
4. Commit `orchestrator: orch-X takes the baton`, push.
5. Tell Nobo the state in five lines and your next step.

## Handing over ("write handover")

Do this when Nobo says "write handover", when you are warned you are close to the usage
limit, or before stopping for any reason.

1. Commit and push every work-in-progress branch (WIP commits are fine).
2. Commit anything that lives only in your sandbox.
3. Update the Baton block: working on, next 3 steps, open PRs with state, waiting-on,
   when your limit resets.
4. Update `docs/NOW.md` and PLAN §8 if they are stale.
5. Release finished claims in `docs/CLAIMS.md`; mark unfinished ones `paused`.
6. Append one line to the Session log below.
7. Commit `orchestrator: orch-X handover`, push, and confirm the push succeeded.

## Session log (append only, newest last)

| When (Dhaka) | Session | What happened | Handover commit |
| --- | --- | --- | --- |
| 2026-10-18 06:10 | orch-A | Wrote HANDOVER_2 (see docs/HANDOVER.md); hit usage limit later | — |
| 2026-10-20 01:00 | orch-C | Merged #17–#36 (WP-04/05/06/07/08/10/12/13/14/16, demo fixes, cuts); renamed to DecisionGuard; WP-19 final pass (docs, evidence, PDFs) | wp-19-submission |
