# ============================================================
# sync-mt5.ps1 — Sync MQL5 files to MT5 terminal directories
# ============================================================
# Usage:
#   .\scripts\sync-mt5.ps1              # sync all files
#   .\scripts\sync-mt5.ps1 -SetOnly     # sync only .set files
#   .\scripts\sync-mt5.ps1 -Mq5Only     # sync only .mq5 files
# ============================================================

param(
    [switch]$SetOnly,
    [switch]$Mq5Only
)

$ErrorActionPreference = "Stop"

$ProjectDir = Join-Path $PSScriptRoot "..\mql5\MITEMSHUB_AI"
$MT5Common = "$env:APPDATA\MetaQuotes\Terminal\Common\MQL5"

$SetsDir    = Join-Path $MT5Common "Profiles\Sets"
$ExpertsDir = Join-Path $MT5Common "Experts"
$MitemDir   = Join-Path $MT5Common "Experts\MITEMSHUB_AI"

# Ensure target directories exist
foreach ($dir in @($SetsDir, $ExpertsDir, $MitemDir)) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        Write-Host "Created: $dir" -ForegroundColor DarkGray
    }
}

$synced = 0

# Sync .set files
if (-not $Mq5Only) {
    $setFiles = Get-ChildItem -Path $ProjectDir -Filter "*.set" -File
    foreach ($f in $setFiles) {
        Copy-Item $f.FullName $SetsDir -Force
        Copy-Item $f.FullName $ExpertsDir -Force
        Copy-Item $f.FullName $MitemDir -Force
        Write-Host "  SET  $($f.Name)" -ForegroundColor Green
        $synced++
    }
}

# Sync .mq5 files
if (-not $SetOnly) {
    $mq5Files = Get-ChildItem -Path $ProjectDir -Filter "*.mq5" -File
    foreach ($f in $mq5Files) {
        Copy-Item $f.FullName $ExpertsDir -Force
        Copy-Item $f.FullName $MitemDir -Force
        Write-Host "  MQ5  $($f.Name)" -ForegroundColor Cyan
        $synced++
    }
}

Write-Host ""
Write-Host "Synced $synced file(s) to MT5 terminal directories:" -ForegroundColor Yellow
Write-Host "  Sets:    $SetsDir" -ForegroundColor DarkGray
Write-Host "  Experts: $ExpertsDir" -ForegroundColor DarkGray
Write-Host "  MITEM:   $MitemDir" -ForegroundColor DarkGray
Write-Host ""
Write-Host "Restart MT5 or recompile the EA for changes to take effect." -ForegroundColor DarkYellow
