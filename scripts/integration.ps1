# Hourly integration run on PC-4 (Labib's desktop): pull main, run all tests, log the result.
# Uses its own clone (C:\hishab\integration) so it never switches branches under Labib's work in C:\hishab\repo.
# Scheduled by: schtasks /create /sc hourly /tn HishabIntegration /tr "powershell -ExecutionPolicy Bypass -File C:\hishab\integration\scripts\integration.ps1"

$repo = "C:\hishab\integration"
$log = "C:\hishab\integration.log"
Set-Location $repo
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm"

git switch -q main 2>$null
git pull -q 2>&1 | Out-Null
$commit = (git rev-parse --short HEAD).Trim()

npm run setup *> $null
npm run test *> "C:\hishab\last-test-output.txt"
$result = if ($LASTEXITCODE -eq 0) { "PASSED" } else { "FAILED" }

Add-Content $log "[$stamp] main@$commit tests $result (details: C:\hishab\last-test-output.txt)"
