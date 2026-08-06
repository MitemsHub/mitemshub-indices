# Setup script: register the daily Stage-3 auto-scorer scheduled task.
#
# Registers `run-live-score-loop-task.ps1` as a Windows scheduled task that
# fires once a day, scheduled AFTER the tick-collector task
# (`SyntheticIndicesLiveTickCollector`, default 00:30) so the outcomes
# journal compounds on the same daily cadence as the tick corpus — WITHOUT
# manual CLI runs and WITHOUT depending on the collector task's own inline
# sweep.  Each firing runs one `score-live-loop --once` sweep (idempotent:
# dedupes by (symbol, generated_at), so the two daily sweeps never
# double-score).
#
# Usage:
#   .\setup-live-score-task.ps1                  # register at 00:45 + baseline sweep
#   .\setup-live-score-task.ps1 -StartTime 01:00 # custom time (validated HH:MM)
#   .\setup-live-score-task.ps1 -TaskName MyTask # custom task name
#   .\setup-live-score-task.ps1 -Unregister      # remove the task
#   .\setup-live-score-task.ps1 -VerifyOnly      # just run a scoring sweep
#   .\setup-live-score-task.ps1 -SkipBaseline    # register without the sweep
#
# Requires: Task Scheduler service + permissions to create a task for the
# current user (no admin needed for a per-user task with /RU current user).
param(
  [string]$TaskName = "SyntheticIndicesLiveAutoScorer",
  [string]$StartTime = "00:45",
  [switch]$Unregister,
  [switch]$VerifyOnly,
  [switch]$SkipBaseline
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$appDir = $scriptDir
$taskAction = Join-Path $appDir "run-live-score-loop-task.ps1"
$verifyDir = Join-Path $appDir ".data"
$setupOutput = Join-Path $verifyDir "live_score_task_setup.txt"
$callsJournal = Join-Path $appDir "journals\live_calibration_calls.jsonl"
$outcomesJournal = Join-Path $appDir "journals\live_calibration_outcomes.jsonl"
$statusPath = Join-Path $appDir "data\auto_scorer.json"

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
  if (-not (Test-Path $taskAction))  { $missing += "run-live-score-loop-task.ps1" }
  if ((Get-PythonRunner) -eq $null)  { $missing += "python on PATH" }
  if ($missing.Count -gt 0) {
    Write-Host "ERROR: missing prerequisites: $($missing -join ', ')" -ForegroundColor Red
    exit 1
  }
  if ($StartTime -notmatch '^\d{2}:\d{2}$') {
    Write-Host "ERROR: -StartTime must be HH:MM (e.g. 00:45); got '$StartTime'" -ForegroundColor Red
    exit 1
  }
}

# Run one real scoring sweep at setup time.  This proves the exact command
# the task will run works end-to-end AND compounds the outcomes journal
# immediately.  Non-fatal: Deriv/MT5 being unreachable must not block
# registration - the daily task will retry.
function Write-BaselineSweep {
  New-Item -ItemType Directory -Force -Path $verifyDir | Out-Null
  $python = Get-PythonRunner
  # Same gotcha as the task action: the engine writes ADVISORY warnings to
  # stderr (e.g. "MT5 not configured - using Deriv API fallback"), and under
  # $ErrorActionPreference = "Stop" Windows PowerShell 5.1 turns native
  # stderr into a terminating NativeCommandError even when redirected.  Run
  # with a LOCAL EAP override and decide success by the process exit code
  # alone; stderr goes to a file for inspection.
  $errFile = Join-Path $verifyDir "score_task_setup_stderr.txt"
  $out = ""
  $exitCode = 1
  $prevEAP = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try {
    $out = & $python -m synthetic_trader.cli score-live-loop --once `
      --calls-journal $callsJournal `
      --output $outcomesJournal `
      --status-path $statusPath 2> $errFile | Out-String
    $exitCode = $LASTEXITCODE
  } catch {
    $exitCode = 1
    $out = $_.Exception.Message
  }
  $ErrorActionPreference = $prevEAP
  if ($exitCode -eq 0) {
    Set-Content -Path $setupOutput -Value $out.Trim() -Encoding UTF8
    Write-Host "Baseline scoring sweep written to $setupOutput" -ForegroundColor Green
    $oneLine = $out.Trim() -replace "\r?\n", " | "
    Write-Host "  $oneLine" -ForegroundColor Cyan
  } else {
    $stderr = ""
    if (Test-Path $errFile) {
      $stderr = (Get-Content $errFile -Raw -ErrorAction SilentlyContinue).Trim() -replace "\r?\n", " | "
    }
    Write-Host "WARNING: baseline scoring sweep exited $exitCode (is MT5/Deriv reachable?). $stderr" -ForegroundColor Yellow
  }
}

if ($VerifyOnly) {
  Assert-Prerequisites
  Write-BaselineSweep
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
# Fires once per day at StartTime (local).  Default 00:45 puts it 15 minutes
# AFTER the collector task (00:30) so the scoring sweep runs once the tick
# corpus for the new day exists.  /SC DAILY + /ST gives the daily cadence;
# /F overwrites any existing registration so re-running setup is idempotent;
# /RU current user keeps it non-admin.
#
# Quoting: the task action and the project path both contain spaces, so the
# /TR value must be wrapped in escaped quotes (\") - schtasks splits on
# spaces otherwise.  Build the raw command line and let cmd.exe hand it to
# schtasks so the escaping is exactly what schtasks expects.
$trValue = '\"powershell.exe\" -NoProfile -ExecutionPolicy Bypass -File \"' + $taskAction + '\"'
$schtasksCmd = 'schtasks /Create /TN "' + $TaskName + '" /TR "' + $trValue + '" /SC DAILY /ST ' + $StartTime + ' /F'

Write-Host "Registering scheduled task '$TaskName'..." -ForegroundColor Yellow
Write-Host "  command: $schtasksCmd" -ForegroundColor Gray
Write-Host "  schedule: daily at $StartTime (local) - after the tick-collector task (00:30)" -ForegroundColor Gray

cmd /c $schtasksCmd
$createExit = $LASTEXITCODE
if ($createExit -ne 0) {
  Write-Host "ERROR: schtasks /Create failed with exit code $createExit." -ForegroundColor Red
  exit 1
}

Write-Host "Task '$TaskName' registered." -ForegroundColor Green

# ── Verify the registration + baseline scoring sweep ───────────────────
Write-Host "`nVerifying registration:" -ForegroundColor Cyan
& schtasks /Query /TN $TaskName /V /FO LIST | Select-String -Pattern "TaskName|Status|Next Run|Schedule Type|Task To Run"

if (-not $SkipBaseline) {
  Write-Host "`nBaseline scoring sweep:" -ForegroundColor Cyan
  Write-BaselineSweep
}

Write-Host "`nDone. The auto-scorer now runs daily at $StartTime - watch .data/live_score_task.log" -ForegroundColor Green
Write-Host "  for per-run results, and data/auto_scorer.json for the live status telemetry." -ForegroundColor Green
Write-Host "Manual one-off run: python -m synthetic_trader.cli score-live-loop --once" -ForegroundColor Gray
exit 0
