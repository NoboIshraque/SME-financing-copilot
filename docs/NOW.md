# Do this next

Maintained by the orchestrator. Mission control (the pinned GitHub issue) is rebuilt from this
file automatically, and anyone whose section changes gets an @mention (phone push via GitHub
Mobile). Done something? Tick it in your head and comment "done: <item>" on the issue.

<!-- section: nobo -->
## Nobo (@NoboIshraque) — PC-1 and PC-2

Step-by-step guides (20 Oct): `docs/handover/VIDEO.md` (recording), `docs/handover/SERVER.md`
(server or no-card tunnel), `docs/handover/FREE_SERVER.md` (free hosting on Render, no card, no PC), `docs/handover/NOTEBOOK01.md` (Labib's notebook, plain words),
`docs/handover/AUDIT_PROMPT.md` (paste into a new chat for the final audit).

**Final audit (20 Oct):** report in `docs/handover/AUDIT_REPORT.md`; 32 of 37 findings fixed and merged (PRs #41, #43,
#45, #47), the rest explained there. Deck, technical documentation and self-assessment PDFs were re-exported on 20 Oct
with the guard's held-out result (15/24 attacks caught, 10/24 false alarms); `video-script.md` matches today's screens.

State at 20 Oct 01:00 (orch-C): every work package is merged or cut; the product is now
**DecisionGuard**. Submission files: `docs/submission/` (PDFs in `docs/submission/pdf/`).

- [ ] **Deck:** the Slides artifact lives on orch-A's claude.ai account and still says Hishab. Either republish it from `docs/submission/deck/` or send `docs/submission/pdf/deck.pdf`.
- [ ] **Video (≤ 5 min):** record from `docs/submission/video-script.md` (`npm run dev`, demo shop `sme_hardware`, owner@hardware.hishab.test); save as `DecisionGuard_TopicE_BUP_demo.mp4`; run `npm run evidence` once more after recording.
- [ ] **Send** (PLAN §9): deck, technical doc, security self-assessment, evidence bundle, video, repo link (source zip while the repo is private) to wangyr@pbcsf.tsinghua.edu.cn.
- [ ] When Amdad sends the server IP: Namecheap A record `hishab` → IP (RUNBOOK §5.9), then add secrets `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_DOMAIN`.
- [ ] Before making the repo public: run the all-refs secret scan (WP-18, PR #14).

<!-- section: amdad -->
## Amdad (@amdad1203)

- [ ] **Server (RUNBOOK §5.2, 30 min) — still the only blocker for the hosted demo and the hosted E2E run:** Tencent Lighthouse Singapore, Ubuntu 22.04, 2 vCPU / 4 GB, ports 22/80/443. Send Nobo the **public IP** right away.
- [ ] On the server: `docker --version` (install if missing: `curl -fsSL https://get.docker.com | sudo sh`), then `mkdir -p ~/hishab/shared ~/hishab/releases ~/hishab/backups`.
- [ ] Create `~/hishab/shared/.env` from `infra/.env.example`: fill `DEPLOY_DOMAIN=hishab.quadbits.net`, and three values from `openssl rand -hex 32` for `POSTGRES_PASSWORD`, `SECRET_KEY`, `VAULT_KEY`. Nobo types the Gemini, Groq and Sepolia values in **in person**; set `CHAIN_MODE=sepolia`.
- [ ] Deploy key (RUNBOOK §5.2 step 3) and give Nobo `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY` **in person**.

<!-- section: labib -->
## Labib (@lab-af)

- [x] **Notebook 01 done (20 Oct, orch-C ran it on UCI Online Retail II).** Nothing to do unless you want to rerun it on Kaggle: (`01_forecast_backtest`, table in `docs/team/LABIB.md`): the orchestrator cannot download the public datasets from the cloud. Save the version and push the artefacts (< 50 MB) to `ml/`.
- [x] **Real data (WP-20):** done 20 Oct by orch-C with the public substitutes (Bangladeshi retailer sales 2013-17 and UCI Online Retail II, both backtested). Field data only if an owner sends some.
- [ ] PC-4 hourly jobs (LABIB.md "PC-4 always-on jobs") if not running yet.
