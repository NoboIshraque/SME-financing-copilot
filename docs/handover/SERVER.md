# Put DecisionGuard online: which server, and how

For: Nobo and Amdad. Goal: a link such as `https://hishab.quadbits.net` that judges in mainland
China (Tsinghua) can open, showing the live app with the synthetic demo shops.

Read first (repo facts this page relies on): `docs/DEPLOY.md`, `docs/RUNBOOK.md` §5.2, §5.6 and
§5.9, `infra/docker-compose.yml`, `infra/Caddyfile`, `infra/.env.example`,
`.github/workflows/deploy.yml`, `docs/packages/WP-18.md`.

**Never** paste a real password, key or token into this file, a chat, a commit or a screenshot.

---

## 1. Decision (read this, then go to your path)

| Path | Cost | Needs a card | Time | China reachability | Use it when |
| --- | --- | --- | --- | --- | --- |
| **A. Tencent Cloud Lighthouse, Singapore** (recommended) | small monthly fee | yes, an internationally enabled Visa/Mastercard | 45–60 min | good (Singapore, no blocked services) | Someone on the team has a card that works abroad |
| A-alt. Alibaba Cloud Simple Application Server, Singapore | similar | yes | same | good | Tencent refuses the card or the identity check |
| A-alt. Vultr or DigitalOcean, Singapore | similar | yes (or PayPal at some) | same | usually fine, sometimes slower than Tencent/Alibaba | Both Chinese clouds refuse you |
| **B. Team PC + Cloudflare Tunnel** (no card) | free | no | 20 min (quick tunnel) | usually reachable, but slower and less reliable | No card works, or you need a link **today** while waiting for A |

What gets deployed is the same in every path: the Docker stack in
`infra/docker-compose.yml` with four containers: `db` (PostgreSQL 16), `api` (FastAPI),
`worker` (scheduled jobs) and `web` (Caddy: serves the web app, HTTPS, security headers, and
forwards `/api/*` to the API).

The web app loads nothing from Google, YouTube or any CDN (an automated browser test enforces
it), so the only China question is the route to the server itself.

---

## 2. Why Oracle Cloud and Azure failed, and how to avoid it next time

Both clouds check your card and identity with automatic fraud rules. Common reasons they refuse
Bangladeshi applicants:

1. **The card is not enabled for international online payments.** Most Bangladeshi debit cards
   work only in taka inside Bangladesh. You need a **dual-currency / international** card, or an
   international limit (USD endorsement) on your card. Ask your bank; it usually needs your
   passport.
2. **International / e-commerce use is switched off in the bank app.** Turn on "international
   transactions" and "online (e-commerce) transactions" in the bank's app or call centre
   **before** signing up.
3. **Debit or prepaid cards** are refused more often than credit cards by Oracle's free tier.
4. **Name or address mismatch.** Type your name and billing address **exactly** as the bank has
   them (same spelling, same city, same postcode).
5. **VPN or proxy during sign-up.** A VPN makes your IP country differ from the card's country,
   which looks like fraud. **Turn the VPN off** for the whole sign-up.
6. **Many attempts.** After two or three failures the provider may block the card for a day.
   Stop, fix the cause, then try a different provider.
7. The small test charge (often around US$1, refunded) needs a few dollars of **available
   balance** on the card.

Worth one try if you have a university email: **Azure for Students** (azure.microsoft.com/free/students)
verifies you with an academic email instead of a card. If BUP email works there, create an
Ubuntu VM in region **Southeast Asia (Singapore)** and follow Path A from step A5.

---

## 3. Path A: Tencent Cloud Lighthouse (Singapore)

`docs/RUNBOOK.md` §5.2 already targets this. Steps marked **(Amdad)** need the card holder;
steps marked **(Nobo)** need the GitHub repo owner and the Namecheap account.

### A1. Create the account (Amdad, 10 min)

1. VPN **off**. Card international use **on** (section 2).
2. Open `https://www.tencentcloud.com` (the **international** site, not the Chinese one).
3. **Sign Up** → email → verify the email.
4. Complete the identity / payment step: add the card. Use the exact name and billing address
   from the bank. Tencent may also ask for identity documents; have your passport ready.
5. Wait for the account to be confirmed (usually minutes).

### A2. Create the server (Amdad, 5 min)

