# Amdad — your instructions

You own **keys, hosting and quality checks**, and optionally run a free coding agent (Worker C)
on your PC-3. You don't use Claude accounts. Full detail: `docs/RUNBOOK.md`.

## Saturday (now → midnight)

### 1. API keys (15 min)
- [ ] aistudio.google.com → **Get API key** → Create key. Screenshot the free rate limits.
- [ ] console.groq.com → **API Keys** → Create (no card).
- [ ] Give both keys to Nobo **in person or by phone call** — never in group chat or a file.

### 2. Hosting server (30 min, needs a payment card)
- [ ] Tencent Cloud International → **Lighthouse** → **Singapore** → Ubuntu 22.04 (Docker image)
      → 2 vCPU / 4 GB. Firewall: open ports 22, 80, 443.
      If the card or signup fails: Oracle Cloud Always Free → Singapore → Ampere A1, Ubuntu.
- [ ] No domain to buy: the app lives at **`hishab.quadbits.net`** (Nobo's domain on Namecheap).
      As soon as the server exists, send Nobo its **public IPv4 address**; he adds the DNS record
      (RUNBOOK §5.9).
- [ ] Check Docker is on the server (web terminal): `docker --version` and `docker compose version`.
      If either is missing: `curl -fsSL https://get.docker.com | sudo sh` then
      `sudo usermod -aG docker ubuntu` and log out/in.
      Keep ports **80 and 443** open: the server needs them to get its free HTTPS certificate.
- [ ] On your PC: `ssh-keygen -t ed25519 -f $HOME\.ssh\hishab_deploy`
- [ ] Put the text of `hishab_deploy.pub` into the server's `~/.ssh/authorized_keys`
      (the Lighthouse console has a web terminal).
- [ ] Give Nobo in person: server IP, user (`ubuntu`), the private key file's text.
- [ ] Post "server ready" in the group.

### 3. Set up PC-3 (20 min)
- [ ] RUNBOOK §3 (skip the Claude install).
- [ ] `cd C:\hishab\repo` → `npm run setup` (after "WP-00 merged").

### 4. Optional Worker C (free Google coding CLI)
- [ ] `npm install -g @google/gemini-cli`, then run `gemini` in `C:\hishab\repo` and sign in with
      **your own** Google account. If it tells you free accounts moved to Antigravity CLI, install
      that instead as it instructs. Note its daily request limit in the group.
- [ ] Your queue: **WP-09 → WP-12.** Same flow as RUNBOOK §4, but paste this start prompt:

```text
Read AGENTS.md and docs/packages/WP-09.md. Work only inside the paths that WP owns.
Implement the next unchecked milestone in its STATUS block, including its tests.
Run the WP's test command until green. Commit with message "WP-09: <milestone>" and push.
Tick the milestone in the STATUS block. Continue milestone by milestone until done.
If you need a decision, write it under "Questions" in the WP file, commit, push, and stop.
```

If its code quality is poor, stop and tell the orchestrator; WP-09/12 move to A1.

## Sunday – Tuesday: quality checks (QA)

After each "merged" message:
1. `cd C:\hishab\repo` → `git switch main` → `git pull` → `npm run dev`
2. Open http://localhost:5173 on your PC **and on your phone** (same Wi-Fi: use the PC's IP).
3. Click through the merged screen: every button, every number (it should open its formula),
   Bangla text correct and natural, nothing cut off on the phone.
4. Each problem → GitHub → Issues → New issue: title, steps, screenshot, label `bug`.

From Monday afternoon do the same on the **hosted** site (`https://hishab.quadbits.net`), and check Bangla wording on every
screen (you're the team's Bangla reviewer).

## Tuesday
- Final QA pass on the hosted site before 14:00 freeze.
- Help Nobo with screen recording for the video.

## Sleep
Sun 01:00–05:00 · Mon 01:00–05:00 · Tue 04:00–06:00 (RUNBOOK §6).
