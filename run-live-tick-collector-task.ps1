# Daily scheduled-task action for the live tick collector (Deriv MT5).
#
# This script is what Task Scheduler runs every day.  It is deliberately
# SHORT-LIVED: it kills yesterday's collector instance, starts a fresh one
# DETACHED (so the task completes in seconds instead of blocking forever),
# then verifies the corpus is still growing via `tick-coverage --json` and
# persists the report under .data/ for later inspection.
#
# A raw task that points at collect-live-ticks.bat would never complete
# (the launcher blocks on WaitForExit), so Task Scheduler would skip every
# daily trigger after the first.  The restart-guard + detached start here is
# what makes the daily cadence actually work.
#
# Register with: setup-live-tick-task.ps1
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$appDir = $scriptDir
$pidFile = Join-Path $appDir ".data\live-tick-collector.pid"
$verifyDir = Join-Path $appDir ".data"
$verifyOutput = Join-Path $verifyDir "live_tick_task_verify.json"
$collectorBat = Join-Path $appDir "collect-live-ticks.bat"

# Task Scheduler runs the action with cwd = C:\Windows\System32, so every
# path that resolves against the engine root (tick-coverage, the collector
# CSV dir) must be anchored explicitly to the project dir.
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
    Add-Content -Path (Join-Path $verifyDir "live_tick_task.log") -Value $line
  } catch {}
}

# ── Daily-restart guard ────────────────────────────────────────────────
# Stop the previous collector instance if it is still alive (either via the
# recorded PID or a fresh process sweep for the CLI command).  This is the
# "restart every day" part: without it a stale collector from yesterday
# would keep appending and the daily task would spawn a duplicate.
function Stop-PreviousCollector {
  $stopped = @()

  # 1) Kill by recorded PID.
  if (Test-Path $pidFile) {
    $oldPid = (Get-Content $pidFile -ErrorAction SilentlyContinue).Trim()
    if ($oldPid) {
      try {
        $proc = Get-Process -Id $oldPid -ErrorAction Stop
        Stop-Process -Id $oldPid -Force -ErrorAction Stop
        $stopped += "pid=$oldPid"
      } catch {}
    }
    Remove-Item $pidFile -ErrorAction SilentlyContinue
  }

  # 2) Sweep for any python process running `synthetic_trader.cli collect-live-ticks`
  #    (catches orphans whose pid file was lost to a crash).
  try {
    $sweeps = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction Stop |
      Where-Object { $_.CommandLine -match "collect-live-ticks" -and $_.CommandLine -match "synthetic_trader" }
    foreach ($p in $sweeps) {
      try {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
        $stopped += "swept=$($p.ProcessId)"
      } catch {}
    }
  } catch {}

  if ($stopped.Count -gt 0) {
    Write-TaskLog "restart guard: stopped previous collector(s) [$($stopped -join ', ')]"
  } else {
    Write-TaskLog "restart guard: no previous collector running"
  }
  Start-Sleep -Milliseconds 800
  return $true
}

# Map a step's return value to the shared status vocabulary used by the
# [VERIFY] / [COLLECT] summary lines: $true -> ok (green), $false -> red,
# $null -> skipped.  Each step function returns $null when python is missing
# or the step is otherwise intentionally skipped, $false only on a real
# failure, $true on success.
function Convert-StepStatus {
  param([object]$Result)
  if ($null -eq $Result) { return 'skip' }
  if ($Result) { return 'ok' }
  return 'red'
}

# ── Start collector DETACHED ───────────────────────────────────────────
# Launch collect-live-ticks.bat in its own hidden window and do NOT wait for
# it.  The task must return promptly so the next daily trigger fires; the
# collector keeps running as an independent process and appends ticks to
# data/backfill/ across the whole day.
function Start-CollectorDetached {
  if (-not (Test-Path $collectorBat)) {
    throw "collector launcher not found: $collectorBat"
  }
  $launched = Start-Process -FilePath "cmd.exe" `
    -ArgumentList @("/c", "`"$collectorBat`"") `
    -WorkingDirectory $appDir `
    -WindowStyle Hidden `
    -PassThru
  Write-TaskLog "started collector (launcher cmd pid=$($launched.Id))"
  return $launched
}

