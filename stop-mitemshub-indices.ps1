$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $scriptDir ".data\launcher-app.pid"

if (-not (Test-Path $pidFile)) {
  Write-Host "No launcher-started app process is currently recorded." -ForegroundColor Yellow
  exit 0
}

$trackedPid = Get-Content $pidFile -ErrorAction SilentlyContinue
if (-not $trackedPid) {
  Remove-Item $pidFile -ErrorAction SilentlyContinue
  Write-Host "No launcher-started app process is currently recorded." -ForegroundColor Yellow
  exit 0
}

try {
  Stop-Process -Id $trackedPid -Force -ErrorAction Stop
  Write-Host "MitemsHub Indices stopped." -ForegroundColor Green
} catch {
  Write-Host "The recorded app process is no longer running." -ForegroundColor Yellow
}

Remove-Item $pidFile -ErrorAction SilentlyContinue
