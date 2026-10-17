# Autosave: commit and push the current branch every few minutes.
# Usage (leave running in its own PowerShell window, from the repo root):
#   powershell -ExecutionPolicy Bypass -File scripts\autosave.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\autosave.ps1 -IntervalSeconds 180

param([int]$IntervalSeconds = 300)

$ErrorActionPreference = "Continue"
$repo = git rev-parse --show-toplevel 2>$null
if (-not $repo) { Write-Host "Run this from inside the repo." -ForegroundColor Red; exit 1 }
Set-Location $repo
$log = Join-Path $repo ".autosave.log"

Write-Host "Autosave every $IntervalSeconds s in $repo. Ctrl+C to stop." -ForegroundColor Green

while ($true) {
    $branch = (git rev-parse --abbrev-ref HEAD).Trim()
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

    if ($branch -eq "main" -or $branch -eq "HEAD") {
        Write-Host "[$stamp] On '$branch' - autosave skipped (work on a WP branch)." -ForegroundColor Yellow
    }
    elseif ((Test-Path (Join-Path $repo ".git\rebase-merge")) -or (Test-Path (Join-Path $repo ".git\rebase-apply")) -or (Test-Path (Join-Path $repo ".git\MERGE_HEAD"))) {
        Write-Host "[$stamp] Rebase/merge in progress - autosave paused." -ForegroundColor Yellow
    }
    else {
        git add -A
        # Safety net: never commit env files even if .gitignore was edited.
        $staged = git diff --cached --name-only
        $leaks = $staged | Where-Object { $_ -match '(^|/)\.env($|\.)' -and $_ -notmatch '\.env\.example$' }
        if ($leaks) {
            git reset -q -- $leaks
            Write-Host "[$stamp] Refused to commit: $($leaks -join ', ')" -ForegroundColor Red
        }
        $pending = git diff --cached --name-only
        if ($pending) {
            git commit -q -m "autosave($branch): $stamp" --no-verify
            Write-Host "[$stamp] Committed $(@($pending).Count) file(s) on $branch." -ForegroundColor Cyan
        }
        $push = git push -q -u origin $branch 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[$stamp] Push failed (offline?). Will retry next round." -ForegroundColor Yellow
            Add-Content $log "[$stamp] push failed: $push"
        }
    }
    Start-Sleep -Seconds $IntervalSeconds
}
