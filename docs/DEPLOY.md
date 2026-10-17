# Deploy Hishab from zero

One Linux server (2 vCPU, 4 GB RAM, Ubuntu 22.04+) with Docker. Everything else runs in
containers: PostgreSQL, the API, a background worker and Caddy (HTTPS + the web app).

## 1. Server

```bash
curl -fsSL https://get.docker.com | sudo sh        # skip if `docker compose version` works
sudo usermod -aG docker $USER && exit               # log in again afterwards
mkdir -p ~/hishab/shared ~/hishab/releases ~/hishab/backups
```

Open ports 22, 80 and 443. Point a DNS **A record** at the server's IP (ours:
`hishab.quadbits.net`).

## 2. Secrets (server only, never in git)

```bash
cp infra/.env.example ~/hishab/shared/.env    # from a copy of this repo
nano ~/hishab/shared/.env                      # fill in; generate keys with: openssl rand -hex 32
```

Required: `DEPLOY_DOMAIN`, `POSTGRES_PASSWORD`, `SECRET_KEY`, `VAULT_KEY`. Optional: LLM keys
(without them the copilot uses its deterministic planner), Sepolia RPC + key (without them
anchors are kept offline and labelled so).

## 3. Start

```bash
git clone <this repo> ~/hishab/releases/manual && cd ~/hishab/releases/manual
docker compose --env-file ~/hishab/shared/.env -f infra/docker-compose.yml up -d --build
ln -sfn "$PWD" ~/hishab/current
curl https://$DEPLOY_DOMAIN/api/health          # {"status":"ok", ...}
```

Caddy obtains the HTTPS certificate on first start (ports 80/443 must be reachable).

## 4. Automatic deploys

Every push to `main` that passes CI is shipped by `.github/workflows/deploy.yml`: it copies
the exact commit to `~/hishab/releases/<sha>`, rebuilds, checks
`https://<DEPLOY_DOMAIN>/api/health`, promotes it to `~/hishab/current`, and **rolls back**
to the previous release if the check fails. Repository secrets: `DEPLOY_HOST`, `DEPLOY_USER`,
`DEPLOY_SSH_KEY`, `DEPLOY_DOMAIN`.

## 5. Backups

`infra/backup.sh` runs hourly from cron (installed by each deploy) and keeps 48 `pg_dump`
files in `~/hishab/backups`. Restore:

```bash
docker exec -i hishab-db-1 pg_restore -U hishab -d hishab --clean < ~/hishab/backups/<file>.dump
```

## 6. Reachability from mainland China

The server is in Singapore. The web app loads nothing from third-party hosts (no Google Fonts,
CDNs or analytics): fonts and assets are bundled, and an automated browser test fails if any
page contacts another host. Measured access from mainland cities: `docs/submission/evidence/china.md`.
