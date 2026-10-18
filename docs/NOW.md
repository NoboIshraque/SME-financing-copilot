# Do this next

Maintained by the orchestrator. Mission control (the pinned GitHub issue) is rebuilt from this
file automatically, and anyone whose section changes gets an @mention (phone push via GitHub
Mobile). Done something? Tick it in your head and comment "done: <item>" on the issue.

<!-- section: nobo -->
## Nobo (@NoboIshraque) — PC-1 and PC-2

- [ ] **Now, 2 min: merge the orchestrator's PRs** (this session can't merge; one tap each in GitHub Mobile, all green): **#10** CI-minutes fix first, then **#12** (Labib's anonymiser, needed by ~14:00), then **#11** (WP-17 injection fix).
- [ ] **Now, 5 min:** repo → Settings → Collaborators → *Add people* → `amdad1203` and `lab-af` (Write access).
- [ ] **Now:** start **B2 on WP-11** (`C:\hishab\repo-b2`, branch `wp-11-security`) with the RUNBOOK §4 start prompt (B1 is on WP-14, A1 on WP-02: both running).
- [ ] **Keys, 10 min (never in chat or in git):** repo → Settings → Secrets and variables → Actions → *New repository secret*: `GEMINI_API_KEY`, `GROQ_API_KEY`. Do **not** add the MetaMask key to GitHub; it goes only into the server's `.env` (Amdad's step) .
- [ ] **Keys on your PCs:** in every repo folder (`C:\hishab\repo`, `C:\hishab\repo-b2`) copy `backend\.env.example` to `backend\.env` and fill `GEMINI_API_KEY` and `GROQ_API_KEY` only. Leave `LLM_MODE=fixtures`.
- [ ] Install **GitHub Mobile** → sign in → open the repo → *Watch* → *Custom* → **Issues** → allow notifications.
- [ ] Windows fix (once, in each repo folder after `git pull`): `Remove-Item -Recurse -Force data\synthetic\universe; git checkout -- data/synthetic/universe` (then `npm run test:backend` is fully green).
- [ ] When Amdad sends the server IP: Namecheap A record `hishab` → IP (RUNBOOK §5.9), then add secrets `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_DOMAIN`.

<!-- section: amdad -->
## Amdad (@amdad1203)

- [ ] Accept the GitHub invite (email from GitHub), install **GitHub Mobile**, *Watch → Custom → Issues* on the repo.
- [ ] **Server (RUNBOOK §5.2, 30 min):** Tencent Lighthouse Singapore, Ubuntu 22.04, 2 vCPU / 4 GB, open ports 22/80/443. Send Nobo the **public IP** right away.
- [ ] On the server: `docker --version` (install if missing: `curl -fsSL https://get.docker.com | sudo sh`), then `mkdir -p ~/hishab/shared ~/hishab/releases ~/hishab/backups`.
- [ ] Create `~/hishab/shared/.env` from `infra/.env.example`: fill `DEPLOY_DOMAIN=hishab.quadbits.net`, and three values from `openssl rand -hex 32` for `POSTGRES_PASSWORD`, `SECRET_KEY`, `VAULT_KEY`. Nobo types the Gemini, Groq and Sepolia values in **in person**; set `CHAIN_MODE=sepolia`.
- [ ] Deploy key (RUNBOOK §5.2 step 3) and give Nobo `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY` **in person**.

<!-- section: labib -->
## Labib (@lab-af)

- [ ] Accept the GitHub invite, install **GitHub Mobile**, *Watch → Custom → Issues*.
- [ ] **10:00–14:00 shops (WP-20):** consent → statement export → baki-khata photos → 5-minute interview. Raw files only in the private Drive folder.
- [ ] **After each shop, anonymise (10 min):** type the baki photos into a sheet, put `known_names.txt` (owner/shop/staff names) in the shop's raw folder, then in `C:\hishab\repo` (branch `wp-20-data`): `uv --directory backend run python -m app.privacy.shopfiles "G:\My Drive\hishab-raw\shop01" --shop shop01-grocery` (change the path to that shop's raw folder; next shop: `shop02-pharmacy` etc.). Check `data\real_anonymised\shop01-grocery\` by eye, then commit and push. Full steps: `docs/packages/WP-20.md` → "Anonymise".
- [ ] **Afternoon: Kaggle notebooks 01, 03, 04** (table in `docs/team/LABIB.md`, now on `main`). Download AgriPriceBD first: https://data.mendeley.com/datasets/bkmxnrn3hn
- [ ] PC-4 hourly jobs (LABIB.md "PC-4 always-on jobs") if not running yet.
