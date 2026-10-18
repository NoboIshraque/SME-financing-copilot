# Runbook — exactly who does what

All machines are Windows. Commands go in **PowerShell** (the prompt starts with `PS C:\`).
The repo is owned by GitHub user `NoboIshraque`:
`NoboIshraque/SME-financing-copilot` (private).

Per-person versions of this file: `docs/team/NOBO.md`, `docs/team/AMDAD.md`, `docs/team/LABIB.md`.

## 0. Five words you need

| Word | Meaning |
| --- | --- |
| **Repo** | The project's shared master copy, on GitHub (online) |
| **Repo folder** | Your own copy of it on your PC, at `C:\hishab\repo`. You get it with `gh repo clone` (§2). Claude Code works inside this folder |
| **Branch** | A private draft lane inside the repo. Each work package gets its own lane, so four AI sessions never overwrite each other |
| **Commit / push** | Commit = save a snapshot on your PC. Push = upload it to GitHub. Autosave does both every 5 minutes |
| **Pull request (PR)** | "Please merge my lane into the master copy." The orchestrator checks it and merges it |

## 1. Machines

| Machine | Person | What runs there | Claude account |
| --- | --- | --- | --- |
| PC-1 (`knight-27`) | Nobo | Claude Code session **A1** in `C:\hishab\repo` | A |
| PC-2 | Nobo | Claude Code **B1** in `C:\hishab\repo` and **B2** in `C:\hishab\repo-b2` (two PowerShell windows) | B |
| PC-3 | Amdad | Optional Worker C (Google's free coding CLI, Amdad's own Google account), keys, hosting, QA | — |
| PC-4 (desktop) | Labib | Docker stack, scheduled test runs, Ollama, Kaggle/Colab | — |

Both Claude accounts stay on Nobo's PCs (a Claude account is for its owner's use).
**Docker** runs only on the Singapore server and Labib's PC-4; coding PCs don't need it.

## 2. Right now

| # | Who | Task |
| --- | --- | --- |
| 1 | Nobo | Email the registration form + passport bio pages of all 3 members to wangyr@pbcsf.tsinghua.edu.cn |
| 2 | Nobo | Email the same address: "Can a Topic E team earn the on-chain challenge bonus (0–5 points) by anchoring settlement hashes on a public testnet?" |
| 2b | Nobo | quadbits.net pre-checks on Namecheap, 10 min (§5.9 step 0) |
| 3 | Nobo | Tell the orchestrator chat your GitHub username and approve the repo-access prompt |
| 4 | Nobo | ~~Approve or cut P1–P14~~ done: all IN except P10 (CUT) |
| 5 | Nobo | Repo → Settings → Collaborators → add Amdad and Labib |
| 6 | Amdad | API keys (§5.1), then the hosting server (§5.2) |
| 7 | Labib | Book 3–5 shop visits for Sunday 10:00–14:00 (§5.4); set up the wallet (§5.3) |
| 8 | All | Set up your PC (§3) |

Nobody starts a work package until the orchestrator posts "WP-00 merged" in the group.

## 3. Set up a PC (20 minutes)

```powershell
winget install --id Git.Git -e
winget install --id GitHub.cli -e
winget install --id OpenJS.NodeJS.LTS -e
winget install --id Python.Python.3.12 -e
winget install --id astral-sh.uv -e
```

**Nobo's PC-1 and PC-2 only:** `irm https://claude.ai/install.ps1 | iex`

Close PowerShell, open a new one, then:

```powershell
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
gh auth login                       # GitHub.com → HTTPS → Login with a web browser
mkdir C:\hishab
cd C:\hishab
gh repo clone NoboIshraque/SME-financing-copilot repo      # creates the repo folder C:\hishab\repo
```

**PC-2 also needs a second repo folder** for session B2:

```powershell
cd C:\hishab
gh repo clone NoboIshraque/SME-financing-copilot repo-b2   # creates C:\hishab\repo-b2
```

**Claude login (PC-1 and PC-2):** in the repo folder type `claude`, log in through the browser
(PC-1 = account A, PC-2 = account B), then type `/status` to confirm the account. On PC-2 both
windows share the same login.

**Labib's PC-4** also installs Docker and Ollama:

```powershell
winget install --id Docker.DockerDesktop -e
winget install --id Ollama.Ollama -e
ollama pull qwen2.5:3b
```

## 4. Building with Claude Code — step by step

Claude Code is an AI that works inside your repo folder. You give it **one instruction per work
package**. It reads the instructions file, writes the code and tests, runs the tests, saves and
uploads its work, and keeps going until the package is done. You mostly watch and press "Yes"
when it asks to run a command.

**Each work package (WP) has a file** in `docs/packages/`, e.g. `WP-01.md`. Its top line names
the **branch** to use (e.g. `wp-01-facts`). Its STATUS list shows what's done.

### Step by step (example: session A1 starting WP-01)

1. Open PowerShell and go to the repo folder:
   `cd C:\hishab\repo`
2. Download the latest master copy:
   `git switch main` then `git pull`
3. Make the draft lane named in the WP file:
   `git switch -c wp-01-facts`
4. Open a **second** PowerShell window in the same folder and start autosave. Leave it running:
   `powershell -ExecutionPolicy Bypass -File scripts\autosave.ps1`
5. In the first window type `claude`. A prompt box appears. Paste this (change only `WP-01`):

   ```text
   Read CLAUDE.md and docs/packages/WP-01.md. Work only inside the paths that WP owns.
   Implement the next unchecked milestone in its STATUS block, including its tests.
   Run the WP's test command until green. Commit with message "WP-01: <milestone>" and push.
   Tick the milestone in the STATUS block and update the WP-01 row in docs/PLAN.md §8.
   Continue milestone by milestone until the WP is done. If you need a decision, write it under
   "Questions" in the WP file, commit, push, and stop.
   ```

6. Watch. You'll see it read files, write code and run tests. If it asks
   **"Allow this command?"**, read the command. Approve if it only touches this repo (tests,
   installs, git). Refuse anything that deletes things outside the repo or touches other folders.
7. **When it says the WP is done**, type in the same Claude window:
   `Open the pull request for this branch.`
   Then post in the group: "WP-01 PR ready".
8. Wait for "WP-01 merged" from the orchestrator. Type `/clear`, stop autosave (Ctrl+C in
   that window), and go back to step 2 with your next WP.

### If Claude stops early

| It says | You do |
| --- | --- |
| A question under "Questions" | Post it in the group; the orchestrator answers in the WP file; then paste the same prompt again |
| "Usage limit reached" | Note the reset time in the group; do the next non-Claude task in your file; resume after reset with `claude --continue` |
| Tests won't pass after many tries | Type: `Summarise what's failing and why, write it under Questions, commit and stop.` Post in the group |

### Queues

| Session | Machine / folder | Order |
| --- | --- | --- |
| A1 | PC-1 `C:\hishab\repo` | WP-01 → WP-02 → WP-04 → WP-05 → WP-07 → (WP-09, WP-12 if Worker C isn't used) |
| B1 | PC-2 `C:\hishab\repo` | WP-14 → WP-15 |
| B2 | PC-2 `C:\hishab\repo-b2` | WP-11 → WP-10 → WP-16 (WP-03 moved to the orchestrator, 18 Oct) |
| Worker C (optional) | PC-3 | WP-09 → WP-12 |
| Orchestrator | cloud | WP-00 → WP-06 → WP-08 → WP-13 → WP-18 → WP-03 → WP-19, plus notebooks for WP-17, reviews and merges |

## 5. Manual tasks only humans can do

### 5.1 API keys — Amdad (15 min)
1. aistudio.google.com → **Get API key** → Create key. Open the rate-limit page and screenshot the free limits.
2. console.groq.com → **API Keys** → Create. No card needed.
3. Send both keys to Nobo **in person or by phone call**, not in group chat. Nobo pastes them
   into `backend\.env` (copy of `backend\.env.example`) in all three repo folders on PC-1/PC-2:
   `GEMINI_API_KEY=...`, `GROQ_API_KEY=...`
4. Only the repo owner can add GitHub secrets, so Nobo adds them: repo → Settings → Secrets and
   variables → Actions → `GEMINI_API_KEY`, `GROQ_API_KEY`.

### 5.2 Hosting server — Amdad (30 min, needs a payment card)
1. Tencent Cloud International → **Lighthouse** → region **Singapore** → Ubuntu 22.04 (Docker
   image) → 2 vCPU / 4 GB. Firewall: open 22, 80, 443.
   If signup or the card fails: Oracle Cloud Always Free → region Singapore → Ampere A1, Ubuntu.
2. **Domain:** nothing to buy. The app lives at `hishab.quadbits.net` (Nobo's existing domain).
   Send Nobo the server's **public IPv4 address** as soon as the server exists; he sets up DNS (§5.9).
   Keep ports **80 and 443 open**: the server needs them to get its free HTTPS certificate.
   Check Docker on the server (web terminal): `docker --version` and `docker compose version`.
   If missing: `curl -fsSL https://get.docker.com | sudo sh`, then `sudo usermod -aG docker ubuntu`
   and log out and back in.
3. On PC-3: `ssh-keygen -t ed25519 -f $HOME\.ssh\hishab_deploy`. Put the `.pub` file's text into
   the server's `~/.ssh/authorized_keys`.
4. Give Nobo (in person) the values for the Actions secrets he adds: `DEPLOY_HOST` (the IP),
   `DEPLOY_USER` (`ubuntu`), `DEPLOY_SSH_KEY` (private key text). Nobo adds `DEPLOY_DOMAIN` himself.
5. Post "server ready" in the group.

### 5.3 Testnet wallet — Labib (15 min)
1. Install MetaMask; create a **brand-new wallet only for this project**.
2. Turn on test networks → Sepolia. Get free Sepolia ETH from a faucet that needs no mainnet
   balance (Sepolia PoW faucet, or QuickNode).
3. Get a free Sepolia RPC URL (Alchemy, Infura, or a public RPC).
4. Give Nobo `SEPOLIA_RPC_URL` and `SEPOLIA_PRIVATE_KEY` in person; he adds them as GitHub Actions
   secrets (the deploy copies them to the server). Never put them in chat or in a file in the repo.

### 5.4 Real shop data — Labib (Sunday 10:00–14:00)
Follow `docs/packages/WP-20.md`: signed consent, statement export, baki-khata photos,
5-minute interview, one anonymised quote. Raw files only in the private team Google Drive.

### 5.5 Kaggle / Colab — Labib on PC-4
1. Kaggle: verify your phone (needed for GPU and internet). New notebook → Settings →
   Accelerator **GPU T4 x2**, Internet **on**.
2. Open each notebook in `ml/` (the orchestrator writes them), Run All. They checkpoint every
   epoch; click **Save Version** when done.
3. Download `ml/artifacts/*` from the output; commit on branch `wp-17-ml`; open a PR.
4. Backup: Colab → Runtime → T4 GPU; the first cell mounts Google Drive for checkpoints.

### 5.6 China reachability — Nobo (Monday 16:00, 20 minutes, no contact in China needed)

Three layers of proof:

1. **By design (automatic):** our site loads nothing from Google, YouTube, Vercel, Facebook or any
   other blocked service, and a test fails the build if any page tries to. You do nothing here.
2. **China-node tools (free websites that test *from* servers inside mainland China).** Paste the
   live URL into each. Pages may be in Chinese: right-click → Translate.
   - **17CE** (17ce.com) — HTTP test from many Chinese cities: DNS, connect, first-byte times.
   - **BOCE** (boce.com) — repeated HTTP/HTTPS checks from many nodes.
   - **ITDog** (itdog.cn) — HTTP and ping from Chinese ISPs (China Telecom, Unicom, Mobile).
   - **GreatFire Analyzer** (en.greatfire.org/analyzer) — is the domain blocked?
   Screenshot each result page and post them in the group. Good result: most nodes green,
   load under ~3 s, GreatFire "not blocked".
3. **If results are bad:** tell the orchestrator. Fixes: change the domain, or move the server to another
   Singapore provider (e.g. Alibaba Cloud Singapore). The LLM calls stay in Singapore either way.

### 5.9 The domain quadbits.net (Namecheap) — Nobo (10 min now, 5 min later, then up to 1 h of waiting)

The app will live at **`https://hishab.quadbits.net`**. Adding one record leaves anything already
on quadbits.net (website, email) working. Nothing to buy.

**Step 0 — Pre-checks (do now, before the server exists)**
1. **Expiry:** namecheap.com → sign in → **Domain List**. The expiry date for quadbits.net must be
   **after 30 Nov 2026** (finals are 21–23 Nov). If not: click **Manage** → turn on
   **Auto-Renew** or renew now.
2. **Where the DNS lives:** Domain List → **Manage** next to quadbits.net → **Domain** tab →
   **Nameservers** box:
   - **Namecheap BasicDNS** (or the PowerShell command `nslookup -type=NS quadbits.net` prints
     names ending in `registrar-servers.com`) → you edit DNS in Namecheap's **Advanced DNS** tab. ✅ Usual case.
   - **Custom DNS** → the domain's DNS is managed elsewhere. The nameserver names tell you where:
     `ns.cloudflare.com` = Cloudflare → DNS → Records; `vercel-dns.com` = Vercel; `nsone.net` =
     Netlify; `dns-parking.com` = Hostinger; anything else = that web host's control panel.
     Add the record there instead. **Don't switch nameservers** — that would break whatever
     quadbits.net is already using.
3. **China check:** en.greatfire.org/analyzer → enter `quadbits.net` → it must not be reported
   as blocked. If it is, tell the orchestrator.
4. **Name is free:** `nslookup hishab.quadbits.net` should answer "Non-existent domain".

**Step 1 — Add the record (when Amdad sends the server IP)**

Namecheap → Domain List → **Manage** (quadbits.net) → **Advanced DNS** tab → **Host Records**
section → **ADD NEW RECORD**:

| Field | Value |
| --- | --- |
| Type | **A Record** |
| Host | `hishab` (just that word; Namecheap adds `.quadbits.net` itself) |
| Value | the server's public IPv4 from Amdad |
| TTL | **Automatic** |

Click the **green tick ✓** to save. Don't edit or delete existing records (`@`, `www`,
URL redirect, `MX`, `TXT`).

