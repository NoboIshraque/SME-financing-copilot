#!/usr/bin/env bash
# Hourly database backup ON THE SERVER. Installed into the user's crontab by remote-deploy.sh.
# Keeps the newest 48 dumps in ~/hishab/backups. Off-server copy: see docs/DEPLOY.md.
set -euo pipefail
DEST="$HOME/hishab/backups"
mkdir -p "$DEST"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
docker exec hishab-db-1 pg_dump -U hishab -d hishab --format=custom \
  > "$DEST/hishab-$STAMP.dump"
ls -1t "$DEST"/hishab-*.dump | tail -n +49 | xargs -r rm -f
