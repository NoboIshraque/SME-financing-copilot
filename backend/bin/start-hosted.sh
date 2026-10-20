#!/bin/sh
# Start command for single-container hosts (Render, render.yaml): load the synthetic demo shops
# (idempotent), then serve on the host's $PORT.
set -e
python -m app.facts.seed
exec uvicorn --factory app.main:create_app --host 0.0.0.0 --port "${PORT:-8000}" \
  --proxy-headers --forwarded-allow-ips '*'
