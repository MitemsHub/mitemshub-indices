# ============================================================
# sync-mt5.ps1 — Sync MQL5 files to ALL MT5 terminal directories
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
$MT5Base = "$env:APPDATA\MetaQuotes\Terminal"

# Find ALL terminal instances (Common + each hash directory)
$terminalDirs = @()
$terminalDirs += Join-Path $MT5Base "Common\MQL5"
Get-ChildItem -Path $MT5Base -Directory | Where-Object { $_.Name -match "^[A-F0-9]{32}$" -or $_.Name -eq "Community" } | ForEach-Object {
    $mql5 = Join-Path $_.FullName "MQL5"
    if (Test-Path $mql5) {
        $terminalDirs += $mql5
    }
}

$synced = 0
$targets = @()

foreach ($mql5Dir in $terminalDirs) {
    $setsDir    = Join-Path $mql5Dir "Profiles\Sets"
    $expertsDir = Join-Path $mql5Dir "Experts"
    $mitemDir   = Join-Path $mql5Dir "Experts\MITEMSHUB_AI"

    # Ensure target directories exist
    foreach ($dir in @($setsDir, $expertsDir, $mitemDir)) {
        if (-not (Test-Path $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
        }
    }

    $label = Split-Path (Split-Path (Split-Path $mql5Dir -Parent) -Parent) -Leaf
    if ($label -eq "Common") { $label = "Common" }

    # Sync .set files
    if (-not $Mq5Only) {
        $setFiles = Get-ChildItem -Path $ProjectDir -Filter "*.set" -File
        foreach ($f in $setFiles) {
            Copy-Item $f.FullName $setsDir -Force
            Copy-Item $f.FullName $expertsDir -Force
            Copy-Item $f.FullName $mitemDir -Force
        }
        $synced += $setFiles.Count
    }

    # Sync .mq5 files
    if (-not $SetOnly) {
        $mq5Files = Get-ChildItem -Path $ProjectDir -Filter "*.mq5" -File
        foreach ($f in $mq5Files) {
            Copy-Item $f.FullName $expertsDir -Force
            Copy-Item $f.FullName $mitemDir -Force
        }
        $synced += $mq5Files.Count
    }

    $targets += $label
}

Write-Host ""
Write-Host "Synced $synced file(s) to $($targets.Count) MT5 terminal instance(s):" -ForegroundColor Yellow
foreach ($t in $targets) {
    Write-Host "  - $t" -ForegroundColor DarkGray
}
Write-Host ""
Write-Host "Restart MT5 or recompile the EA for changes to take effect." -ForegroundColor DarkYellow