If the Host Records list already contains any **CAA Record**, add one more: Type **CAA Record**,
Host `hishab`, Flag `0`, Tag `issue`, Value `letsencrypt.org` — otherwise the free HTTPS
certificate is refused. No CAA records in the list → skip this.

(Custom DNS from step 0? Same fields in that provider's panel; on Cloudflare set the proxy to
**DNS only**, grey cloud, because the orange proxy is unreliable from China.)

**Step 2 — Check it worked (5–60 minutes later)**
1. PowerShell: `nslookup hishab.quadbits.net 8.8.8.8` → shows the server IP. Repeat with `1.1.1.1`.
2. Post "DNS ready: hishab.quadbits.net" in the group.
3. GitHub repo → Settings → Secrets and variables → Actions → **New repository secret**:
   `DEPLOY_DOMAIN` = `hishab.quadbits.net`.

**Step 3 — After the first deploy (orchestrator posts "deployed")**
Open `https://hishab.quadbits.net` → the app loads with a padlock. The server gets its HTTPS
certificate automatically on first start (Caddy + Let's Encrypt). No padlock after 10 minutes
→ tell the orchestrator.

### 5.7 Deck and video — Nobo (Monday night / Tuesday)
The orchestrator writes slides and the script. Nobo records English narration; the screen
recording follows `docs/submission/video-script.md`; ≤ 5 minutes.

### 5.8 Submit — Nobo
Mon 21:00 insurance and Tue 19:00 final: email the 6 deliverables (checklist in PLAN §9).
Before the final, the orchestrator runs the secret scan; then Nobo makes the repo public.

## 6. Shifts (Dhaka time)

Nobo runs three sessions, so he never sleeps when both teammates are asleep, and he sleeps in
short blocks timed to Claude's 5-hour usage resets.

| Block | Nobo | Amdad | Labib |
| --- | --- | --- | --- |
| Sat 19:00 – Sun 01:00 | awake | awake | awake |
| Sun 01:00 – 05:00 | awake | sleep | awake |
| Sun 05:00 – 09:00 | sleep | awake | sleep |
| Sun 09:00 – Mon 01:00 | awake | awake | shops 10–14, then awake |
| Mon 01:00 – 05:00 | awake | sleep | awake |
| Mon 05:00 – 09:00 | sleep | awake | sleep |
| Mon 09:00 – Tue 02:00 | awake | awake | awake |
| Tue 02:00 – 06:00 | sleep 02–04 | sleep 04–06 | awake |
| Tue 06:00 – 21:59 | awake | awake | awake (short nap 08–10) |

## 7. When something breaks

| Problem | Do this |
| --- | --- |
| Power or Wi-Fi cut | Switch to a phone hotspot. After power returns: `cd C:\hishab\repo; git status; claude --continue`. Autosave has your work up to the last 5 minutes |
| Merge conflict | In that Claude window: `Rebase on origin/main and resolve conflicts keeping both sides' intent, then run the tests.` |
| Tests fail on main | Post in the group; the orchestrator fixes or reverts |
| A key leaked | Revoke it in the provider console at once, make a new one, tell Nobo |
| Kaggle session died | Reopen the notebook; it resumes from the last checkpoint |