1. Console → search **Lighthouse** → **Create**.
2. Region: **Singapore**.
3. Image: **Ubuntu 22.04 LTS** (system image). If the list offers an application image
   **Docker CE** on Ubuntu, that is fine too (Docker is then pre-installed).
4. Plan: **2 vCPU, 4 GB RAM** (the build of the web app needs the memory). Check the price on
   the page; pay monthly.
5. Set a login method: an SSH key or a password. Write the password in your password manager,
   not in chat.
6. **Buy / Create**. After a minute the instance shows **Running** and a **public IPv4 address**.
7. Send the **IP address** to Nobo (the IP is not secret).

### A3. Open the firewall (Amdad, 2 min)

Lighthouse → your instance → **Firewall** tab. Make sure these rules exist (add any that are
missing with **Add rule**):

| Protocol | Port | Source | Why |
| --- | --- | --- | --- |
| TCP | 22 | all | SSH (deploys and your terminal) |
| TCP | 80 | all | HTTP; Let's Encrypt uses it to issue the HTTPS certificate |
| TCP | 443 | all | HTTPS |
| UDP | 443 | all | HTTP/3 (optional) |

### A4. DNS at Namecheap (Nobo, 5 min + up to 1 h waiting)

Exactly as in `docs/RUNBOOK.md` §5.9 step 1:

1. namecheap.com → sign in → **Domain List** → **Manage** next to `quadbits.net` →
   **Advanced DNS** tab → **Host Records** → **ADD NEW RECORD**.
2. Type **A Record**, Host `hishab`, Value = the server IP, TTL **Automatic** → green tick ✓.
3. Do not touch the other records.
4. If the list already has a **CAA Record**, add: CAA, Host `hishab`, Flag `0`, Tag `issue`,
   Value `letsencrypt.org`.
5. Check after 5–60 minutes, in PowerShell: `nslookup hishab.quadbits.net 8.8.8.8` → it shows
   the server IP.

(If the Nameservers box says Custom DNS, add the record at that DNS provider instead. On
Cloudflare set the proxy to **DNS only**, grey cloud: the orange proxy is unreliable from China.)

### A5. Log in to the server and install Docker (Amdad, 5 min)

1. Lighthouse → instance → **Login** (opens a web terminal in the browser). Or from PowerShell:
   `ssh ubuntu@<server IP>`.
2. Check Docker:
   ```bash
   docker --version
   docker compose version
   ```
3. If either is missing:
   ```bash
   curl -fsSL https://get.docker.com | sudo sh
   sudo usermod -aG docker $USER
   exit
   ```
   Log in again (step 1) so the group change applies.
4. Make the folders the deploy expects:
   ```bash
   mkdir -p ~/hishab/shared ~/hishab/releases ~/hishab/backups
   ```

### A6. Create the server's secret file (Amdad, 5 min; Nobo types the API keys in person)

The template is `infra/.env.example`. The real file lives **only on the server** at
`~/hishab/shared/.env`.

1. Make three random values, one at a time:
   ```bash
   openssl rand -hex 32
   ```
   Run it three times. Keep the output on screen; you paste it in step 3. Do not save it
   anywhere else.
2. Open the file: `nano ~/hishab/shared/.env`
3. Type (or paste) this, filling in the empty values:

   ```
   APP_ENV=demo
   DEMO_MODE=true
   DEPLOY_DOMAIN=hishab.quadbits.net
   ACME_EMAIL=<a team email that receives certificate notices>
   POSTGRES_PASSWORD=<first openssl value>
   SECRET_KEY=<second openssl value>
   VAULT_KEY=<third openssl value>
   LLM_MODE=live
   GEMINI_API_KEY=<Nobo types it in person>
   GROQ_API_KEY=<Nobo types it in person>
   CHAIN_MODE=offline
   SEPOLIA_RPC_URL=<leave empty while CHAIN_MODE=offline>
   SEPOLIA_PRIVATE_KEY=<leave empty while CHAIN_MODE=offline>
   ```

   Replace every `<…>` with the real value. For a line that should stay empty, delete
   everything after the `=`.

4. Save: **Ctrl+O**, **Enter**, then **Ctrl+X**.
5. Lock it: `chmod 600 ~/hishab/shared/.env`

What each value means:

