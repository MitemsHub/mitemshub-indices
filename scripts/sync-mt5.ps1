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
    $setsMitem  = Join-Path $mql5Dir "Profiles\Sets\MITEMSHUB_AI"
    $expertsDir = Join-Path $mql5Dir "Experts"
    $mitemDir   = Join-Path $mql5Dir "Experts\MITEMSHUB_AI"
    $presetsDir = Join-Path $mql5Dir "Presets"

    foreach ($dir in @($setsDir, $setsMitem, $expertsDir, $mitemDir, $presetsDir)) {
        if (-not (Test-Path $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
        }
    }

    # Mirror the FULL EA source tree (mq5 + mqh includes + subfolders + .set)
    # into Experts\MITEMSHUB_AI — compiling root-only *.mq5 against stale/missing
    # includes produced the v26.13 TickFadeConfirm undeclared-identifier build
    # failure, and flat duplicates in Experts\ root caused the "MetaEditor
    # still shows v21.1" stale-build trap. The tree is the single deployed copy.
    Copy-Item -Path (Join-Path $ProjectDir '*') -Destination $mitemDir -Recurse -Force

    if (-not $Mq5Only) {
        Get-ChildItem -Path $ProjectDir -Filter "*.set" -File | ForEach-Object {
            Copy-Item $_.FullName $setsDir -Force
            Copy-Item $_.FullName $setsMitem -Force
            Copy-Item $_.FullName $presetsDir -Force
            $synced++
        }
    }

    $termCount++
}

Write-Host "Synced $synced file(s) to $termCount MT5 instance(s)." -ForegroundColor Yellow
Write-Host "Restart MT5 or recompile the EA for changes to take effect." -ForegroundColor DarkYellow
