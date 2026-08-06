# check-tick-task-health.ps1
#
# Morning health check for the daily tick-collector task.  Runs the Python
# check (tick-task-health) and, when any warning fires, prints a loud summary
# and optionally sends an email (configure SMTP below).  For a desktop toast,
# install BurntToast and uncomment the toast block at the bottom.
#
# Schedule it with Task Scheduler, e.g. every morning at 08:00:
#   schtasks /Create /TN SyntheticIndicesTickHealth /SC DAILY /ST 08:00 ^
#     /TR "powershell -NoProfile -ExecutionPolicy Bypass -File ^
#     \"C:\path\to\check-tick-task-health.ps1\"" /F
#
# Exit code: 0 = healthy, 1 = warnings fired (useful for chained alerting).

$ErrorActionPreference = "Continue"

# ── Config ────────────────────────────────────────────────────────────────
$ProjectDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonRunner = if (Get-Command python -ErrorAction SilentlyContinue) { "python" }
                elseif (Get-Command py -ErrorAction SilentlyContinue) { "py" }
                else { $null }

# Email (leave $SmtpServer empty to disable email):
$SmtpServer   = ""            # e.g. "smtp.gmail.com"
$SmtpPort     = 587
$SmtpFrom     = ""            # sender address
$SmtpTo       = @()           # e.g. @("you@example.com")
$SmtpUser     = ""            # auth user (often = From)
$SmtpPass     = ""            # app password / token
$SmtpUseSsl   = $true

if (-not $PythonRunner) {
  Write-Host "ERROR: python not found on PATH"
  exit 1
}

# ── Run the check ─────────────────────────────────────────────────────────
$json = & $PythonRunner -m synthetic_trader.cli tick-task-health `
  --engine-root $ProjectDir --json 2>$null | Out-String
$exitCode = $LASTEXITCODE

$report = $null
try { $report = $json | ConvertFrom-Json } catch { }

if ($null -eq $report) {
  Write-Host "ERROR: tick-task-health did not return JSON (exit $exitCode)"
  exit 1
}

$status = if ($report.healthy) { "OK" } else { "WARNINGS" }
Write-Host "TICK-COLLECTOR HEALTH: $status (exit $exitCode)"

if ($report.healthy) {
  exit 0
}

# ── Warnings fired: print the details ─────────────────────────────────────
Write-Host "`nWARNINGS:"
foreach ($w in $report.warnings) { Write-Host "  - $w" }
Write-Host "`nSymbol detail:"
foreach ($s in $report.symbols) {
  if ($s.flat) { Write-Host "  $($s.symbol): FLAT - $($s.flat_reason)" }
}

# ── Optional email alert ──────────────────────────────────────────────────
if ($SmtpServer -and $SmtpTo.Count -gt 0) {
  $bodyLines = @(
    "TICK-COLLECTOR HEALTH: $status",
    "checked: $(Get-Date -Format 'yyyy-MM-dd HH:mm')",
    "task last action: $($report.task.last_action_age_hours)h ago",
    "",
    "WARNINGS:"
  )
  foreach ($w in $report.warnings) { $bodyLines += "  - $w" }
  $bodyLines += ""
  foreach ($s in $report.symbols) {
    $state = if ($s.flat) { "FLAT" } else { "ok" }
    $bodyLines += "  $($s.symbol): $state ($($s.ticks_latest) ticks)"
  }
  $body = $bodyLines -join "`r`n"

  $cred = $null
  if ($SmtpUser) {
    $secure = ConvertTo-SecureString $SmtpPass -AsPlainText -Force
    $cred = New-Object System.Management.Automation.PSCredential($SmtpUser, $secure)
  }
  try {
    Send-MailMessage -To $SmtpTo -From $SmtpFrom -Subject `
      "TICK-COLLECTOR ALERT: $status" -Body $body `
      -SmtpServer $SmtpServer -Port $SmtpPort -UseSsl:$SmtpUseSsl `
      -Credential $cred -ErrorAction Stop
    Write-Host "`nEmail alert sent to $($SmtpTo -join ', ')"
  } catch {
    Write-Host "`nEmail FAILED: $($_.Exception.Message)"
  }
}

# ── Optional desktop toast (requires BurntToast module) ───────────────────
# if (Get-Module -ListAvailable -Name BurntToast) {
#   Import-Module BurntToast
#   New-BurntToastNotification -Text "Tick collector: $status",
#     ($report.warnings -join '; ') | Out-Null
# }

exit 1