# ── Scoring sweep: score-live-loop --once ─────────────────────────────
# After the collector restart + coverage check, sweep the live calls
# journal and append any newly-settled outcomes (target/stop/neither) to
# the outcomes journal.  This is what keeps the Stage-3 gate's per-trigger
# hit rates fresh without a separate resident scorer - the SAME daily task
# that compounds the tick corpus also compounds the outcomes journal, so
# the calibration health panel stays live in production.
#
# Non-fatal by design: a stale outcomes journal (Deriv unreachable, token
# missing) must not fail the collector task; the auto-scorer's own status
# file records the error for the dashboard.  Retries cover transient WS
# connect failures.
function Write-ScoringSweep {
  param([int]$Retries = 2, [int]$DelaySec = 5)
  $python = Get-PythonRunner
  if (-not $python) {
    Write-TaskLog "scoring sweep skipped: python not found on PATH"
    return $null   # skipped, not failed
  }
  $callsJournal = Join-Path $appDir "journals\live_calibration_calls.jsonl"
  $outcomesJournal = Join-Path $appDir "journals\live_calibration_outcomes.jsonl"
  $statusPath = Join-Path $appDir "data\auto_scorer.json"  # Task Scheduler runs with cwd = C:\Windows\System32, so every path is
  # anchored absolutely to the project dir (same pattern as the coverage
  # verification above).
  #
  # The engine writes advisory warnings to stderr (e.g. the Deriv-fallback
  # notice).  Under the script's $ErrorActionPreference = "Stop", Windows
  # PowerShell 5.1 turns native stderr into a terminating NativeCommandError
  # even when redirected with 2> — so the call runs with a LOCAL EAP
  # override and a try/catch.  The process exit code is the only thing that
  # decides success; stderr is captured to a file for the log.
  for ($i = 1; $i -le $Retries; $i++) {
    $errFile = Join-Path $verifyDir "score_sweep_stderr.txt"
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


# ── Band-geometry re-validation (weekly, internal gate) ──────────────
# Re-sweep the live band geometry around the current defaults so the live
# calls track the freshest corpus.  The CLI's own growth/elapsed gates make
# this CHEAP on the 6 of 7 days it skips (a JSON read + a span check); the
# full focused sweep only fires when the corpus grew ~6+ days since the
# last run.  Non-fatal by design: a re-validation hiccup must not fail the
# collector task.
function Write-BandRevalidate {
  $python = Get-PythonRunner
  if (-not $python) {
    Write-TaskLog "band-revalidate skipped: python not found on PATH"
    return $null   # skipped, not failed
  }
  $errFile = Join-Path $verifyDir "band_revalidate_stderr.txt"
  $prevEAP = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  $exitCode = 1
  $out = ""
  try {
    $out = & $python -m synthetic_trader.cli band-revalidate `
      --engine-root $appDir `
      --symbols R_75,R_100 2> $errFile | Out-String
    $exitCode = $LASTEXITCODE
  } catch {
    $exitCode = 1
    $out = $_.Exception.Message
  }
  $ErrorActionPreference = $prevEAP
  $oneLine = $out.Trim() -replace "\r?\n", " | "
  if ($exitCode -eq 0) {
    Write-TaskLog "band-revalidate ok: $oneLine"
    return $true
  }
  $stderr = ""
  if (Test-Path $errFile) {
    $stderr = (Get-Content $errFile -Raw -ErrorAction SilentlyContinue).Trim() -replace "\r?\n", " | "
  }
  Write-TaskLog "band-revalidate failed (exit $exitCode): $oneLine $stderr"
  return $false
}


# ── Head-to-head milestone verify (spans >= ~14d, internal gate) ──────
# Re-runs the full band vs fade vs momentum vs sniper comparison once the
# corpus crosses ~14 days (and again at ~18d when the band reaches 40+
# trades), so the +0.994R cell is re-tested at sample size without a manual
# step.  The CLI's internal span/growth gates make this a cheap skip on the
# days before the milestone; the heavy run only fires when the corpus grew.
# Non-fatal: a verify hiccup must not fail the collector task.
function Write-HeadToHeadVerify {
  $python = Get-PythonRunner
  if (-not $python) {
    Write-TaskLog "headtohead-verify skipped: python not found on PATH"
    return $null   # skipped, not failed
  }
  $errFile = Join-Path $verifyDir "headtohead_verify_stderr.txt"
  $prevEAP = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  $exitCode = 1
  $out = ""
  try {
    $out = & $python -m synthetic_trader.cli verify-headtohead `
      --engine-root $appDir `
      --symbol R_75 2> $errFile | Out-String
    $exitCode = $LASTEXITCODE
  } catch {
    $exitCode = 1
    $out = $_.Exception.Message
  }
  $ErrorActionPreference = $prevEAP
  $oneLine = $out.Trim() -replace "\r?\n", " | "
  if ($exitCode -eq 0) {
    Write-TaskLog "headtohead-verify ok: $oneLine"
    return $true
  }
  $stderr = ""
  if (Test-Path $errFile) {
    $stderr = (Get-Content $errFile -Raw -ErrorAction SilentlyContinue).Trim() -replace "\r?\n", " | "
  }
  Write-TaskLog "headtohead-verify failed (exit $exitCode): $oneLine $stderr"
  return $false
}


# ── Collector health summary (48h window, non-fatal) ──────────────────
# Summarizes .data/mt5_events.jsonl each morning so IPC-timeout recurrence
# after the single-flight guard (§44) is visible in the task log without a
# manual step.  Non-fatal: a report failure must not fail the collector task.
function Write-CollectorHealth {
  $python = Get-PythonRunner
  if (-not $python) {
    Write-TaskLog "collector-health skipped: python not found on PATH"
    return $null   # skipped, not failed
  }
  $prevEAP = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  $exitCode = 1
  $out = ""
  try {
    $out = & $python -m synthetic_trader.cli collector-health-report `
      --engine-root $appDir --hours 48 2>$null | Out-String
    $exitCode = $LASTEXITCODE
  } catch {
    $exitCode = 1
    $out = $_.Exception.Message
  }
  $ErrorActionPreference = $prevEAP
  $oneLine = ($out.Trim() -replace "\r?\n", " | ")
  if ($exitCode -eq 0) {
    Write-TaskLog "collector-health ok: $oneLine"
    return $true
  }
  Write-TaskLog "collector-health failed (exit $exitCode): $oneLine"
  return $false
}


# ── Verification via tick-coverage --json ──────────────────────────────
function Write-CoverageVerification {
  param([int]$Retries = 6, [int]$DelaySec = 10)
  $python = Get-PythonRunner
  if (-not $python) {
    Write-TaskLog "verification skipped: python not found on PATH"
    return
  }
  New-Item -ItemType Directory -Force -Path $verifyDir | Out-Null

  # Give the collector a few seconds to establish its MT5 feed before the
  # first coverage read (the CSV grows by appends; coverage needs only the
  # files to be present, but a retry loop also covers slow terminal startup).
  for ($i = 1; $i -le $Retries; $i++) {
    $json = & $python -m synthetic_trader.cli tick-coverage --engine-root $appDir --json 2>$null | Out-String
    if ($LASTEXITCODE -eq 0 -and $json -match '"symbols"') {
      $json = $json.Trim()
      Set-Content -Path $verifyOutput -Value $json -Encoding UTF8
      # Extract a one-line human summary from the JSON.
      try {
        $parsed = $json | ConvertFrom-Json
        foreach ($sym in $parsed.symbols) {
          $tfs = ($sym.horizons | ForEach-Object {
            "tf=$($_.timeframe_sec)s h=$($_.horizon_hours) windows=$($_.usable_windows)"
          }) -join ", "
          Write-TaskLog "coverage $($sym.symbol) ($($sym.ticks) ticks, $($sym.span_days) days): $tfs"
        }
      } catch {
        Write-TaskLog "coverage written to $verifyOutput (raw json)"
      }
      return $true
    }
    Start-Sleep -Seconds $DelaySec
  }
  Write-TaskLog "verification FAILED: tick-coverage --json did not return a report after $Retries tries"
  return $false
}

try {
  Write-TaskLog "task action starting (daily collector restart + scoring sweep)"
  # Each step's outcome feeds the machine-readable [COLLECT] summary line at
  # the end (same parseable format family as the verifier's [VERIFY] line, so
  # the email loop / dashboard parse both with one pattern).
  $stepResult = [ordered]@{}
  $stepResult['restart']          = if (Stop-PreviousCollector)   { 'ok' } else { 'red' }
  $stepResult['start']            = if (Start-CollectorDetached)  { 'ok' } else { 'red' }
  Start-Sleep -Seconds 3
  $verified = Write-CoverageVerification
  $stepResult['coverage'] = Convert-StepStatus $verified
  # Score any newly-settled live calls so the outcomes journal (and the
  # calibration health panel / Stage-3 gate) compounds on the same daily
  # schedule as the tick corpus.  Non-fatal - see the function comment.
  $stepResult['scoring']          = Convert-StepStatus (Write-ScoringSweep)
  # Re-validate the band geometry weekly (internal growth/elapsed gates
  # skip most days cheaply).  Non-fatal - see the function comment.
  $stepResult['band_revalidate']  = Convert-StepStatus (Write-BandRevalidate)
  # Re-run the full head-to-head at the 14-day milestone (internal span/
  # growth gates skip until then).  Non-fatal - see the function comment.
  $stepResult['headtohead']       = Convert-StepStatus (Write-HeadToHeadVerify)
  # Log the 48h IPC-timeout recurrence verdict each morning.  Non-fatal.
  $stepResult['health']           = Convert-StepStatus (Write-CollectorHealth)
  Write-TaskLog "task action complete"

  # Machine-readable status line — mirrors the [VERIFY] summary shape
  # (ok=/green=/red=/skip= + failed=names) so a single parse pattern covers
  # both schedulers.  ok=0 if ANY step went red (the line is the full health
  # picture; the exit code below stays policy: only coverage + hard errors
  # are Task-Scheduler-fatal, per the non-fatal step comments above).
  $nGreen = @($stepResult.Values | Where-Object { $_ -eq 'ok' }).Count
  $nRed   = @($stepResult.Values | Where-Object { $_ -eq 'red' }).Count
  $nSkip  = @($stepResult.Values | Where-Object { $_ -eq 'skip' }).Count
  $nSteps = $stepResult.Count
  $collectLine = "[COLLECT] summary ok=$(if ($nRed -eq 0) { 1 } else { 0 }) steps=$nSteps green=$nGreen red=$nRed skip=$nSkip"
  if ($nRed -gt 0) {
    $failedNames = @($stepResult.GetEnumerator() | Where-Object { $_.Value -eq 'red' } | ForEach-Object { $_.Key }) -join ','
    $collectLine += " failed=$failedNames"
  }
  Write-Host $collectLine
  Write-TaskLog $collectLine
  # Surface verification failures in Task Scheduler's Last Result so a
  # silent corpus stall is visible from the task list, not just the log.
  if (-not $verified) {
    exit 1
  }
  exit 0
} catch {
  Write-TaskLog "task action ERROR: $($_.Exception.Message)"
  exit 1
}
