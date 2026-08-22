<#
.SYNOPSIS
  Task-Scheduler wrapper for the MITEMSHUB_AI verifier (mql5/verify_all.ps1).

.DESCRIPTION
  Turns the one-command verify loop into an unattended, continuous check:

    1. Git gate: only verifies when HEAD moved since the last VERIFIED run
       (state in .data/mql5_verify_state.json).  Same-commit re-runs after a
       PASS are skipped in seconds; a FAIL is retried on the next tick.
    2. Runs mql5/verify_all.ps1 (compiles every Phase*Tests.mq5 in MetaEditor,
       runs each suite headlessly in the Strategy Tester, restores the
       terminal) and captures the full PASS/FAIL table.
    3. Logs to .data/mql5_verify_task.log (same convention as the tick
       collector) and persists the last output + state.
    4. Emails the PASS/FAIL table when a verification actually ran (never on
       a gate skip).  The subject is parsed from verify_all.ps1's
       machine-readable `[VERIFY] summary ok=...` line (so a red row like
       the P10-A STRICT trade-count breach is named without scraping the
       table), falling back to the human summary text when the machine line
       is absent (e.g. a pre-flight throw).  SMTP is configured via
       MQL5_VERIFY_SMTP_* environment variables, falling back to the inline
       block below; empty = disabled.

  Install with setup-mql5-verify-task.ps1 (registers the scheduled task and a
  post-commit git hook that fires it after every commit).

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File run-mql5-verify-task.ps1
  powershell -NoProfile -ExecutionPolicy Bypass -File run-mql5-verify-task.ps1 -Force
#>
[CmdletBinding()]
param(
  [string]$VerifyRunner = "",      # override for testing (defaults to mql5/verify_all.ps1)
  [string]$ProjectDir = "",        # auto-detected from this script's location
  [switch]$Force                    # ignore the git gate and always verify
)

$ErrorActionPreference = "Stop"

if (-not $ProjectDir) { $ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $VerifyRunner) { $VerifyRunner = Join-Path $ProjectDir "mql5\verify_all.ps1" }

$stateDir  = Join-Path $ProjectDir ".data"
$stateFile = Join-Path $stateDir "mql5_verify_state.json"
$taskLog   = Join-Path $stateDir "mql5_verify_task.log"
$lastOut   = Join-Path $stateDir "mql5_verify_last_output.txt"
$errFile   = Join-Path $stateDir "mql5_verify_stderr.txt"

# ---- SMTP config: environment override, then inline fallback --------------
# Leave SmtpServer empty to disable email entirely.  For Gmail use an app
# password, not your account password.
$SmtpServer = $env:MQL5_VERIFY_SMTP_SERVER
$SmtpPort   = if ($env:MQL5_VERIFY_SMTP_PORT) { [int]$env:MQL5_VERIFY_SMTP_PORT } else { 587 }
$SmtpFrom   = $env:MQL5_VERIFY_SMTP_FROM
$SmtpToRaw  = $env:MQL5_VERIFY_SMTP_TO
$SmtpUser   = $env:MQL5_VERIFY_SMTP_USER
$SmtpPass   = $env:MQL5_VERIFY_SMTP_PASS
$SmtpUseSsl = $true
if (-not $SmtpServer) { $SmtpServer = "" }   # inline defaults live here if you prefer them
if (-not $SmtpFrom)   { $SmtpFrom = "" }
if (-not $SmtpUser)   { $SmtpUser = "" }
if (-not $SmtpPass)   { $SmtpPass = "" }
$SmtpTo = @()
if ($SmtpToRaw) { $SmtpTo = @($SmtpToRaw -split "," | ForEach-Object { $_.Trim() } | Where-Object { $_ }) }

# ---- helpers ---------------------------------------------------------------
function Write-TaskLog {
  param([string]$Message)
  $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
  Write-Host $line
  try { Add-Content -Path $taskLog -Value $line } catch {}
}

function Read-State {
  if (-not (Test-Path $stateFile)) { return $null }
  try {
    return Get-Content $stateFile -Raw -ErrorAction Stop | ConvertFrom-Json
  } catch {
    Write-TaskLog "state file unreadable ($stateFile) - treating as no previous state: $($_.Exception.Message)"
    return $null
  }
}

function Write-State {
  param([string]$Commit, [string]$Status, [string]$Table)
  $now = (Get-Date).ToUniversalTime().ToString("o")
  $obj = [pscustomobject]@{
    last_attempted_commit = $Commit
    last_status           = $Status
    last_run_utc          = $now
    last_result_table     = $Table
  }
  try {
    $obj | ConvertTo-Json -Depth 4 | Set-Content -Path $stateFile -Encoding UTF8
  } catch {
    Write-TaskLog "failed to write state file: $($_.Exception.Message)"
  }
}

function Get-HeadCommit {
  $git = Get-Command git -ErrorAction SilentlyContinue
  if (-not $git) { return "" }
  $prevEAP = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try {
    $head = & git -C $ProjectDir rev-parse HEAD 2>$null | Out-String
    return $head.Trim()
  } catch {
    return ""
  } finally {
    $ErrorActionPreference = $prevEAP
  }
}

function Run-Verify {
  $pwsh = Join-Path $PSHOME "powershell.exe"
  $prevEAP = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  $out = ""
  $code = 1
  try {
    # Native stderr under EAP=Stop becomes a terminating NativeCommandError in
    # PS 5.1, so the verifier's stderr is redirected to a file (same pattern as
    # the tick-collector task) and the process exit code decides success.
    $out = & $pwsh -NoProfile -ExecutionPolicy Bypass -File $VerifyRunner 2> $errFile | Out-String
    $code = $LASTEXITCODE
  } catch {
    $code = 1
    $out = "WRAPPER ERROR launching verifier: $($_.Exception.Message)"
  } finally {
    $ErrorActionPreference = $prevEAP
  }
  $stderr = ""
  if (Test-Path $errFile) {
    $raw = Get-Content $errFile -Raw -ErrorAction SilentlyContinue
    if ($raw) { $stderr = $raw.Trim() }
  }
  return @{ exitCode = $code; output = $out; stderr = $stderr }
}