| Name | Required | What to put |
| --- | --- | --- |
| `APP_ENV` | yes | `demo` (the hosted competition demo). Keep it |
| `DEMO_MODE` | yes | `true`: demo accounts, published demo codes and the synthetic banner. Keep it |
| `DEPLOY_DOMAIN` | yes | `hishab.quadbits.net`. Caddy gets the HTTPS certificate for this name |
| `ACME_EMAIL` | no | email for Let's Encrypt notices (empty → `admin@quadbits.net` from the compose file) |
| `POSTGRES_PASSWORD`, `SECRET_KEY`, `VAULT_KEY` | yes | each a separate `openssl rand -hex 32`. The app refuses to start in `demo` with a key shorter than 32 characters |
| `LLM_MODE` | yes | `live`. With both LLM keys empty, the copilot falls back to its deterministic planner (no model calls) |
| `GEMINI_API_KEY`, `GROQ_API_KEY` | no | Nobo types them **in person**, never via chat |
| `CHAIN_MODE` | yes | `offline` unless **both** Sepolia values below are filled; then `sepolia` (as in `docs/NOW.md`). With `offline`, anchors are stored locally and labelled "offline" |
| `SEPOLIA_RPC_URL`, `SEPOLIA_PRIVATE_KEY` | no | from Labib's project-only testnet wallet (RUNBOOK §5.3), typed in person |

Note: `deploy.yml` does **not** copy these values to the server. The server's `.env` is the
only place they live.

### A7. Get the code onto the server: pick ONE option

**Option 1 (recommended): let GitHub Actions ship it.** No token on the server, and every later
merge to `main` deploys itself with a health check and automatic rollback.

1. **Deploy key pair** (Amdad, on his Windows PC, PowerShell):
   ```powershell
   ssh-keygen -t ed25519 -f $HOME\.ssh\hishab_deploy
   ```
   Press **Enter** twice for **no passphrase** (GitHub Actions cannot type one).
2. Put the **public** half on the server. On the PC: `Get-Content $HOME\.ssh\hishab_deploy.pub`
   → copy the one line. On the server:
   ```bash
   mkdir -p ~/.ssh && chmod 700 ~/.ssh
   nano ~/.ssh/authorized_keys      # paste the line on a new line, save
   chmod 600 ~/.ssh/authorized_keys
   ```
3. Copy the **private** half to the clipboard (PC):
   `Get-Content $HOME\.ssh\hishab_deploy -Raw | Set-Clipboard`
4. **Repository secrets** (Nobo, as repo owner): GitHub → repo `NoboIshraque/SME-financing-copilot`
   → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**. Add
   these four (names exactly; values given to Nobo in person):

   | Secret name | Value |
   | --- | --- |
   | `DEPLOY_HOST` | the server IP |
   | `DEPLOY_USER` | the login user, `ubuntu` on Tencent's Ubuntu image |
   | `DEPLOY_SSH_KEY` | the whole private key text from step 3 (including the BEGIN/END lines) |
   | `DEPLOY_DOMAIN` | `hishab.quadbits.net` |

5. Run it: GitHub → **Actions** → workflow **Deploy** → **Run workflow** → branch **main** →
   **Run workflow**. Watch it (about 5–15 minutes; the first build is the slowest).
   - It copies the exact commit to `~/hishab/releases/<commit>`, builds, starts the stack,
     waits for `https://hishab.quadbits.net/api/health` to say `"status":"ok"`, then points
     `~/hishab/current` at it. It also installs the hourly backup job.
   - If the deploy secrets are missing, the run says "Deploy secrets not set yet - skipping".
   - The smoke test needs DNS (A4) to work first, or it fails after about 5 minutes.
6. Go to **A9** (seed the data).

**Option 2: clone by hand on the server.** Use this if Actions is not available.

The repo is private, so the server needs read access. Choose one:

- **Fine-grained read-only token** (Nobo): GitHub → your profile picture → **Settings** →
  **Developer settings** → **Personal access tokens** → **Fine-grained tokens** →
  **Generate new token**. Name `hishab-server-read`, Expiration **7 days**, Resource owner
  **NoboIshraque**, Repository access **Only select repositories** → `SME-financing-copilot`,
  Permissions → Repository permissions → **Contents: Read-only**. **Generate token**. Give it
  to Amdad in person. On the server:
  ```bash
  git clone https://github.com/NoboIshraque/SME-financing-copilot.git ~/hishab/releases/manual
  ```
  Username: `NoboIshraque`. Password: paste the token (nothing shows while you paste; press
  Enter). Delete the token on GitHub after the competition.
