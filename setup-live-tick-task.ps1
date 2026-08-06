# Setup script: register the daily live-tick collector scheduled task.
#
# Registers `run-live-tick-collector-task.ps1` (which in turn launches
# `collect-live-ticks.bat`) as a Windows scheduled task that fires once a
# day.  Each firing restarts the Blueberry MT5 tick collector (killing the
# previous day's instance first — the daily-restart guard), verifies the
# corpus is compounding via `tick-coverage --json`, and runs a
# `score-live-loop --once` sweep so the Stage-3 outcomes journal (and the
# calibration health panel) compounds on the same daily schedule.
#
# Usage:
#   .\setup-live-tick-task.ps1                  # register + baseline verify
#   .\setup-live-tick-task.ps1 -StartTime 02:30 # register, fire at 02:30 local
#   .\setup-live-tick-task.ps1 -TaskName MyTask # custom task name
#   .\setup-live-tick-task.ps1 -Unregister      # remove the task
#   .\setup-live-tick-task.ps1 -VerifyOnly      # just run tick-coverage --json
#   .\setup-live-tick-task.ps1 -SkipBaseline    # register without the coverage run
#
# Requires: Task Scheduler service + permissions to create a task for the
# current user (no admin needed for a per-user task with /RU current user).
param(
  [string]$TaskName = "SyntheticIndicesLiveTickCollector",
  [string]$StartTime = "00:30",
  [switch]$Unregister,
  [switch]$VerifyOnly,
  [switch]$SkipBaseline
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$appDir = $scriptDir
$taskAction = Join-Path $appDir "run-live-tick-collector-task.ps1"
$collectorBat = Join-Path $appDir "collect-live-ticks.bat"
$verifyDir = Join-Path $appDir ".data"
$baselineOutput = Join-Path $verifyDir "live_tick_task_setup_baseline.json"

function Get-PythonRunner {
  if (Get-Command python -ErrorAction SilentlyContinue) {
    return "python"
  }
  if (Get-Command py -ErrorAction SilentlyContinue) {
    return "py"
  }
  return $null
}

function Assert-Prerequisites {
  $missing = @()
  if (-not (Test-Path $collectorBat)) { $missing += "collect-live-ticks.bat" }
  if (-not (Test-Path $taskAction))   { $missing += "run-live-tick-collector-task.ps1" }
  if ((Get-PythonRunner) -eq $null)   { $missing += "python on PATH" }
  if ($missing.Count -gt 0) {
    Write-Host "ERROR: missing prerequisites: $($missing -join ', ')" -ForegroundColor Red
    exit 1
  }
  if ($StartTime -notmatch '^\d{2}:\d{2}$') {
    Write-Host "ERROR: -StartTime must be HH:MM (e.g. 00:30); got '$StartTime'" -ForegroundColor Red
    exit 1
  }
}

function Write-BaselineCoverage {
  New-Item -ItemType Directory -Force -Path $verifyDir | Out-Null
  $python = Get-PythonRunner
  try {
    $json = & $python -m synthetic_trader.cli tick-coverage --engine-root $appDir --json 2>$null | Out-String
    if ($LASTEXITCODE -eq 0 -and $json -match '"symbols"') {
      Set-Content -Path $baselineOutput -Value $json.Trim() -Encoding UTF8
      $parsed = $json | ConvertFrom-Json
      Write-Host "Baseline coverage written to $baselineOutput" -ForegroundColor Green
      foreach ($sym in $parsed.symbols) {
        $tfs = ($sym.horizons | ForEach-Object {
          "tf=$($_.timeframe_sec)s h=$($_.horizon_hours) windows=$($_.usable_windows)"
        }) -join ", "
        Write-Host "  $($sym.symbol) ($($sym.ticks) ticks, $($sym.span_days) days): $tfs" -ForegroundColor Cyan
      }
    } else {
      Write-Host "WARNING: tick-coverage --json returned nothing usable (is MT5/collector running?)." -ForegroundColor Yellow
    }
  } catch {
    Write-Host "WARNING: baseline coverage failed: $($_.Exception.Message)" -ForegroundColor Yellow
  }
}

if ($VerifyOnly) {
  Assert-Prerequisites
  Write-BaselineCoverage
  exit 0
}

if ($Unregister) {
  Write-Host "Removing scheduled task '$TaskName'..." -ForegroundColor Yellow
  schtasks /Delete /TN $TaskName /F
  if ($LASTEXITCODE -eq 0) {
    Write-Host "Task '$TaskName' removed." -ForegroundColor Green
  } else {
    Write-Host "No task removed (exit $LASTEXITCODE) - it may not exist." -ForegroundColor Yellow
  }
  exit 0
}

Assert-Prerequisites

# ── The schtasks registration command ──────────────────────────────────
# Fires once per day at StartTime (local time).  /SC DAILY + /ST gives the
# daily cadence; /F overwrites any existing registration so re-running setup
# is idempotent; /RU current user keeps it non-admin.  The action runs the
# SHORT wrapper (restart guard + detached collector + verification), NOT the
# blocking collect-live-ticks.bat directly — otherwise the task would never
# complete and later daily triggers would be skipped.
#
# Quoting: the task action and the project path both contain spaces, so the
# /TR value must be wrapped in escaped quotes (\"...\") — schtasks splits on
# spaces otherwise.  Build the raw command line and let cmd.exe hand it to
# schtasks so the escaping is exactly what schtasks expects.
$trValue = '\"powershell.exe\" -NoProfile -ExecutionPolicy Bypass -File \"' + $taskAction + '\"'
$schtasksCmd = 'schtasks /Create /TN "' + $TaskName + '" /TR "' + $trValue + '" /SC DAILY /ST ' + $StartTime + ' /F'

Write-Host "Registering scheduled task '$TaskName'..." -ForegroundColor Yellow
Write-Host "  command: $schtasksCmd" -ForegroundColor Gray
Write-Host "  schedule: daily at $StartTime (local)" -ForegroundColor Gray

cmd /c $schtasksCmd
$createExit = $LASTEXITCODE
if ($createExit -ne 0) {
  Write-Host "ERROR: schtasks /Create failed with exit code $createExit." -ForegroundColor Red
  exit 1
}

Write-Host "Task '$TaskName' registered." -ForegroundColor Green

# ── Verify the registration + baseline corpus state ────────────────────
Write-Host "`nVerifying registration:" -ForegroundColor Cyan
& schtasks /Query /TN $TaskName /V /FO LIST | Select-String -Pattern "TaskName|Status|Next Run|Schedule Type|Task To Run"

if (-not $SkipBaseline) {
  Write-Host "`nBaseline corpus coverage:" -ForegroundColor Cyan
  Write-BaselineCoverage
}

Write-Host "`nDone. The collector now restarts daily and each run also sweeps the" -ForegroundColor Green
Write-Host "  outcomes journal (score-live-loop --once); watch .data/live_tick_task.log for per-run results." -ForegroundColor Green
Write-Host "Manual one-off runs: .\collect-live-ticks.bat" -ForegroundColor Gray
exit 0
