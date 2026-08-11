<#
.SYNOPSIS
  Setup script: register the unattended MQL5 continuous-verification loop.

.DESCRIPTION
  Registers `run-mql5-verify-task.ps1` (the git-gated wrapper around
  mql5/verify_all.ps1) as a Windows scheduled task AND installs a post-commit
  git hook that fires the task after every commit, so the MITEMSHUB_AI build
  verifies itself continuously:

    commit -> post-commit hook -> schtasks /Run -> wrapper (git gate) ->
    compile + Strategy Tester suites -> PASS/FAIL table -> optional email

  The hourly scheduled tick is the safety net (a commit made with a GUI tool
  or rebase still gets picked up); the hook provides the instant trigger.
  The wrapper's git gate makes every no-op tick a cheap skip, and retries a
  FAILed run on the next tick.

  Usage:
    .\setup-mql5-verify-task.ps1                     # register + install hook
    .\setup-mql5-verify-task.ps1 -Interval DAILY -StartTime 03:00
    .\setup-mql5-verify-task.ps1 -TaskName MyVerify  # custom task name
    .\setup-mql5-verify-task.ps1 -RunNow             # trigger once immediately
    .\setup-mql5-verify-task.ps1 -Unregister         # remove task + hook
    .\setup-mql5-verify-task.ps1 -NoHook             # schedule only, no git hook

  Requires: Task Scheduler service + permission to create a per-user task
  (no admin needed with /RU current user).
