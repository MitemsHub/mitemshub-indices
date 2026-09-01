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

$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..\mql5\MITEMSHUB_AI")).Path
$MT5Base = "$env:APPDATA\MetaQuotes\Terminal"

# Collect every MQL5 directory (Common + every terminal hash)
$mql5Dirs = @()
$mql5Dirs += Join-Path $MT5Base "Common\MQL5"
Get-ChildItem -Path $MT5Base -Directory | ForEach-Object {
    $mql5 = Join-Path $_.FullName "MQL5"
    if (Test-Path $mql5) { $mql5Dirs += $mql5 }
}
$mql5Dirs = $mql5Dirs | Select-Object -Unique

$synced = 0
$pruned = 0
$termCount = 0
$deployFailures = @()

# Repo-relative paths — the prune pass compares terminal files against this list.
$repoFiles = Get-ChildItem -Path $ProjectDir -Recurse -File | ForEach-Object {
    $_.FullName.Substring($ProjectDir.Length + 1)
}

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

    # --------------------------------------------------------
    # Prune pass — remove files the repo no longer has, so the
    # terminals can never resurrect stale copies by themselves.
    # --------------------------------------------------------

    # 1) Orphaned sources/presets inside the mirrored tree (deleted from repo).
    Get-ChildItem -Path $mitemDir -Recurse -File |
        Where-Object { $_.Extension -in ".mqh", ".mq5", ".set" } |
        Where-Object { $repoFiles -notcontains $_.FullName.Substring($mitemDir.Length + 1) } |
        ForEach-Object {
            Remove-Item $_.FullName -Force
            $pruned++
        }

    # 2) Orphaned compiled binaries: a .ex5 whose .mq5 no longer exists in the
    #    repo tree can never be rebuilt from source — it is a zombie build.
    Get-ChildItem -Path $mitemDir -Recurse -File -Filter "*.ex5" |
        Where-Object {
            $srcRel = $_.FullName.Substring($mitemDir.Length + 1) -replace "\.ex5$", ".mq5"
            $repoFiles -notcontains $srcRel
        } |
        ForEach-Object {
            Remove-Item $_.FullName -Force
            $pruned++
        }

    # 2b) Stale compiled binaries: a .ex5 older than its .mq5 can never be the
    #     current build — the terminal would silently keep running the old
    #     code (the "MetaEditor still shows v21.1" trap class). Delete the
    #     stale binary so it cannot accumulate or be reattached; the build
    #     gate below then reports the live EA as NOT BUILT until recompiled.
    Get-ChildItem -Path $mitemDir -Recurse -File -Filter "*.ex5" |
        ForEach-Object {
            $src = [IO.Path]::ChangeExtension($_.FullName, ".mq5")
            if ((Test-Path $src) -and ((Get-Item $_.FullName).LastWriteTime -lt (Get-Item $src).LastWriteTime)) {
                Remove-Item $_.FullName -Force
                $pruned++
            }
        }

    # 3) Flat Experts\ root leftovers: the script no longer deploys there, so
    #    any MitemshubAI* binary/preset sitting in the root is stale by design
    #    (the "MetaEditor still shows v21.1" trap). Other EAs are untouched.
    Get-ChildItem -Path $expertsDir -File -Filter "MitemshubAI*" |
        Where-Object { $_.Extension -in ".ex5", ".mq5", ".set" } |
        ForEach-Object {
            Remove-Item $_.FullName -Force
            $pruned++
        }

    $termCount++

    # --------------------------------------------------------
    # Build gate — the live EA must have a fresh .ex5 after sync.
    # A missing or stale binary here means the terminal would run
    # an old build (the "MetaEditor still shows v21.1" trap class).
    # Only the LIVE EA (root MitemshubAI.mq5 + its includes) is
    # gated; Tests\*.mq5 scripts are compiled on demand.
    # --------------------------------------------------------
    $liveMq5 = Join-Path $mitemDir "MitemshubAI.mq5"
    $liveEx5 = Join-Path $mitemDir "MitemshubAI.ex5"
    $tag     = Split-Path (Split-Path $mql5Dir) -Leaf
    if (-not (Test-Path $liveMq5)) {
        $deployFailures += "[$tag] live source missing: Experts\MITEMSHUB_AI\MitemshubAI.mq5"
    } elseif (-not (Test-Path $liveEx5)) {
        $deployFailures += "[$tag] LIVE EA NOT BUILT: MitemshubAI.ex5 is missing"
    } else {
        $newestSrc = Get-ChildItem -Path $mitemDir -Recurse -File -Include *.mq5, *.mqh |
            Where-Object { $_.FullName -notmatch '\\Tests\\' } |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ((Get-Item $liveEx5).LastWriteTime -lt $newestSrc.LastWriteTime) {
            $deployFailures += "[$tag] LIVE EA STALE: MitemshubAI.ex5 ($((Get-Item $liveEx5).LastWriteTime.ToString('yyyy-MM-dd HH:mm'))) is older than $($newestSrc.Name) ($($newestSrc.LastWriteTime.ToString('yyyy-MM-dd HH:mm')))"
        }
    }
}

Write-Host "Synced $synced file(s) to $termCount MT5 instance(s)." -ForegroundColor Yellow
Write-Host "Pruned $pruned orphaned file(s) not present in the repo." -ForegroundColor Yellow

if ($deployFailures.Count -gt 0) {
    Write-Host ""
    Write-Host "DEPLOY FAILED - live EA build is missing or stale in $($deployFailures.Count) place(s):" -ForegroundColor Red
    $deployFailures | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    Write-Host "Fix: compile MitemshubAI.mq5 in MetaEditor, then re-run sync-mt5.ps1." -ForegroundColor Yellow
    exit 1
}

Write-Host "Build gate passed: MitemshubAI.ex5 is present and up-to-date in all instances." -ForegroundColor Green
Write-Host "Restart MT5 or recompile the EA for changes to take effect." -ForegroundColor DarkYellow
