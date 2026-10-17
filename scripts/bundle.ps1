# Hourly off-GitHub backup: the whole repo (all branches) as one git bundle in Google Drive.
# Keeps the newest 24 bundles. Scheduled on PC-4 by:
#   schtasks /create /sc hourly /tn HishabBundle /tr "powershell -ExecutionPolicy Bypass -File C:\hishab\integration\scripts\bundle.ps1"
# Restore: git clone <bundle file> restored-repo

param([string]$Dest = "")

$repo = "C:\hishab\integration"
if (-not $Dest) {
    # Google Drive for desktop: stream mode mounts G:\My Drive; mirror mode uses %USERPROFILE%\My Drive.
    $roots = @("G:\My Drive", (Join-Path $env:USERPROFILE "My Drive"))
    $root = $roots | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($root) { $Dest = Join-Path $root "hishab-backups" }
    else { $Dest = "C:\hishab\backups"; Write-Warning "Google Drive folder not found; saving locally to $Dest" }
}
New-Item -ItemType Directory -Force $Dest | Out-Null

Set-Location $repo
git fetch -q --all --prune
$stamp = Get-Date -Format "yyyyMMdd-HHmm"
$file = Join-Path $Dest "hishab-$stamp.bundle"
git bundle create $file --all 2>&1 | Out-Null

Get-ChildItem $Dest -Filter "hishab-*.bundle" | Sort-Object LastWriteTime -Descending |
    Select-Object -Skip 24 | Remove-Item -Force