function Send-ResultEmail {
  param([string]$Status, [string]$Table, [string]$Stderr)
  if (-not $SmtpServer -or $SmtpTo.Count -eq 0) {
    Write-TaskLog "email skipped: SMTP not configured (set MQL5_VERIFY_SMTP_SERVER/TO, or inline defaults)"
    return
  }
  $subject = "MQL5 VERIFY: $Status"
  # Machine-readable [VERIFY] summary line wins when present (printed by
  # verify_all.ps1 on every full run): ok=1 -> all green, ok=0 -> red rows
  # named inline (failed=SuiteA,SuiteB).  Falls back to the human text for
  # runs that never reached the summary (pre-flight throw / wrapper error).
  if ($Table -match "\[VERIFY\] summary ok=(\d+) rows=\d+ green=\d+ red=(\d+) skip=\d+(?: failed=([^\s]+))?") {
    if ($Matches[1] -eq "0") {
      $subject += " - $($Matches[2]) suite(s) not green"
      if ($Matches[3]) { $subject += ": $($Matches[3])" }
    } else {
      $subject += " - all green"
    }
  }
  elseif ($Table -match "(\d+) suite\(s\) NOT green") { $subject += " - $($Matches[1]) suite(s) not green" }
  elseif ($Table -match "PRE-FLIGHT FAILED")     { $subject += " - pre-flight failed" }
  elseif ($Table -match "ALL SUITES PASSED")     { $subject += " - all green" }
  # The tick-collector task emits the SAME parseable format family
  # ([COLLECT] summary ok=... steps=... green=... red=... skip=... failed=...)
  # from its own daily schedule; scan its task log for the latest line and
  # append the collector's health to the subject so one email covers both
  # schedulers.
  $collectorLog = Join-Path $stateDir "live_tick_task.log"
  if (Test-Path $collectorLog) {
    $lastCollect = (Get-Content $collectorLog -ErrorAction SilentlyContinue |
      Select-String -Pattern '\[COLLECT\] summary ok=\d+ steps=\d+ green=\d+ red=\d+ skip=\d+' |
      Select-Object -Last 1).Line
    if ($lastCollect -match '\[COLLECT\] summary ok=(\d+) steps=\d+ green=\d+ red=(\d+) skip=\d+(?: failed=(\S+))?') {
      if ($Matches[1] -eq "0") {
        $subject += " | COLLECT: $($Matches[2]) step(s) red"
        if ($Matches[3]) { $subject += " ($($Matches[3]))" }
      } else {
        $subject += " | COLLECT: all steps green"
      }
    }
  }
  $bodyLines = @(
    "MQL5 MITEMSHUB_AI continuous verification - $Status",
    "ran:   $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
    "state: $($stateFile)",
    "",
    "---- RESULT TABLE ----"
  )
  $bodyLines += ($Table.Trim() -split "`r?`n")
  if ($Stderr) {
    $bodyLines += ""
    $bodyLines += "---- STDERR (tail) ----"
    $bodyLines += (($Stderr -split "`r?`n") | Select-Object -Last 25)
  }
  $body = $bodyLines -join "`r`n"

  $cred = $null
  if ($SmtpUser) {
    $secure = ConvertTo-SecureString $SmtpPass -AsPlainText -Force
    $cred = New-Object System.Management.Automation.PSCredential($SmtpUser, $secure)
  }
  try {
    Send-MailMessage -To $SmtpTo -From $SmtpFrom -Subject $subject -Body $body `
      -SmtpServer $SmtpServer -Port $SmtpPort -UseSsl:$SmtpUseSsl `
      -Credential $cred -ErrorAction Stop
    Write-TaskLog "email sent: '$subject' to $($SmtpTo -join ', ')"
  } catch {
    Write-TaskLog "email FAILED: $($_.Exception.Message)"
  }
}

# ---- main ------------------------------------------------------------------
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null

if (-not (Test-Path $VerifyRunner)) {
  Write-TaskLog "ERROR: verifier not found at $VerifyRunner"
  exit 1
}

$head  = Get-HeadCommit
$state = Read-State

# Git gate: same HEAD + last run PASS => nothing new to verify.
$skip = (-not $Force) -and $head -and $state -and `
        $state.last_attempted_commit -eq $head -and $state.last_status -eq "PASS"
if ($skip) {
  Write-TaskLog "skip: HEAD $head unchanged since verified run at $($state.last_run_utc) - nothing to do"
  exit 0
}
if (-not $head) {
  Write-TaskLog "warning: git not available or no commits - running ungated"
}

Write-TaskLog "starting MQL5 verify (HEAD=$head)..."
$r = Run-Verify
Set-Content -Path $lastOut -Value $r.output -Encoding UTF8

$status = if ($r.exitCode -eq 0) { "PASS" } else { "FAIL" }
Write-TaskLog "verify $status (exit $($r.exitCode))"
if ($r.stderr) {
  Write-TaskLog "verifier stderr: $(($r.stderr -split "`r?`n" | Select-Object -Last 3) -join ' | ')"
}

Write-State $head $status $r.output
Send-ResultEmail $status $r.output $r.stderr

if ($r.exitCode -eq 0) { exit 0 } else { exit 1 }
