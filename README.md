# Hishab — SME Finance Copilot

FinTechathon 2026 (Shenzhen) International Track, Topic E. A mobile-first copilot that helps a
small Bangladeshi business match financing options, manage cash flow with early alerts, and
analyse its finances. **Code computes every number; the model only explains it.**

> Status: under active development (deadline 20 Oct 2026). Data shown in demo mode is synthetic
> and labelled as such.

## Quick start (Windows PowerShell, macOS or Linux)

Prerequisites: Git, Node.js 22, [uv](https://docs.astral.sh/uv/) (uv installs Python 3.12 for you).

```
npm run setup      # install backend and web dependencies
npm run test       # all backend + web unit tests (offline: no LLM, no network)
npm run dev        # API on http://localhost:8000, web on http://localhost:5173
npm run e2e        # browser tests (with `npm run dev` running)
```

Configuration: copy `backend/.env.example` to `backend/.env`. Without keys the app runs on
recorded model responses (`LLM_MODE=fixtures`) and an offline chain anchor (`CHAIN_MODE=offline`).

## Layout

| Path | What |
| --- | --- |
| `backend/app/contracts/` | Frozen shared schemas (exported to `docs/api/contracts.json`) |
| `backend/app/engines/` | Deterministic engines: cash, receivables, financing, analysis, mesh, market |
| `backend/app/llm/`, `backend/app/agents/` | Model gateway (anonymised payloads only), agents, checker, critic |
| `backend/app/security/` | Roles, permission tiers, approvals, hash-chained audit log |
| `web/` | React + TypeScript PWA (English, বাংলা, 中文) |
| `data/synthetic/` | Deterministic synthetic SME universe (5 Dhaka SMEs, 18 months) |
| `docs/` | Plan, features, runbook, submission documents |

Team: Nobo Ishraque (lead), Amdad, Labib — Bangladesh University of Professionals.
