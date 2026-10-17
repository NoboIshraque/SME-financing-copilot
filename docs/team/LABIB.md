# Labib — your instructions

You own **real shop data, the testnet wallet, Kaggle/Colab training and the always-on desktop
(PC-4)**. You don't use Claude accounts. Full detail: `docs/RUNBOOK.md`.

## Saturday (now → midnight)

- [ ] Send Nobo your passport bio page scan (registration).
- [ ] Phone/visit 3–5 small shops (grocery, pharmacy, fabric, hardware) and book Sunday
      10:00–14:00 visits. Print 5 copies of the consent form in `docs/packages/WP-20.md`.
- [ ] **Wallet (15 min):** install MetaMask → create a **new** wallet only for this project →
      turn on test networks → Sepolia → get free Sepolia ETH (Sepolia PoW faucet or QuickNode,
      no mainnet balance needed) → get a free Sepolia RPC URL (Alchemy, Infura or public).
      Give Nobo the RPC URL and private key **in person**. Never in chat or a file.
- [ ] **Kaggle:** create/log in → verify your phone (needed for GPU and internet).
- [ ] **Set up PC-4 (desktop):** RUNBOOK §3 (skip the Claude install), plus Docker and Ollama:

```powershell
winget install --id Docker.DockerDesktop -e
winget install --id Ollama.Ollama -e
winget install --id Google.GoogleDrive -e
ollama pull qwen2.5:3b
```

- [ ] In Google Drive for desktop, sign in and create the folder `My Drive\hishab-backups`.

## PC-4 always-on jobs (start after "WP-00 merged")

Your own work (Kaggle artefacts, data) uses `C:\hishab\repo`; the scheduled jobs use
`C:\hishab\integration`, so they never touch your branch. The desktop stays on, plugged in, sleep disabled (Settings → System → Power → Sleep: Never).

```powershell
cd C:\hishab
gh repo clone NoboIshraque/SME-financing-copilot integration   # separate copy only for these jobs
cd C:\hishab\integration
npm run setup
# hourly: pull main, run all tests, log results
schtasks /create /sc hourly /tn HishabIntegration /tr "powershell -ExecutionPolicy Bypass -File C:\hishab\integration\scripts\integration.ps1"
# hourly: full repo backup bundle to Google Drive
schtasks /create /sc hourly /tn HishabBundle /tr "powershell -ExecutionPolicy Bypass -File C:\hishab\integration\scripts\bundle.ps1"
```

Check `C:\hishab\integration.log` now and then; if a run shows FAILED, post in the group.

## Sunday

- **10:00–14:00 shops** (WP-20): consent → statement export → 2–4 baki-khata photos →
  5-minute interview → one quote. Raw files go **only** into the private team Drive folder.
- **Afternoon:** Kaggle notebooks in `ml/` (RUNBOOK §5.5): GPU T4 x2, Internet on, Run All,
  **Save Version**, download `ml/artifacts/*`, commit on branch `wp-17-ml`, open a PR
  (`gh pr create --fill --base main`).
- **When WP-03 (privacy) is merged:** run the anonymiser on your shop files (the orchestrator
  posts the exact command), check the output has no names or numbers, commit only the
  anonymised files to `data/real_anonymised/` on branch `wp-20-data`, open a PR.

## Monday – Tuesday
- Keep PC-4 running; rerun any notebook the orchestrator asks for.
- Write the 3–5 interview quotes (English, anonymised) into `docs/submission/field-notes.md`.
- Help test the hosted site on your phone (mobile data, not Wi-Fi).

## Sleep
Sun 05:00–09:00 (then shops) · Mon 05:00–09:00 · Tue 08:00–10:00 (RUNBOOK §6).
