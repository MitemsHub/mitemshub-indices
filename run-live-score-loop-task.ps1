# Daily scheduled-task action for the Stage-3 auto-scorer (score-live-loop).
#
# This script is what the dedicated scoring task runs every day.  It performs
# a single `score-live-loop --once` sweep — scoring every live call whose
# hold horizon has elapsed (target/stop/neither) and appending the outcomes
# to journals/live_calibration_outcomes.jsonl — so the Stage-3 gate's
# per-trigger hit rates and the calibration health panel stay fresh WITHOUT a
# resident scorer and WITHOUT depending on the collector task's own run.
#
# Why a separate task when the collector action already sweeps?  Separation
# of concerns: the collector task is about the TICK corpus (restart guard +
# detached start + coverage verify); this task is about the OUTCOMES journal.
# If the collector is down (stuck corpus, MT5 missing), the scorer still runs
# on its own schedule.  The sweep is idempotent (dedupe by (symbol,
# generated_at) against the existing outcomes journal), so the two daily
# sweeps never double-score.
#
# Register with: setup-live-score-task.ps1
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$appDir = $scriptDir
$verifyDir = Join-Path $appDir ".data"
$taskLog = Join-Path $verifyDir "live_score_task.log"
$callsJournal = Join-Path $appDir "journals\live_calibration_calls.jsonl"
$outcomesJournal = Join-Path $appDir "journals\live_calibration_outcomes.jsonl"
$statusPath = Join-Path $appDir "data\auto_scorer.json"

# Task Scheduler runs the action with cwd = C:\Windows\System32, so every
# path that resolves against the engine root must be anchored explicitly to
# the project dir.
New-Item -ItemType Directory -Force -Path $verifyDir | Out-Null

function Get-PythonRunner {
  if (Get-Command python -ErrorAction SilentlyContinue) {
    return "python"
  }
  if (Get-Command py -ErrorAction SilentlyContinue) {
    return "py"
  }
  return $null
}

function Write-TaskLog {
  param([string]$Message)
  $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
  Write-Host $line
  try {
    Add-Content -Path $taskLog -Value $line
  } catch {}
}

# ── Collector-health note (informational, never fatal) ─────────────────
# The task is scheduled AFTER the collector; if the collector's log shows no
# completed action in the last 26h the corpus may be stalled.  Log a warning
# so the scoring-task log surfaces it, but STILL run the sweep — scoring is
# independent of the tick corpus.
function Write-CollectorHealthNote {
  $collectorLog = Join-Path $verifyDir "live_tick_task.log"
  if (-not (Test-Path $collectorLog)) {
    Write-TaskLog "collector note: no collector log found - is the collector task registered?"
    return
  }
  try {
    $lines = @(Get-Content $collectorLog -ErrorAction Stop)
    $completeLines = @($lines | Where-Object { $_ -match "task action complete" })
    $failedLines  = @($lines | Where-Object { $_ -match "verification FAILED" })
    if ($completeLines.Count -eq 0) {
      Write-TaskLog "collector note: collector log has no completed action yet"
      return
    }
    # The log line starts with [yyyy-MM-dd HH:mm:ss]; parse it as local time
    # (Get-Date writes local time; same machine, so no off-by-hour).
    $lastComplete = $completeLines[-1]
    if ($lastComplete -match '^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]') {
      $lastTs = [datetime]::ParseExact($Matches[1], "yyyy-MM-dd HH:mm:ss", $null)
      $ageHours = ((Get-Date) - $lastTs).TotalHours
      # The collector logs "task action complete" EVEN on a failed day (it
      # exits 1 AFTER logging complete), so "last completed" alone can lie.
      # The most recent action failed iff a "verification FAILED" line is
      # newer than the SECOND-to-last "task action complete" line.
      $failed = $false
      if ($failedLines.Count -gt 0) {
        $lastFailed = $failedLines[-1]
        if ($lastFailed -match '^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]') {
          $failedTs = [datetime]::ParseExact($Matches[1], "yyyy-MM-dd HH:mm:ss", $null)
          if ($completeLines.Count -eq 1) {
            $failed = $true  # only one completed action ever, and a FAILED line exists
          } else {
            $prevComplete = $completeLines[-2]
            if ($prevComplete -match '^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]') {
              $prevTs = [datetime]::ParseExact($Matches[1], "yyyy-MM-dd HH:mm:ss", $null)
              $failed = $failedTs -ge $prevTs
            }
          }
        }
      }
      if ($failed) {
        Write-TaskLog ("collector note: collector's most recent run FAILED verification " +
          "({0:0.0}h ago) - tick corpus may be stalled (see tick-task-health)" -f $ageHours)
      } elseif ($ageHours -gt 26) {
        Write-TaskLog ("collector note: collector last completed {0:0.0}h ago - tick corpus may be stalled (see tick-task-health)" -f $ageHours)
      } else {
        Write-TaskLog ("collector note: collector last completed {0:0.0}h ago - OK" -f $ageHours)
      }
    }
  } catch {
    Write-TaskLog "collector note: could not parse collector log: $($_.Exception.Message)"
  }
}

# ── The scoring sweep ──────────────────────────────────────────────────
# score-live-loop --once performs a single sweep and exits (cron-friendly).
# The engine writes advisory warnings to stderr; under $ErrorActionPreference
# = "Stop", Windows PowerShell 5.1 turns native stderr into a terminating
# NativeCommandError even when redirected — so the call runs with a LOCAL EAP
# override and try/catch (same pattern as the collector task).  The process
# exit code alone decides success.
function Invoke-ScoringSweep {
  param([int]$Retries = 3, [int]$DelaySec = 10)
  $python = Get-PythonRunner
  if (-not $python) {
    Write-TaskLog "scoring sweep skipped: python not found on PATH"
    return $false
  }
  for ($i = 1; $i -le $Retries; $i++) {
    $errFile = Join-Path $verifyDir "score_task_stderr.txt"
    $exitCode = 1
    $out = ""
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
    $oneLine = $out.Trim() -replace "\r?\n", " | "
    if ($exitCode -eq 0) {
      Write-TaskLog "scoring sweep ok: $oneLine"
      return $true
    }
    $stderr = ""
    if (Test-Path $errFile) {
      $stderr = (Get-Content $errFile -Raw -ErrorAction SilentlyContinue).Trim() -replace "\r?\n", " | "
    }
    Write-TaskLog "scoring sweep attempt $i/$Retries failed (exit $exitCode): $oneLine $stderr"
    Start-Sleep -Seconds $DelaySec
  }
  Write-TaskLog "scoring sweep FAILED after $Retries tries - outcomes journal may be stale"
  return $false
}

try {
  Write-TaskLog "score task action starting (daily scoring sweep)"
  Write-CollectorHealthNote
  $ok = Invoke-ScoringSweep
  Write-TaskLog "score task action complete"
  # Surface sweep failures in Task Scheduler's Last Result so a stale
  # outcomes journal is visible from the task list, not just the log.
  if (-not $ok) {
    exit 1
  }
  exit 0
} catch {
  Write-TaskLog "score task action ERROR: $($_.Exception.Message)"
  exit 1
}
