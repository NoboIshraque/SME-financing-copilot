# Execution evidence: index (deliverable 06)

Everything here was produced by running the repository's own code. All business data is
**synthetic** (`data_mode: synthetic`), every run is offline (no model call, no network), and
secrets are redacted. Each file says how to regenerate it.

## Freeze record

| Item | Value |
| --- | --- |
| Code-freeze commit on `main` | _filled at freeze_ |
| CI run on that commit (lint, tests, audits, secret scan, Docker stack boot) | _filled at freeze_ |
| All-refs secret scan before the repository went public | _filled at freeze_ |
| Sepolia anchor transaction | none recorded: anchors in this evidence are offline (labelled `offline`) |
| Live-model traces | none: every copilot answer in the evidence was produced offline by the deterministic planner |

## Index

| Evidence | File | What it shows | Regenerate |
| --- | --- | --- | --- |
| Sandbox operation log | `operations/operation-log.md` (readable) and `operations/operation-log.jsonl` (one JSON object per step, with the SHA-256 of each full response) | 48 steps through the real FastAPI app: sign-in with TOTP; upload preview, commit and duplicate re-upload; cash forecast, gaps, alerts and a what-if; the provenance of a figure; financing match and lender check; the full EXECUTE path (draft, request, refused without and with a wrong step-up code, approved with a fresh code, executed, idempotent replay); injection attempts in Bangla, English and Chinese; cross-tenant and anonymous calls refused; audit chain verify and anchor; the mesh ring netted, approved, settled, sealed, verified and tamper-detected | `uv --directory backend run python ../scripts/evidence_operations.py` (exits 1 if any step returns an unexpected status or any network connection is attempted) |
| Test counts by area | `test-counts.md` | Backend (pytest) and web (Vitest) tests per area | `npm run evidence` |
| Full test runs | `test-runs/backend-pytest.txt`, `test-runs/web-vitest.txt` | The complete output of one backend and one web run | `cd backend && uv run pytest -q`; `cd web && npm test -- --run` |
| Worked examples | `../technical-documentation.md` §3.3-§3.9 and Appendix A | Forecast and what-if, true cost of four loans, the netting ring, analysis of one quarter, two copilot answers with every claim recomputed | Commands in Appendix A |
| Demo video | sent with the submission email (MP4); script in `../video-script.md` | The live app on the synthetic shops | Recording checklist in the script |
| CI history | GitHub Actions, workflow `CI` | Every pull request and every push to `main` | Runs automatically |

## What the evidence does not show

- No real shop data and no real users.
- No call to a hosted language model (offline mode); the copilot's critic and agreement steps run
  on their offline fallbacks, and no agreement is claimed.
- No public hosted instance.
- No on-chain transaction: anchors are offline.

## At code freeze (checklist)

1. Tag the freeze commit on `main`; record it and its CI run above.
2. On a clean checkout of that commit: `npm run setup`, `npm run test` (save both outputs to
   `test-runs/`), `npm run evidence`, and the operation-log command above.
3. Re-check the status tables in `../technical-documentation.md` and
   `../security-self-assessment.md` against what was merged.
4. Run the all-refs secret scan (`gitleaks git --log-opts="--all" --redact`) and record the
   result above before the repository is made public.
