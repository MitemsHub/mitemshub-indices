# ============================================================
# sync-mt5.ps1 — Sync MQL5 files to ALL MT5 terminal directories
# ============================================================
# Project repo is the single source of truth.
# Edit .mq5 / .set files in mql5/MITEMSHUB_AI/, then run this script.
# ============================================================

param(
    [switch]$SetOnly,
    [switch]$Mq5Only
)

$ErrorActionPreference = "Stop"

$ProjectDir = Join-Path $PSScriptRoot "..\mql5\MITEMSHUB_AI"
$MT5Base = "$env:APPDATA\MetaQuotes\Terminal"

# Collect every MQL5 directory (Common + every terminal hash)
$mql5Dirs = @()
$mql5Dirs += Join-Path $MT5Base "Common\MQL5"
Get-ChildItem -Path $MT5Base -Directory | ForEach-Object {
    $mql5 = Join-Path $_.FullName "MQL5"
    if (Test-Path $mql5) { $mql5Dirs += $mql5 }
}

$synced = 0
$termCount = 0

foreach ($mql5Dir in $mql5Dirs) {
    $setsDir    = Join-Path $mql5Dir "Profiles\Sets"
    $expertsDir = Join-Path $mql5Dir "Experts"
    $mitemDir   = Join-Path $mql5Dir "Experts\MITEMSHUB_AI"

    foreach ($dir in @($setsDir, $expertsDir, $mitemDir)) {
        if (-not (Test-Path $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
        }
    }

    if (-not $Mq5Only) {
        Get-ChildItem -Path $ProjectDir -Filter "*.set" -File | ForEach-Object {
            Copy-Item $_.FullName $setsDir -Force
            Copy-Item $_.FullName $expertsDir -Force
            Copy-Item $_.FullName $mitemDir -Force
            $synced++
        }
    }

    if (-not $SetOnly) {
        Get-ChildItem -Path $ProjectDir -Filter "*.mq5" -File | ForEach-Object {
            Copy-Item $_.FullName $expertsDir -Force
            Copy-Item $_.FullName $mitemDir -Force
            $synced++
        }
    }

    $termCount++
}

Write-Host "Synced $synced file(s) to $termCount MT5 instance(s)." -ForegroundColor Yellow
Write-Host "Restart MT5 or recompile the EA for changes to take effect." -ForegroundColor DarkYellow