- **Deploy key** (read-only SSH key just for this repo): on the server
  `ssh-keygen -t ed25519 -f ~/.ssh/github_read` (Enter twice), `cat ~/.ssh/github_read.pub`,
  then GitHub repo → **Settings** → **Deploy keys** → **Add deploy key** → paste, leave
  **Allow write access unticked** → **Add key**. Then:
  ```bash
  GIT_SSH_COMMAND="ssh -i ~/.ssh/github_read" git clone git@github.com:NoboIshraque/SME-financing-copilot.git ~/hishab/releases/manual
  ```

### A8. Start the stack (Option 2 only; Option 1 already did this)

From `docs/DEPLOY.md` §3:

```bash
cd ~/hishab/releases/manual
docker compose --env-file ~/hishab/shared/.env -f infra/docker-compose.yml up -d --build
ln -sfn "$PWD" ~/hishab/current
```

The first build takes 5–15 minutes. Then `docker compose --env-file ~/hishab/shared/.env -f
infra/docker-compose.yml ps` should list `db`, `api`, `worker`, `web` as running / healthy.

### A9. Load the synthetic shops (both options, once)

Without this step, Cash and Today refuse to answer ("at least 8 weeks of transactions"),
because the database has no ledger facts (`docs/packages/WP-15.md`, Questions 2). It is safe
to run again (idempotent).

```bash
cd ~/hishab/current
docker compose --env-file ~/hishab/shared/.env -f infra/docker-compose.yml exec api python -m app.facts.seed
```

It prints one line per shop: `seeded sme_…: … transactions (synthetic)`.

### A10. Check health and open it

1. On the server or your PC: `curl https://hishab.quadbits.net/api/health`
   (route `GET /api/health`, `backend/app/api/health.py`). Good answer:
   `{"status":"ok", "contracts_version": …, "data_mode_banner":"synthetic", "config": {…}}`.
   `config` shows only whether keys are set, never the keys.
2. Browser: `https://hishab.quadbits.net` → padlock, sign-in page with **Try the demo**.
3. Tap **Sign in as Owner** (Nawabpur Hardware Traders) → type the **Demo code** → **Verify** →
   Today shows the Critical alert.
4. No padlock after 10 minutes: see Troubleshooting.

### A11. Check from China (Nobo, 10 min; RUNBOOK §5.6)

Paste `https://hishab.quadbits.net` into each tool. Pages may be in Chinese: right-click →
Translate.

1. **17CE** `https://www.17ce.com` → HTTP test from many mainland cities.
2. **Chinaz ping** `https://ping.chinaz.com` → ping/latency from Chinese ISPs.
3. **ITDog** `https://www.itdog.cn` and **BOCE** `https://www.boce.com` (RUNBOOK §5.6).
4. **GreatFire Analyzer** `https://en.greatfire.org/analyzer` → "not blocked".

Good result: most nodes green, page load under about 3 s, not blocked. Screenshot each result
for `docs/submission/evidence/china.md` (WP-18 milestone 4). Bad result: tell the orchestrator
(fixes: another Singapore provider, or another domain).

### A12. After it works

1. Tell the group "hosted demo up" and the orchestrator.
2. Hosted browser tests: GitHub → **Actions** → **E2E** → **Run workflow** → target `hosted`
   (`docs/submission/evidence/e2e/README.md`).
3. The video's closing card may then show the URL (`docs/submission/video-script.md` S14).

### Differences on the alternative providers

| Provider | Product / where | Default user | Firewall |
| --- | --- | --- | --- |
| Alibaba Cloud (international, alibabacloud.com) | **Simple Application Server**, region **Singapore**, Ubuntu 22.04, 2 vCPU / 4 GB | `root` (or the one you set) | instance → **Firewall** → add TCP 80, 443 (22 is usually open) |
| Vultr (vultr.com) | **Cloud Compute**, location **Singapore**, Ubuntu 22.04, 2 vCPU / 4 GB | `root` | no firewall by default; if you add a Firewall Group, allow 22, 80, 443 |
| DigitalOcean (digitalocean.com) | **Droplet**, region **Singapore (SGP1)**, Ubuntu 22.04, 4 GB | `root` | Networking → Firewalls: allow 22, 80, 443 if you add one |

Everything else (A4 to A12) is the same. Use the provider's default user as `DEPLOY_USER`.
With `root`, the folders are under `/root/hishab`, which the workflow handles (it uses `$HOME`).

---

## 4. Path B: team PC + Cloudflare Tunnel (no card)