#>
param(
  [string]$TaskName = "MQL5Verify",
  [string]$Interval = "HOURLY",
  [string]$StartTime = "08:00",
  [switch]$Unregister,
  [switch]$RunNow,
  [switch]$NoHook,
  [switch]$SkipBaseline
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$appDir    = $scriptDir
$taskAction = Join-Path $appDir "run-mql5-verify-task.ps1"
$verifyPs1  = Join-Path $appDir "mql5\verify_all.ps1"
$gitDir     = Join-Path $appDir ".git"
$hookPath   = Join-Path $gitDir "hooks\post-commit"
$stateDir   = Join-Path $appDir ".data"

function Assert-Prerequisites {
  $missing = @()
  if (-not (Test-Path $taskAction)) { $missing += "run-mql5-verify-task.ps1" }
  if (-not (Test-Path $verifyPs1))  { $missing += "mql5/verify_all.ps1" }
  if (-not (Test-Path $gitDir))     { $missing += ".git (not a git repo)" }
  if ($missing.Count -gt 0) {
    Write-Host "ERROR: missing prerequisites: $($missing -join ', ')" -ForegroundColor Red
    exit 1
  }
  if ($Interval -notmatch '^(DAILY|HOURLY|MINUTE|WEEKLY)$') {
    Write-Host "ERROR: -Interval must be DAILY/HOURLY/MINUTE/WEEKLY; got '$Interval'" -ForegroundColor Red
    exit 1
  }
  if ($StartTime -notmatch '^\d{2}:\d{2}$') {
    Write-Host "ERROR: -StartTime must be HH:MM (e.g. 08:00); got '$StartTime'" -ForegroundColor Red
    exit 1
  }
}

function Install-Hook {
  param([string]$Name)
  $hookDir = Join-Path $gitDir "hooks"
  New-Item -ItemType Directory -Force -Path $hookDir | Out-Null
  # schtasks runs through PowerShell: MSYS/Git-Bash path-converts a bare
  # `/Run` argument into `R:\un`, so a direct call breaks inside git's
  # bundled sh.  Passing the whole command as one -Command string dodges
  # conversion.  Written WITHOUT a UTF-8 BOM - a BOM before #! breaks the
  # shebang on sh-based hook execution.
  $content = @(
    "#!/bin/sh",
    "# Fire the $Name scheduled task after every commit (installed by",
    "# setup-mql5-verify-task.ps1). Fire-and-forget: the task runs the",
    "# git-gated wrapper, so a PASSed HEAD is skipped and a FAIL is retried.",
    "powershell -NoProfile -Command 'schtasks /Run /TN $Name' >/dev/null 2>&1 || true",
    ""
  ) -join "`r`n"
  $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
  [System.IO.File]::WriteAllText($hookPath, $content, $utf8NoBom)
  Write-Host "post-commit hook installed: $hookPath" -ForegroundColor Green
}

function Remove-Hook {
  if (Test-Path $hookPath) {
    Remove-Item $hookPath -Force
    Write-Host "post-commit hook removed." -ForegroundColor Yellow
  } else {
    Write-Host "no post-commit hook to remove." -ForegroundColor Gray
  }
}

if ($Unregister) {
  Write-Host "Removing scheduled task '$TaskName'..." -ForegroundColor Yellow
  cmd /c "schtasks /Delete /TN `"$TaskName`" /F"
  if ($LASTEXITCODE -eq 0) {
    Write-Host "Task '$TaskName' removed." -ForegroundColor Green
  } else {
    Write-Host "No task removed (exit $LASTEXITCODE) - it may not exist." -ForegroundColor Yellow
  }
  Remove-Hook
  exit 0
}

Assert-Prerequisites

# ---- register the scheduled task ------------------------------------------
# The wrapper self-gates on git, so HOURLY ticks are cheap; the post-commit
# hook gives the instant "after each commit" trigger.  Quoting follows the
# tick-collector setup: /TR value wrapped in escaped quotes because the path
# contains spaces.
$trValue = '\"powershell.exe\" -NoProfile -ExecutionPolicy Bypass -File \"' + $taskAction + '\"'
$schtasksCmd = 'schtasks /Create /TN "' + $TaskName + '" /TR "' + $trValue + '" /SC ' + $Interval + ' /ST ' + $StartTime + ' /F'

Write-Host "Registering scheduled task '$TaskName'..." -ForegroundColor Yellow
Write-Host "  command: $schtasksCmd" -ForegroundColor Gray
Write-Host "  schedule: every $($Interval.ToLower()) from $StartTime (local)" -ForegroundColor Gray

cmd /c $schtasksCmd
if ($LASTEXITCODE -ne 0) {
  Write-Host "ERROR: schtasks /Create failed with exit code $LASTEXITCODE." -ForegroundColor Red
  exit 1
}
Write-Host "Task '$TaskName' registered." -ForegroundColor Green

# ---- git hook: fire the task after every commit ----------------------------
if (-not $NoHook) {
  Install-Hook $TaskName
} else {
  Write-Host "post-commit hook skipped (-NoHook)." -ForegroundColor Gray
}

# ---- verify registration ---------------------------------------------------
Write-Host "`nVerifying registration:" -ForegroundColor Cyan
& schtasks /Query /TN $TaskName /V /FO LIST 2>$null | Select-String -Pattern "TaskName|Status|Next Run|Schedule Type|Task To Run"

if (-not $SkipBaseline) {
  Write-Host "`nBaseline wrapper smoke run (git gate: only verifies on new commits):" -ForegroundColor Cyan
  & powershell -NoProfile -ExecutionPolicy Bypass -File $taskAction
  Write-Host "wrapper exit code: $LASTEXITCODE" -ForegroundColor Gray
}

if ($RunNow) {
  Write-Host "`nTriggering '$TaskName' once now..." -ForegroundColor Cyan
  cmd /c "schtasks /Run /TN `"$TaskName`""
  Write-Host "triggered (exit $LASTEXITCODE). Watch .data/mql5_verify_task.log." -ForegroundColor Green
}

Write-Host "`nDone. Continuous MQL5 verification is live:" -ForegroundColor Green
Write-Host "  - every commit fires the task via the post-commit hook" -ForegroundColor Green
Write-Host "  - hourly ticks catch commits made by GUI tools / rebases" -ForegroundColor Green
Write-Host "  - results in .data/mql5_verify_task.log; email via MQL5_VERIFY_SMTP_* env vars" -ForegroundColor Gray
Write-Host "  (manual run: .\run-mql5-verify-task.ps1 -Force)" -ForegroundColor Gray
exit 0
