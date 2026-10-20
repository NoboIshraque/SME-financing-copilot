#!/usr/bin/env bash
# Hourly database backup ON THE SERVER. Installed into the user's crontab by remote-deploy.sh.
# Keeps the newest 48 dumps in ~/hishab/backups. Off-server copy: see docs/DEPLOY.md.
# With ~/hishab/shared/backup.key present (create it once: `openssl rand -hex 32 >
# ~/hishab/shared/backup.key && chmod 600 ~/hishab/shared/backup.key`), each dump is encrypted
# with AES-256 (known risk R17); keep a copy of that key off the server, or the dumps are lost.
set -euo pipefail
umask 077
DEST="$HOME/hishab/backups"
KEY="$HOME/hishab/shared/backup.key"
mkdir -p "$DEST"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
if [[ -s "$KEY" ]]; then
  docker exec hishab-db-1 pg_dump -U hishab -d hishab --format=custom \
    | openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass "file:$KEY" \
    > "$DEST/hishab-$STAMP.dump.enc"
else
  echo "backup.sh: $KEY missing, writing an unencrypted dump" >&2
  docker exec hishab-db-1 pg_dump -U hishab -d hishab --format=custom \
    > "$DEST/hishab-$STAMP.dump"
fi
ls -1t "$DEST"/hishab-*.dump* | tail -n +49 | xargs -r rm -f
