# Nobo — your instructions

You are the lead. You run **three Claude Code sessions on your two PCs**, hold the GitHub repo
and its secrets, and do registration, China checks, deck narration and submission.
The orchestrator (the cloud chat) plans, reviews and merges. Full detail: `docs/RUNBOOK.md`.

## Your machines

| PC | Folder | Session | Account | Queue |
| --- | --- | --- | --- | --- |
| PC-1 (`knight-27`) | `C:\hishab\repo` | A1 | A | WP-01 → 02 → 04 → 05 → 07 (→ 09, 12 if Worker C isn't used) |
| PC-2 | `C:\hishab\repo` | B1 | B | WP-14 → 15 |
| PC-2 | `C:\hishab\repo-b2` | B2 | B | WP-03 → 11 → 10 → 16 |

Each session needs **two PowerShell windows**: one running `claude`, one running autosave.
So PC-2 has four windows open.

## Saturday (now → midnight)

- [ ] Email registration form + all 3 passport pages to wangyr@pbcsf.tsinghua.edu.cn
- [ ] Email the on-chain bonus question (same address)
- [ ] Give the orchestrator your GitHub username; approve its repo-access prompt
- [x] Approve or cut P1–P14 — done: all IN except P10 (CUT)
- [ ] Add Amdad and Labib as repo collaborators
- [ ] **quadbits.net, step 0 (RUNBOOK §5.9):** Namecheap → Domain List → expiry after 30 Nov
      (else Auto-Renew) · Manage → Domain tab → Nameservers says **Namecheap BasicDNS**? ·
      GreatFire "not blocked" · `nslookup hishab.quadbits.net` = "Non-existent domain"
- [ ] **When Amdad sends the server IP — step 1:** Namecheap → Manage → **Advanced DNS** → Add New
      Record → **A Record** · Host `hishab` · Value = IP · TTL Automatic → green ✓
      (add a CAA record only if CAA records already exist)
- [ ] **Step 2:** `nslookup hishab.quadbits.net 8.8.8.8` shows the IP → post "DNS ready" → add GitHub
      secret `DEPLOY_DOMAIN` = `hishab.quadbits.net`
- [ ] Set up PC-1 and PC-2 (RUNBOOK §3), including the second folder `repo-b2` on PC-2
- [ ] Log PC-1 into account A and PC-2 into account B (`claude` → browser login → `/status`)
- [ ] When Amdad gives you the API keys (in person/phone): copy `backend\.env.example` to
      `backend\.env` in all three folders and paste the keys; add them as GitHub Actions secrets
- [ ] When the orchestrator posts "WP-00 merged": start **A1 with WP-01** (RUNBOOK §4)
- [ ] About 2.5 h after A1 starts: start **B2 with WP-03**, then **B1 with WP-14**

## Every session, every time

1. `cd` into the session's folder → `git switch main` → `git pull` → `git switch -c <branch from WP file>`
2. Second window: `powershell -ExecutionPolicy Bypass -File scripts\autosave.ps1`
3. `claude` → paste the start prompt (RUNBOOK §4, change the WP number)
4. Approve commands that stay inside the repo
5. Done → `Open the pull request for this branch.` → post "WP-xx PR ready" in the group
6. After "merged": `/clear`, Ctrl+C autosave, next WP

## Sunday – Tuesday

- Keep all three sessions fed; when an account hits its limit, post the reset time and use the
  break for review, QA or rest.
- Add GitHub secrets when Amdad (server) and Labib (wallet) hand you the values.
- **After "deployed":** open `https://hishab.quadbits.net` and check the padlock (§5.9 step 3).
- **Mon 16:00:** China checks (RUNBOOK §5.6) — 17CE, BOCE, ITDog, GreatFire; post screenshots.
- **Mon 21:00:** send the insurance submission (PLAN §9).
- **Mon night / Tue:** record narration for the video; rehearse the deck (≤ 10 min).
- **Tue 14:00:** code freeze. **Tue 18:30:** make the repo public after the orchestrator's secret scan.
- **Tue 19:00:** send the final submission.

## Sleep
Sun 05:00–09:00 · Mon 05:00–09:00 · Tue 02:00–04:00 (RUNBOOK §6).
