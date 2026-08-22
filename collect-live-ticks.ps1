# Continuous live tick collection service launcher (Deriv MT5 terminal).
# Appends real SYN75/SYN100 ticks to data/backfill/ across days/sessions.
#
# Run with the Deriv MT5 terminal open and logged in.  Stops with Ctrl+C
# or via the stop-live-tick-collector.ps1 script.
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$appDir = $scriptDir
$pidFile = Join-Path $appDir ".data\live-tick-collector.pid"

function Get-PythonRunner {
  if (Get-Command python -ErrorAction SilentlyContinue) {
    return "python"
  }
  if (Get-Command py -ErrorAction SilentlyContinue) {
    return "py"
  }
  return $null
}

$python = Get-PythonRunner
if (-not $python) {
  Write-Host "ERROR: python not found on PATH. Install Python 3.10+ and retry." -ForegroundColor Red
  exit 1
}

New-Item -ItemType Directory -Force -Path (Join-Path $appDir ".data") | Out-Null

# If a previous instance is still running, stop it first.
if (Test-Path $pidFile) {
  $oldPid = (Get-Content $pidFile -ErrorAction SilentlyContinue).Trim()
  if ($oldPid -and (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) {
    Write-Host "Stopping previous collector instance (PID $oldPid)..."
    Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 500
  }
}

Write-Host "Starting live tick collection (SYN75/SYN100 -> data/backfill/)..."
Write-Host "Keep the Deriv MT5 terminal open. Press Ctrl+C to stop."

$proc = Start-Process -FilePath $python -ArgumentList @(
  "-m", "synthetic_trader.cli", "collect-live-ticks",
  "--symbols", "R_75,R_100",
  "--output-dir", "data/backfill",
  "--status-path", "data/live_tick_collector.json"
) -WorkingDirectory $appDir -NoNewWindow -PassThru

Set-Content -Path $pidFile -Value $proc.Id

try {
  $proc.WaitForExit()
} finally {
  if (Test-Path $pidFile) {
    Remove-Item $pidFile -ErrorAction SilentlyContinue
  }
}

if ($proc.ExitCode -ne 0) {
  Write-Host "Collector exited with code $($proc.ExitCode)." -ForegroundColor Yellow
}
