#!/usr/bin/env bash
# Runs ON THE SERVER (piped over ssh by .github/workflows/deploy.yml).
#   remote-deploy.sh <sha>     build and start that release
#   remote-deploy.sh rollback  restart the last promoted release (~/hishab/current)
set -euo pipefail
BASE="$HOME/hishab"
ENV_FILE="$BASE/shared/.env"
[ -f "$ENV_FILE" ] || { echo "missing $ENV_FILE (copy infra/.env.example there)"; exit 1; }

if [ "${1:-}" = "rollback" ]; then
  REL="$(readlink -f "$BASE/current" || true)"
  [ -n "$REL" ] && [ -d "$REL" ] || { echo "no previous release to roll back to"; exit 1; }
else
  REL="$BASE/releases/$1"
fi

cd "$REL"
docker compose --env-file "$ENV_FILE" -f infra/docker-compose.yml up -d --build --remove-orphans
# The hosted demo needs its synthetic shops in the ledger, or Today and Cash abstain. The seed is
# idempotent; a deployment with DEMO_MODE=false (real data) never gets them.
if ! grep -qiE '^DEMO_MODE=(false|0|no)$' "$ENV_FILE"; then
  docker compose --env-file "$ENV_FILE" -f infra/docker-compose.yml exec -T api python -m app.facts.seed
fi
docker image prune -f >/dev/null
docker compose --env-file "$ENV_FILE" -f infra/docker-compose.yml ps

# Hourly backups (idempotent: replaces any older DecisionGuard line in the crontab).
( crontab -l 2>/dev/null | grep -v 'hishab-backup' ; \
  echo "17 * * * * $BASE/current/infra/backup.sh >> $BASE/backups.log 2>&1 # hishab-backup" ) | crontab -
