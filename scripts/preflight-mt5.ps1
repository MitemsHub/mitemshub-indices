# ============================================================
# preflight-mt5.ps1 — one command before trusting the deploy:
#   [1/3] sync repo -> all MT5 terminals (incl. prune + build gate)
#   [2/3] verify deployment (repo hash match + build freshness)
#   [3/3] tail the live EA's latest Experts-log lines
# Exit code 0 only if all three pass.
# ============================================================
param(
    [int]$Tail = 15
)

$ErrorActionPreference = "Stop"

# --- [1/3] SYNC (build gate inside aborts on stale/missing live .ex5) ---
Write-Host "== [1/3] SYNC ==" -ForegroundColor Cyan
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "sync-mt5.ps1")
if ($LASTEXITCODE -ne 0) {
    Write-Host "`nPREFLIGHT FAILED at sync/build gate - see DEPLOY FAILED above." -ForegroundColor Red
    exit 1
}

# --- [2/3] VERIFY (full audit; show only problems + verdict) ---
Write-Host "`n== [2/3] VERIFY ==" -ForegroundColor Cyan
$audit = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "verify-mt5-deploy.ps1")
$problems = $audit | Where-Object {
    $_ -cmatch "STALE|MISSING in terminal|ORPHAN|mismatch=[1-9]|missing=[1-9]|orphan=[1-9]"
}
$verdict = ($audit | Where-Object { $_ -match "RESULT:" } | Select-Object -Last 1)
if ($problems) { $problems | ForEach-Object { Write-Host $_ } }
Write-Host $verdict -ForegroundColor ($(if ($verdict -match "ALL OK") { "Green" } else { "Red" }))
if ($verdict -notmatch "ALL OK") {
    Write-Host "`nPREFLIGHT FAILED at verify - see problem lines above." -ForegroundColor Red
    exit 1
}

# --- [3/3] LIVE EA LOG (most recently written terminal log) ---
Write-Host "`n== [3/3] LIVE EA LOG (last $Tail lines) ==" -ForegroundColor Cyan
$logDate = (Get-Date).ToString("yyyyMMdd")
$latest = Get-ChildItem "$env:APPDATA\MetaQuotes\Terminal\*\MQL5\Logs\$logDate.log" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($latest) {
    $termName = $latest.FullName.Split('\')[5]
    Write-Host ("most recent log: " + $termName + " (last write " + $latest.LastWriteTime.ToString("HH:mm:ss") + ")")
    Get-Content $latest.FullName -Tail $Tail | ForEach-Object { Write-Host ($_ -replace "`r", "") }
}
else {
    Write-Host "no Experts log for today - MT5 may not be running." -ForegroundColor DarkYellow
}

Write-Host "`nPREFLIGHT OK - deploy is clean and the EA is logging." -ForegroundColor Green