Use an always-on PC with Docker (Labib's PC-4 already has Docker Desktop, RUNBOOK §3).
Cloudflare Tunnel makes an outgoing connection from the PC to Cloudflare, so you need **no**
open ports, no public IP and no router changes.

Honest limits:

- Cloudflare is usually reachable from mainland China, but **slower and less reliable** than a
  Singapore server, because the free plan does not route through China. Test it (A11) before
  sending the link.
- A **quick tunnel** URL (`https://<random words>.trycloudflare.com`) **changes every time the
  tunnel restarts** and has no uptime guarantee. Fine for a test or an emergency link, not for
  a link printed in the submission.
- If the PC sleeps, loses power or Wi-Fi, the site is down.

### B1. Prepare the PC (15 min)

1. Settings → System → Power → Sleep: **Never**. Plugged in.
2. Docker Desktop running (whale icon in the tray says "Engine running"). If missing:
   `winget install --id Docker.DockerDesktop -e`, restart, open Docker Desktop once.
3. A copy of the repo (private repo; this PC already has `gh` logged in per RUNBOOK §3):
   ```powershell
   cd C:\hishab
   gh repo clone NoboIshraque/SME-financing-copilot hosting
   cd C:\hishab\hosting
   git switch main
   git pull
   ```
   (Use a separate folder so it never touches anyone's work branch.)
4. Install cloudflared: `winget install --id Cloudflare.cloudflared -e`. Close and reopen
   PowerShell.

### B2. The secret file for this PC

1. Make the folder: `mkdir C:\hishab\shared`
2. Make three random values. Either in **Git Bash** (comes with Git for Windows):
   `openssl rand -hex 32`, or in PowerShell (same result, 64 hex characters):
   ```powershell
   $b = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); -join ($b | ForEach-Object { $_.ToString('x2') })
   ```
3. `notepad C:\hishab\shared\.env` → **Yes** to create it. Content as in A6, with **one
   difference**:

   ```
   DEPLOY_DOMAIN=:80
   ```

   Why: Cloudflare already provides HTTPS to the visitor and talks to the PC over the tunnel.
   `:80` tells Caddy to serve plain HTTP on port 80 for **any** host name, so it answers for the
   tunnel's name and does not try to get a certificate itself. The API's CSRF check accepts a
   request whose `Origin` matches its `Host` (`backend/app/security/web.py`), which is the case
   through the tunnel. Keep `APP_ENV=demo`: visitors reach it over HTTPS, so the secure session
   cookie works.
4. Notepad: **File → Save as** → Encoding **UTF-8** → Save. Make sure the name is `.env`, not
   `.env.txt` (in the Save dialog choose "Save as type: All files").

### B3. Start the stack and load the data

```powershell
cd C:\hishab\hosting
docker compose --env-file C:\hishab\shared\.env -f infra\docker-compose.yml up -d --build
docker compose --env-file C:\hishab\shared\.env -f infra\docker-compose.yml ps
docker compose --env-file C:\hishab\shared\.env -f infra\docker-compose.yml exec api python -m app.facts.seed
```

Check locally: open `http://localhost/api/health` in a browser → `"status":"ok"`.
Restarts: the containers have `restart: unless-stopped`, so they come back when Docker Desktop
starts. In Docker Desktop → Settings → General, tick **Start Docker Desktop when you sign in**.

### B4. Quick tunnel (2 minutes, no account)

```powershell
cloudflared tunnel --url http://localhost:80
```

After a few seconds it prints a box with `https://<random-words>.trycloudflare.com`. Open that
address on your phone (mobile data) → the sign-in page. **Keep this window open**; closing it
ends the link. A restart gives a **new** address.

### B5. Named tunnel with our own domain (30–60 min, free Cloudflare account)

A named tunnel gives a fixed address such as `https://hishab.quadbits.net`. It needs the
domain's DNS to be managed by Cloudflare.

**About quadbits.net (Namecheap):** today its DNS is at Namecheap (RUNBOOK §5.9). Two choices:

- **Move quadbits.net's DNS to Cloudflare's free plan.** Cloudflare copies the existing records
  during setup, but you must check that **every** record (website `@`, `www`, `MX` mail, `TXT`)
  was copied before you switch, or email and the website break. RUNBOOK §5.9 warns against
  switching nameservers casually; only do this if Nobo agrees.
- **Use a separate cheap domain** just for the demo and add it to Cloudflare. Nothing on
  quadbits.net changes.

Do **not** also point `hishab.quadbits.net` at a Path A server at the same time; one name, one
target.

Steps:

1. `https://dash.cloudflare.com` → **Sign up** (free; no card for the free plan).
2. **Add a site / Add a domain** → enter the domain → **Free** plan → review the imported DNS
   records (compare with Namecheap's **Advanced DNS** list; add any missing one by hand).
3. Cloudflare shows two **nameservers**. Namecheap → Domain List → **Manage** → **Domain** tab
   → **Nameservers** → **Custom DNS** → enter the two Cloudflare names → green tick ✓.
   Wait until Cloudflare says the site is **Active** (minutes to a few hours).
4. Cloudflare → **Zero Trust** (left menu) → **Networks** → **Tunnels** → **Create a tunnel**
   → type **Cloudflared** → name `hishab-pc` → **Save**. (Menu names move around; look for
   "Tunnels".)
5. Choose **Windows**. Cloudflare shows a command like `cloudflared.exe service install <token>`.
   Run it in an **administrator** PowerShell (Start → PowerShell → right-click → Run as
   administrator). The tunnel now runs as a Windows service and survives restarts. The token is
   a secret: do not paste it anywhere else.
6. Back in Cloudflare → **Next** → **Public Hostname**: Subdomain `hishab`, Domain your domain,
   Service Type **HTTP**, URL `localhost:80` → **Save tunnel**.
7. Open `https://hishab.<your domain>` → sign-in page with a padlock (Cloudflare's certificate).
8. Run the China checks (A11).

---

## 5. Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Card refused at sign-up | Card not international, e-commerce off, VPN on, name mismatch | Section 2. Then try Alibaba, then Vultr/DigitalOcean, or Path B |
| `nslookup hishab.quadbits.net` shows nothing or an old IP | DNS not yet updated or record wrong | Wait up to 1 h; check Host is `hishab` (not the full name) and the IP |
| No padlock / certificate error (Path A) | Port 80 or 443 closed, DNS wrong, or a CAA record blocks Let's Encrypt | A3 firewall; A4 DNS and CAA; then `docker compose … logs web` and look for "certificate" errors |
| Deploy run: "Deploy secrets not set yet - skipping" | Secrets missing | A7 option 1 step 4 (names exactly) |
| Deploy run fails at "SSH key" or "Ship release" | Wrong key, wrong user, or public key not in `authorized_keys` | Check `DEPLOY_USER`; try `ssh -i $HOME\.ssh\hishab_deploy <user>@<IP>` from the PC |
| Deploy run fails at "Smoke test" then rolls back | DNS/HTTPS not ready, or the app crashed | Fix DNS first; on the server `docker compose --env-file ~/hishab/shared/.env -f infra/docker-compose.yml logs api` |
| `api` keeps restarting, log says `secret_key must be set to 32+ characters` | Empty or short key in `.env` | Fill `SECRET_KEY` and `VAULT_KEY` with `openssl rand -hex 32` |
| `set POSTGRES_PASSWORD` error from compose | Missing value or wrong `--env-file` path | Check the path and the line in `.env` |
| Build stops with "killed" or out of memory | Server has under 4 GB RAM | Use 4 GB, or add swap: `sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile` |
| Today / Cash say not enough data | Data not seeded | A9 (or B3 last line) |
| Sign-in fails with "origin not allowed" (403) | `DEPLOY_DOMAIN` does not match the address you open | Path A: open exactly `https://hishab.quadbits.net`. Path B: `DEPLOY_DOMAIN=:80`, then `docker compose … up -d` again |
| Many people sign in through the tunnel and get "too many requests" (429) | Through the tunnel, visitors can share one client IP for rate limiting | Wait a minute; for judges, prefer Path A |
| Path B: port 80 already in use | IIS, Skype or another web server on the PC | Stop it (Services → "World Wide Web Publishing Service" → Stop), then `docker compose … up -d` |
| Quick tunnel link stopped working | The PowerShell window closed or the PC restarted; the URL changed | Run B4 again and share the new URL, or set up B5 |
| Slow or failing from China | Cloudflare route or provider route | Prefer Path A in Singapore; test with 17CE / Chinaz; tell the orchestrator |
| Health JSON shows `"chain_mode":"offline"` | Expected unless both Sepolia values are set | Set both, `CHAIN_MODE=sepolia`, restart: `docker compose … up -d` |
