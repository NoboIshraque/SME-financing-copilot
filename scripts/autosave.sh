#!/usr/bin/env bash
# Autosave for Linux/macOS/Git Bash/the server: commit and push the current branch every few minutes.
# Usage: bash scripts/autosave.sh [interval_seconds]
set -u
INTERVAL="${1:-300}"
cd "$(git rev-parse --show-toplevel)" || exit 1
echo "Autosave every ${INTERVAL}s in $(pwd). Ctrl+C to stop."
while true; do
  branch="$(git rev-parse --abbrev-ref HEAD)"
  stamp="$(date '+%Y-%m-%d %H:%M:%S')"
  if [ "$branch" = "main" ] || [ "$branch" = "HEAD" ]; then
    echo "[$stamp] On '$branch' - skipped (work on a WP branch)."
  elif [ -d .git/rebase-merge ] || [ -d .git/rebase-apply ] || [ -f .git/MERGE_HEAD ]; then
    echo "[$stamp] Rebase/merge in progress - paused."
  else
    git add -A
    leaks="$(git diff --cached --name-only | grep -E '(^|/)\.env($|\.)' | grep -v '\.env\.example$' || true)"
    if [ -n "$leaks" ]; then git reset -q -- $leaks; echo "[$stamp] Refused to commit: $leaks"; fi
    if [ -n "$(git diff --cached --name-only)" ]; then
      git commit -q -m "autosave($branch): $stamp" --no-verify && echo "[$stamp] Committed on $branch."
    fi
    git push -q -u origin "$branch" 2>>.autosave.log || echo "[$stamp] Push failed (offline?), will retry."
  fi
  sleep "$INTERVAL"
done
