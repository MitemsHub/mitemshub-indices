<#
.SYNOPSIS
  One-command verification for the MITEMSHUB_AI MQL5 build: compiles every
  Tests/*Tests.mq5 in MetaEditor and runs each suite in the MT5 Strategy
  Tester headlessly, reporting PASS/FAIL per suite.

.DESCRIPTION
  Per suite:
    1. Compile in a temp build dir (MetaEditor CLI, start/wait semantics).
    2. Stage source + .ex5 into the terminal's Experts/MITEMSHUB_AI tree.
    3. Run the suite in the Strategy Tester via `terminal64 /config` (auto-test
       with ShutdownTerminal=1) on a FREE agent port (3001+ — the default 3000
       is the dashboard dev server on this machine).
    4. Parse the tester log and report the verdict (pulling FAIL lines on error).

  The terminal is closed for the test run and restored afterwards if it was
  running when the script started. Every new *Tests.mq5 (e.g. the live
  StructureLiveTests cross-validation suite) is picked up automatically; pass
  -RangeDays N to give the tester more market history (the live structure
  suite wants >= ~4 days of SYN75 M5 bars for a meaningful measurement).
  automatically.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File mql5\verify_all.ps1
#>
[CmdletBinding()]
param(
  [string]$Symbol = "SYN75",
  [int]$RangeDays = 1,
  [string]$Suite = "",        # filter: only run suites whose BaseName matches (e.g. "BandBackTests")
  [string]$Inputs = "",       # tester input overrides: "InpZEntry=0.8;InpGeomSweep=false;..." (written as a .set)
  [int]$MaxBars = 50000,       # cap on tester history per suite
  [string]$MetaEditor = "C:\Program Files\Blueberry Markets MetaTrader 5\MetaEditor64.exe",
  [string]$TerminalExe = "C:\Program Files\Blueberry Markets MetaTrader 5\terminal64.exe",
  [string]$TerminalDataFolder = "",
  [switch]$SkipSniperGate   # skip the Python sniper walk-forward gate contract (runs by default)
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$srcTree    = Join-Path $scriptRoot "MITEMSHUB_AI"
$buildDir   = Join-Path $scriptRoot "_verify_build"

function Write-Step([string]$msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan }

# --- discover the Blueberry terminal data folder ----------------------------
if (-not $TerminalDataFolder) {
  $termBase = Join-Path $env:APPDATA "MetaQuotes\Terminal"
  $hit = Get-ChildItem $termBase -Directory -ErrorAction SilentlyContinue | Where-Object {
    $o = Join-Path $_.FullName "origin.txt"
    (Test-Path $o) -and ((Get-Content $o -Raw -ErrorAction SilentlyContinue) -match "Blueberry")
  } | Select-Object -First 1
  if (-not $hit) {
    throw "Cannot auto-discover the Blueberry terminal data folder under $termBase. Pass -TerminalDataFolder."
  }
  $TerminalDataFolder = $hit.FullName
}
$termTree      = Join-Path $TerminalDataFolder "MQL5\Experts\MITEMSHUB_AI"
$testerLogsDir = Join-Path $TerminalDataFolder "Tester\logs"
$todayStamp    = (Get-Date).ToString("yyyyMMdd")

if (-not (Test-Path $MetaEditor))  { throw "MetaEditor not found: $MetaEditor" }
if (-not (Test-Path $TerminalExe)) { throw "Terminal not found: $TerminalExe" }
if (-not (Test-Path $srcTree))     { throw "MITEMSHUB_AI tree not found: $srcTree" }

$restoreTerminal = [bool](Get-Process -Name terminal64 -ErrorAction SilentlyContinue)

Write-Step "MITEMSHUB verify — terminal data folder: $TerminalDataFolder"

# --- free agent port (3000 is the dashboard dev server on this machine) -----
function Get-FreePort([int]$start) {
  for ($p = $start; $p -lt $start + 20; $p++) {
    if (-not (Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue)) {
      return $p
    }
  }
  return $start
}

# --- pre-flight smoke check: fail fast instead of a 5-minute hang ------------
# Hard-fails only on conditions that would make the run hang or produce a
# bogus verdict. Port 3000 being held by the dashboard is NOT a failure — the
# tester uses the 3001+ override — but we diagnose it so the message is clear.
function Invoke-Preflight {
  Write-Step "Pre-flight smoke check"
  $problems = @()

  # 1. the data folder must look like a real terminal tree (staging + verdict
  #    parsing both depend on its layout)
  foreach ($sub in @("MQL5", "Tester", "config")) {
    if (-not (Test-Path (Join-Path $TerminalDataFolder $sub))) {
      $problems += "terminal data folder '$TerminalDataFolder' is missing the '$sub' subfolder — is this the right folder?"
    }
  }

  # 2. diagnose port 3000 (dashboard vs anything else) and verify a free agent
  #    port actually exists in the 3001-3020 override range
  $p3000 = Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue
  if ($p3000) {
    $owner = (Get-Process -Id $p3000[0].OwningProcess -ErrorAction SilentlyContinue).ProcessName
    if ($owner -eq "node") {
      Write-Host "    note: port 3000 held by node.exe (dashboard dev server) — tester uses 3001+ override, fine." -ForegroundColor Yellow
    } else {
      Write-Host "    warning: port 3000 held by $owner (not the dashboard) — if this is a stale tester agent it is killed below." -ForegroundColor Yellow
    }
  }
  $anyFree = $false
  for ($p = 3001; $p -lt 3021; $p++) {
    if (-not (Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue)) { $anyFree = $true; break }
  }
  if (-not $anyFree) {
    $problems += "no free agent port in 3001-3020 (all listening) — the tester cannot spawn its agent; free a port and re-run."
  }

  # 3. stale tester agents poison the local agent authorization (the bug that
  #    caused 'authorization error' hangs) — clean them here, before anything
  #    compiles or stages
  $stale = Get-Process -Name metatester64 -ErrorAction SilentlyContinue
  if ($stale) {
    Write-Host "    cleaning $($stale.Count) stale metatester64 process(es) from a previous run..." -ForegroundColor Yellow
    $stale | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
  }

  # 4. the tester log dir must exist and be writable (verdict parsing reads it)
  try {
    New-Item -ItemType Directory -Path $testerLogsDir -Force -ErrorAction Stop | Out-Null
  } catch {
    $problems += "cannot create tester log dir '$testerLogsDir': $($_.Exception.Message)"
  }

  if ($problems.Count -gt 0) {
    Write-Host "PRE-FLIGHT FAILED:" -ForegroundColor Red
    foreach ($p in $problems) { Write-Host "  - $p" -ForegroundColor Red }
    Write-Host "Fix the above and re-run — nothing was compiled or staged." -ForegroundColor Red
    exit 2
  }
  Write-Host "    ok: data folder valid, free agent port available, tester log dir writable." -ForegroundColor Green
}

# --- compile one .mq5 with the MetaEditor CLI --------------------------------
function Invoke-Compile([string]$mq5, [string]$logPath) {
  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = $MetaEditor
  $psi.Arguments = '/compile:"' + $mq5 + '" /log:"' + $logPath + '"'
  # ShellExecute is REQUIRED here: MetaEditor is a GUI-subsystem app whose
  # /compile only actually executes via ShellExecute semantics (the
  # CreateProcess path hands off to a single instance and exits silently).
  $psi.UseShellExecute = $true
  $proc = [System.Diagnostics.Process]::Start($psi)
  $proc.WaitForExit(120000) | Out-Null
  Start-Sleep -Milliseconds 500
  $text = ""
  if (Test-Path $logPath) {
    $text = Get-Content $logPath -Encoding Unicode -Raw
  }
  $m = [regex]::Match($text, "Result:\s*(\d+)\s*errors?,\s*(\d+)\s*warnings?")
  if (-not $m.Success) { return @{ ok = $false; detail = "no compile result in log ($logPath)" } }
  return @{ ok = ([int]$m.Groups[1].Value -eq 0); detail = "Result: $($m.Groups[1].Value) errors, $($m.Groups[2].Value) warnings" }
}

# --- validate the band's edge-depth-split report ----------------------------
# The depth-split table (BandBackTests) is a measurement contract: it must be
# present, its cells must be cumulative subsets (n non-decreasing as the cap
# grows), and the shallow-cell hit rates must stay in sane bands — otherwise a
# depth-cap regression (e.g. the trail-disaster class that collapsed hit to
# ~2%, or a refactor that drops the report) fails the suite VISIBLY instead of
# silently re-measuring garbage.
function Test-DepthSplit([string[]]$logLines) {
  # The tester log accumulates ALL of today's runs.  Only the CURRENT run's
  # block is meaningful — everything after the last suite start marker —
  # otherwise cells from earlier runs (different caps/trails/seeds) get mixed
  # in and the cumulative-n invariant fails spuriously.
  $startIdx = -1
  for ($i = 0; $i -lt $logLines.Count; $i++) {
    if ($logLines[$i] -match 'tester backtest on SYN75 M5 starting') { $startIdx = $i }
  }
  if ($startIdx -ge 0) { $logLines = @($logLines[$startIdx..($logLines.Count - 1)]) }
  # Exit-mode-aware hit bands: in TIME mode (InpExitMode=1, the Python
  # time-exit port) the target is ignored, so "hit" = positive-R closes,
  # which runs ~12-15% by design vs TARGET mode's ~25-28% target hits.
  # The [15,60] TARGET band would false-fail every TIME-mode run; the
  # TIME band is [5,60] — still catches the ~2% trail-disaster class.
  $hitFloor = 15.0
  foreach ($ln in $logLines) {
    if ($ln -match 'exit_mode=TIME') { $hitFloor = 5.0 }
  }
  $rows = @()
  foreach ($ln in $logLines) {
    $m = [regex]::Match($ln, 'depth <= ([\d.]+):\s+n=\s*(\d+)\s+hit=([\d.]+)%\s+exp=([+-][\d.]+)R')
    if ($m.Success) {
      $rows += [pscustomobject]@{
        cap = [double]$m.Groups[1].Value
        n   = [long]$m.Groups[2].Value
        hit = [double]$m.Groups[3].Value
        exp = [double]$m.Groups[4].Value
      }
    }
  }
  $msgs = @()
  if ($rows.Count -eq 0) {
    return @{ ok = $false; msgs = @("depth-split report MISSING from BandBackTests output — the suite no longer prints the per-cap table") }
  }
  # n must be non-decreasing with the cap (cumulative subsets within one run).
  $prev = -1
  foreach ($r in $rows) {
    if ($r.n -lt $prev) {
      $msgs += "cumulative n not monotonic (cap $($r.cap): n=$($r.n) < previous $prev)"
    }
    $prev = $r.n
  }
  # The two contract cells must be present with sane hit bands (measured range
  # across geometries: <=1.25 hit 28-47%, <=2.0 hit 28-41%; the bands below are
  # wide enough to survive window changes but catch the 2%-hit disaster class).
  # exp upper bound widened to +0.75R: the closed-candle trail grace legitimately
  # pushes shallow-cell exp to +0.40R (measured 2026-08-11, trail sweep) — the
  # regression the check exists for is the NEGATIVE collapse (trail-disaster
  # class ~-0.2R+), so the positive side is deliberately generous.
  $c125 = $rows | Where-Object { $_.cap -eq 1.25 } | Select-Object -First 1
  $c20  = $rows | Where-Object { $_.cap -eq 2.00 } | Select-Object -First 1
  if (-not $c125) { $msgs += "depth <= 1.25 cell missing" }
  else {
    if ($c125.hit -lt $hitFloor -or $c125.hit -gt 60.0) { $msgs += "depth <= 1.25 hit $($c125.hit)% outside [$($hitFloor),60] — shallow-fade collapse?" }
    if ($c125.exp -lt -0.35 -or $c125.exp -gt 0.75) { $msgs += "depth <= 1.25 exp $($c125.exp)R outside [-0.35,+0.75]" }
  }
  if (-not $c20) { $msgs += "depth <= 2.00 cell missing" }
  else {
    if ($c20.hit -lt $hitFloor -or $c20.hit -gt 60.0) { $msgs += "depth <= 2.00 hit $($c20.hit)% outside [$($hitFloor),60] — shallow-only regression?" }
    if ($c20.exp -lt -0.35 -or $c20.exp -gt 0.75) { $msgs += "depth <= 2.00 exp $($c20.exp)R outside [-0.35,+0.75]" }
  }
  $best = ($rows | Sort-Object cap | Select-Object -Last 1)

  # --- Stage-3 floor verdict contract (same run block) -----------------------
  # The gate's own BEATS / does NOT beat line is a measurement contract too:
  # it must be PRESENT (a refactor that drops the gate block fails), internally
  # CONSISTENT (BEATS requires achieved hit >= floor — a declared flip that
  # contradicts its own numbers is a bug, not an improvement), and the floor
  # must sit in the plausible 1/(1+RR)+margin band [20,60]% for the RR
  # geometries this suite measures (RR 1.0-3.5, margin 0.05 -> floor 27-55%).
  $fHit = 0.0; $fFloor = 0.0; $fWord = ''; $hasFloorBlock = $false
  foreach ($ln in $logLines) {
    if ($ln -match 'Stage-3 empirical floor gate') { $hasFloorBlock = $true }
    $m = [regex]::Match($ln, 'VERDICT: achieved hit ([\d.]+)% (BEATS|does NOT beat) the ([\d.]+)% floor')
    if ($m.Success) {
      $fHit = [double]$m.Groups[1].Value
      $fWord = $m.Groups[2].Value
      $fFloor = [double]$m.Groups[3].Value
    }
  }
  if (-not $hasFloorBlock) {
    $msgs += "Stage-3 floor-gate report MISSING from BandBackTests output — the suite no longer prints the break-even verdict"
  } elseif (-not $fWord) {
    $msgs += "Stage-3 VERDICT line missing (gate block present but no BEATS / does NOT beat verdict)"
  } else {
    if ($fFloor -lt 20.0 -or $fFloor -gt 60.0) {
      $msgs += "floor $($fFloor)% outside [20,60]% — break-even math regressed?"
    }
    # Rounding tolerance: the suite decides on RAW doubles then prints 1-decimal
    # values, so the printed hit can sit up to ~0.1pp on the wrong side of the
    # printed floor for a legitimately-consistent verdict.  ±0.15 absorbs that.
    $beats = ($fWord -eq 'BEATS')
    if ($beats) {
      if ($fHit + 0.15 -lt $fFloor) { $msgs += "floor verdict FLIP: declared BEATS at hit $($fHit)% but floor is $($fFloor)% — contradicts its own numbers" }
    } else {
      if ($fHit + 0.15 -ge $fFloor) { $msgs += "floor verdict FLIP: declared 'does NOT beat' at hit $($fHit)% vs floor $($fFloor)% — contradicts its own numbers" }
    }
  }

  # --- vol-regime split contract (same run block) ----------------------------
  # Independent of depth: is the book drifting into high-vol-regime entries
  # (vol_ratio_entry = prev_sigma / sigma_ema > 1.25)?  The suite prints each
  # vol cell ONLY when it has trades (it `continue`s on dn==0), so a missing
  # vol>1.25 line means ZERO high-vol trades — normal.  A missing split HEADER
  # is a refactor regression and fails like the other contracts.
  # Fail when the high-vol cell becomes a MEANINGFUL SHARE of the book with a
  # negative expectancy (the bleed hypothesis this split exists to watch), and
  # unconditionally past a third of trades — at that point the cell is no
  # longer a diagnostic, it IS the strategy, and its floor needs its own
  # validation.  A large-but-positive high-vol share is reported in the Detail
  # line, not failed (measured 2026-08-12 default run: 0.7% share, +0.200R).
  $hasVolBlock = $false; $vlo = $null; $vhi = $null
  foreach ($ln in $logLines) {
    if ($ln -match 'vol-regime split at entry') { $hasVolBlock = $true }
    $m = [regex]::Match($ln, 'vol(<=1\.25|>1\.25)\s+n=\s*(\d+)\s+hit=\s*([\d.]+)%\s+exp=([+-][\d.]+)R')
    if ($m.Success) {
      $cell = [pscustomobject]@{ n = [long]$m.Groups[2].Value; hit = [double]$m.Groups[3].Value; exp = [double]$m.Groups[4].Value }
      if ($m.Groups[1].Value -eq '<=1.25') { $vlo = $cell } else { $vhi = $cell }
    }
  }
  $volShare = -1.0   # -1 = not computable
  if (-not $hasVolBlock) {
    $msgs += "vol-regime split report MISSING from BandBackTests output — the suite no longer prints the vol split"
  } elseif (-not $vlo) {
    $msgs += "vol-regime split has no vol<=1.25 row — cannot compute the high-vol share"
  } else {
    $volTotal = $vlo.n + $(if ($vhi) { $vhi.n } else { 0 })
    if ($volTotal -gt 0) {
      $volShare = $(if ($vhi) { $vhi.n / [double]$volTotal } else { 0.0 })
      if ($vhi -and $volShare -ge 0.35) {
        $msgs += "vol>1.25 cell is $([math]::Round(100 * $volShare, 1))% of trades (n=$($vhi.n)/$volTotal) — the vol cell IS the book now; re-validate the high-vol entry path"
      } elseif ($vhi -and $volShare -ge 0.20 -and $vhi.exp -lt 0.0) {
        $msgs += "vol>1.25 cell is $([math]::Round(100 * $volShare, 1))% of trades with exp $($vhi.exp)R — high-vol entries diluting the edge"
      }
    }
  }

  # --- machine-parseable depth profile + floor verdict -----------------------
  # The suite prints one DEPTHPROFILE line (all 5 cumulative caps in one line:
  # n / hit / exp / share-of-total) and one FLOORVERDICT line.  The BUCKET
  # COMPOSITION contract: each cap's share must stay in the measured bands —
  # sweep ON/OFF across 5 seeds and TARGET/TIME modes all span <=1.25 10.7-12.4%,
  # <=1.50 20.9-24.7%, <=2.00 46.7-48.6%, <=2.50 71.7-74.3% — so a composition
  # shift (e.g. a refactor letting deep trades dominate, or the shallow bucket
  # collapsing) fails the loop visibly.  Guarded by total>=50 so thin windows
  # don't false-fail.  The FLOORVERDICT must agree with the human VERDICT line.
  $dp = $null; $fv = $null
  foreach ($ln in $logLines) {
    $m = [regex]::Match($ln, 'DEPTHPROFILE caps=1\.25,1\.50,2\.00,2\.50,3\.00 n=(\d+(?:,\d+){4}) hit=(\S+) exp=(\S+) share=(\S+) total=(\d+)')
    if ($m.Success) { $dp = $m }
    $mf = [regex]::Match($ln, 'FLOORVERDICT floor=([\d.]+) achieved=([\d.]+) verdict=(BEAT|NOT_BEAT) mean_rr=([\d.]+)')
    if ($mf.Success) { $fv = $mf }
  }
  $dpShares = @()
  if (-not $dp) {
    $msgs += "DEPTHPROFILE line MISSING from BandBackTests output — the suite no longer prints the machine depth profile"
  } else {
    $dpN  = @($dp.Groups[1].Value -split ',') | ForEach-Object { [long]$_ }
    $dpHit = @($dp.Groups[2].Value -split ',') | ForEach-Object { [double]$_ }
    $dpExp = @($dp.Groups[3].Value -split ',') | ForEach-Object { [double]$_ }
    $dpShares = @($dp.Groups[4].Value -split ',') | ForEach-Object { [double]$_ }
    $dpTotal = [long]$dp.Groups[5].Value
    # cross-check: the machine line must agree with the parsed per-row lines
    # (both are printed from the same arrays, so a mismatch is a print bug).
    $caps = @(1.25, 1.50, 2.00, 2.50, 3.00)
    for ($i = 0; $i -lt 5; $i++) {
      $row = $rows | Where-Object { $_.cap -eq $caps[$i] } | Select-Object -First 1
      if ($row -and $row.n -ne $dpN[$i]) {
        $msgs += "DEPTHPROFILE n[$($caps[$i])]=$($dpN[$i]) disagrees with parsed row n=$($row.n) — print drift"
      }
    }
    if ($best -and $dpTotal -ne $best.n) {
      $msgs += "DEPTHPROFILE total $($dpTotal) disagrees with parsed max-cap n $($best.n) — parse drift"
    }
    if ($dpTotal -ge 50) {
      $compBands = @(
        @{ cap = 1.25; lo = 5.0;  hi = 25.0 },
        @{ cap = 1.50; lo = 10.0; hi = 40.0 },
        @{ cap = 2.00; lo = 25.0; hi = 70.0 },
        @{ cap = 2.50; lo = 45.0; hi = 90.0 }
      )
      for ($i = 0; $i -lt 4; $i++) {
        $s = $dpShares[$i]
        $b = $compBands[$i]
        if ($s -lt $b.lo -or $s -gt $b.hi) {
          $msgs += "depth bucket composition shifted: <=$($b.cap) share is $('{0:0.0}' -f $s)% of $($dpTotal) trades, outside [$($b.lo),$($b.hi)]% — entries landed in different depth buckets than measured (10.7-12.4 / 20.9-24.7 / 46.7-48.6 / 71.7-74.3)"
        }
      }
    }
  }
  if (-not $fv) {
    $msgs += "FLOORVERDICT line MISSING from BandBackTests output — the suite no longer prints the machine floor verdict"
  } elseif ($fWord) {
    # machine token must agree with the human verdict (BEAT <-> BEATS, NOT_BEAT <-> does NOT beat)
    $fvWord = if ($fv.Groups[3].Value -eq 'BEAT') { 'BEATS' } else { 'does NOT beat' }
    if ($fvWord -ne $fWord) {
      $msgs += "FLOORVERDICT verdict '$($fv.Groups[3].Value)' contradicts human VERDICT '$fWord' — contract bug"
    }
    if ([math]::Abs([double]$fv.Groups[1].Value - $fFloor) -gt 0.15 -or [math]::Abs([double]$fv.Groups[2].Value - $fHit) -gt 0.15) {
      $msgs += "FLOORVERDICT floor/achieved ($($fv.Groups[1].Value)/$($fv.Groups[2].Value)) disagree with VERDICT ($fFloor/$fHit) — parse drift"
    }
  }

  $ok = ($msgs.Count -eq 0)
  $okMsg = "depth-split: $($rows.Count) cells, <=1.25 hit $($c125.hit)%/exp $($c125.exp)R, <=2.00 hit $($c20.hit)%/exp $($c20.exp)R, max cap $($best.cap) n=$($best.n)"
  if ($fWord) { $okMsg += " | floor-gate: hit $($fHit)% $($fWord) $($fFloor)%" }
  if ($dpShares.Count -eq 5 -and $dp) {
    $okMsg += " | depth-comp: <=1.25 $('{0:0.0}' -f $dpShares[0])% | <=1.50 $('{0:0.0}' -f $dpShares[1])% | <=2.50 $('{0:0.0}' -f $dpShares[3])% (total $($dp.Groups[5].Value))"
  }
  if ($hasVolBlock -and $vlo) {
    $volTotal = $vlo.n + $(if ($vhi) { $vhi.n } else { 0 })
    # Stable decimal formatting (the Detail line is machine-parsed): '0.0' keeps
    # the trailing zero and '+0.000;-0.000' keeps the sign on exp.
    $volState = "vol-split: <=1.25 n=$($vlo.n) hit=$('{0:0.0}' -f $vlo.hit)% exp=$('{0:+0.000;-0.000}' -f $vlo.exp)R"
    if ($vhi) {
      $volState += "; >1.25 n=$($vhi.n) hit=$('{0:0.0}' -f $vhi.hit)% exp=$('{0:+0.000;-0.000}' -f $vhi.exp)R ($('{0:0.0}' -f (100 * $vhi.n / $volTotal))% of trades)"
    } else {
      $volState += "; >1.25 n=0 (0.0% of trades)"
    }
    $okMsg += " | $volState"
  }
  return @{ ok = $ok; msgs = $msgs; okMsg = $okMsg }
}

# --- run the sniper walk-forward gate contract (Python harness) ---------------
# The band's depth-split contract is asserted inside the tester log parse; the
# sniper's equivalent lives in the PYTHON harness (mql5/svcap_recheck.py): its
# walk-forward gate block tags every trade KEPT or SUPPRESSED, and the reference
# svcap cell (UTC 12-24h & |range_z|<1.0 & |garch_z|<=1.5, time-exit) is
# gate-clean (measured 13.02d corpus 2026-08-12: kept=147/147, suppressed=0).
# A suppressed-vs-kept REGRESSION — the gate starting to block a previously
# clean cell — must fail the scheduled loop the same way a depth-cap regression
# fails it.  --gate-check runs ONE real run_ticks pass (~3-5 min) and exits
# nonzero on FAIL, so the loop just has to honor the exit code + verdict line.
function Invoke-SniperGateCheck {
  $py = Get-Command python -ErrorAction SilentlyContinue
  if (-not $py) {
    return @{ ok = $false; skipped = $true; detail = "python not on PATH — sniper gate contract NOT run (install Python to arm it)" }
  }
  Write-Step "Running sniper walk-forward gate contract (svcap_recheck.py --gate-check, ~3-5 min)..."
  $script = Join-Path $scriptRoot "svcap_recheck.py"
  if (-not (Test-Path $script)) {
    return @{ ok = $false; skipped = $false; detail = "svcap_recheck.py missing under $scriptRoot — sniper gate contract cannot run" }
  }
  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = "python"
  $psi.Arguments = '"' + $script + '" --gate-check'
  $psi.RedirectStandardOutput = $true
  $psi.RedirectStandardError = $true
  $psi.UseShellExecute = $false
  $proc = [System.Diagnostics.Process]::Start($psi)
  $stdout = $proc.StandardOutput.ReadToEnd()
  $stderr = $proc.StandardError.ReadToEnd()
  if (-not $proc.WaitForExit(900000)) {
    $proc.Kill()
    return @{ ok = $false; skipped = $false; detail = "sniper gate check TIMED OUT (900s) — harness hung; treat as regression" }
  }
  $exit = $proc.ExitCode
  if ($stderr) { Write-Host "    (gate-check stderr): $($stderr.Trim())" -ForegroundColor Yellow }
  # Last [GATECHECK] verdict line wins (PASS / FAIL / SKIP + detail).
  $last = $null
  foreach ($ln in ($stdout -split "`r?`n")) {
    $m = [regex]::Match($ln, [regex]::Escape('[GATECHECK]') + ' (PASS|FAIL|SKIP): (.+)')
    if ($m.Success) { $last = $m }
  }
  if (-not $last) {
    return @{ ok = $false; skipped = $false; detail = "no [GATECHECK] verdict in harness output (exit $exit) — check python / corpus" }
  }
  $verdict = $last.Groups[1].Value
  $detail = $last.Groups[2].Value
  $ok = ($verdict -ne 'FAIL')
  Write-Host "    sniper gate contract: $verdict — $detail" -ForegroundColor $(if ($ok) { "Green" } else { "Red" })
  return @{ ok = $ok; skipped = $false; detail = "$verdict — $detail" }
}

# --- run one suite in the tester, return verdict -----------------------------
function Invoke-TesterSuite([string]$expertName, [string]$iniPath) {
  Get-Process -Name metatester64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  if (Get-Process -Name terminal64 -ErrorAction SilentlyContinue) {
    Write-Step "Closing running terminal for the test run..."
    Get-Process -Name terminal64 -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
  }

  $logFile = Join-Path $testerLogsDir ($todayStamp + ".log")
  $logBefore = if (Test-Path $logFile) { (Get-Item $logFile).Length } else { -1 }
  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = $TerminalExe
  $psi.Arguments = '/config:"' + $iniPath + '"'
  $psi.UseShellExecute = $false
  $proc = [System.Diagnostics.Process]::Start($psi)
  $proc.WaitForExit(300000) | Out-Null   # self-shuts via ShutdownTerminal=1

  $lines = @()
  if (Test-Path $logFile) {
    $lines = Get-Content $logFile -Encoding Unicode
  }
  $logAfter = if (Test-Path $logFile) { (Get-Item $logFile).Length } else { -1 }
  if ($logAfter -le $logBefore) {
    # The terminal never wrote to the tester log: it either failed to start or
    # the tester never launched. Bail out now with a clear message instead of
    # trusting a stale PASSED line from an earlier run.
    return @{ status = "TESTER_ERROR"; detail = "tester log '$logFile' unchanged after the run (size $logBefore -> $logAfter) — terminal/tester failed to start; re-check the INI and the pre-flight output." }
  }
  $summary = $lines | Select-String -Pattern '=== (\d+) passed, (\d+) failed ===' | Select-Object -Last 1
  $verdict = $lines | Select-String -Pattern 'SUITE (PASSED|FAILED)' | Select-Object -Last 1
  $failLns = $lines | Select-String -Pattern 'FAIL ' | Select-Object -First 3

  if (-not $verdict) {
    return @{ status = "TESTER_ERROR"; detail = "no SUITE verdict in $logFile (terminal exit may have failed)" }
  }
  $passed = 0; $failed = 0
  if ($summary) {
    $mm = [regex]::Match($summary.Line, '=== (\d+) passed, (\d+) failed ===')
    if ($mm.Success) { $passed = [int]$mm.Groups[1].Value; $failed = [int]$mm.Groups[2].Value }
  }
  $ok = ($verdict.Line -match 'PASSED')
  $detail = "passed=$passed failed=$failed ($($verdict.Line.Trim()))"
  if (-not $ok -and $failLns) {
    $detail += " | first fails: " + (($failLns | ForEach-Object { $_.Line.Trim() }) -join " ; ")
  }
  # --- depth-split contract (BandBackTests only) -----------------------------
  # A depth-cap regression must fail the suite visibly even when the suite's
  # own "SUITE PASSED" verdict is unchanged (the tester only counts its own
  # assertions).  Parse the table the run just printed and fold the verdict in.
  if ($expertName -eq "BandBackTests") {
    $ds = Test-DepthSplit $lines
    if ($ds.ok) {
      $detail += " | $($ds.okMsg)"
    } else {
      $ok = $false
      $detail += " | DEPTH-REGRESSION: " + ($ds.msgs -join " ; ")
    }
  }
  return @{ status = $(if ($ok) { "PASS" } else { "FAIL" }); detail = $detail }
}

# ============================ main ==========================================
Invoke-Preflight

Write-Step "Staging source tree into the terminal: $termTree"
New-Item -ItemType Directory -Path $termTree -Force | Out-Null
Copy-Item (Join-Path $srcTree "*") $termTree -Recurse -Force

Write-Step "Preparing temp build dir: $buildDir"
Remove-Item $buildDir -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item $srcTree $buildDir -Recurse -Force

$tests = Get-ChildItem (Join-Path $srcTree "Tests") -Filter "*Tests.mq5" | Sort-Object Name
if ($Suite) {
  $tests = $tests | Where-Object { $_.BaseName -like $Suite }
  if (-not $tests) { throw "No suite matches -Suite '$Suite' under $srcTree\Tests" }
}
if (-not $tests) { throw "No *Tests.mq5 found under $srcTree\Tests" }
Write-Host "Found $($tests.Count) suite(s): $((($tests | ForEach-Object { $_.BaseName }) -join ', '))"

$results = @()
foreach ($t in $tests) {
  $name = $t.BaseName
  Write-Step "[$name] compiling in MetaEditor..."
  $mq5src  = Join-Path $buildDir ("Tests\" + $t.Name)
  $compLog = Join-Path $buildDir ("compile_" + $name)
  $c = Invoke-Compile $mq5src $compLog
  if (-not $c.ok) {
    $results += [pscustomobject]@{ Suite = $name; Compile = "FAIL"; Tester = "-"; Detail = $c.detail }
    Write-Host "    COMPILE FAILED: $($c.detail)" -ForegroundColor Red
    continue
  }
  Write-Host "    compile OK: $($c.detail)"

  $ex5 = Join-Path $buildDir ("Tests\" + $name + ".ex5")
  if (-not (Test-Path $ex5)) {
    $results += [pscustomobject]@{ Suite = $name; Compile = "FAIL"; Tester = "-"; Detail = "no .ex5 produced" }
    continue
  }
  Copy-Item $ex5 (Join-Path $termTree ("Tests\" + $name + ".ex5")) -Force

  $port = Get-FreePort 3001
  $from = (Get-Date).AddDays(-$RangeDays).ToString("yyyy.MM.dd")
  $to   = (Get-Date).ToString("yyyy.MM.dd")
  # Stale saved input sets (MQL5\Profiles\Tester\<expert>.set) silently override
  # the compiled defaults of a freshly built .ex5 — a rebuilt suite can run with
  # OLD gate values and pass/fail for the wrong reasons.  Purge the set for this
  # expert (and the bare name without 'Tests') before every run.
  $testerProfiles = Join-Path $TerminalDataFolder "MQL5\Profiles\Tester"
  # NOTE: each array element MUST be parenthesized — PowerShell otherwise
  # parses `@($name + ".set", $name.Replace(...))` as a SINGLE space-joined
  # string ("BandBackTests.set BandBack.set"), Test-Path always returns
  # False, and the purge silently never runs — the tester's auto-saved
  # .set then pins stale inputs over the compiled defaults.
  foreach ($setName in @(($name + ".set"), ($name.Replace("Tests", "") + ".set"))) {
    $setPath = Join-Path $testerProfiles $setName
    if (Test-Path $setPath) {
      Remove-Item $setPath -Force -ErrorAction SilentlyContinue
      Write-Host "    purged stale input set: $setPath" -ForegroundColor Yellow
    }
  }
  # -Inputs overrides: MT5's tester INI takes ExpertParameters=<name>.set, i.e.
  # a saved input set in MQL5\Profiles\Tester — not inline pairs.  Write one
  # here (after the purge, so it survives), point the INI at it, and the
  # post-run purge below removes it again.
  $setOverrideName = ""
  if ($Inputs) {
    $setOverrideName = $name + ".set"
    $setLines = @()
    foreach ($pair in ($Inputs -split ';')) {
      $kv = $pair -split '=', 2
      if ($kv.Count -ne 2) { continue }
      $nm = $kv[0].Trim(); $val = $kv[1].Trim()
      if ($val -eq 'true' -or $val -eq 'false') {
        $setLines += "$nm=$val||false||0||true||N"
      } else {
        $setLines += "$nm=$val||$val||0.0||10000.0||N"
      }
    }
    $setPath = Join-Path $testerProfiles $setOverrideName
    [System.IO.File]::WriteAllText($setPath, ($setLines -join "`r`n"), [System.Text.Encoding]::Unicode)
    Write-Host "    wrote input override set: $setPath" -ForegroundColor Yellow
  }
  $ini  = Join-Path $TerminalDataFolder ("verify_" + $name + ".ini")
  $iniContent = @(
    "[Tester]",
    "Expert=MITEMSHUB_AI\Tests\$name",
    "ExpertParameters=$setOverrideName",
    "Symbol=$Symbol",
    "Period=M5",
    "Model=1",
    "ExecutionMode=0",
    "Optimization=0",
    "OptimizationCriterion=0",
    "FromDate=$from",
    "ToDate=$to",
    "ForwardMode=0",
    "Report=verify_$name",
    "ReplaceReport=1",
    "ShutdownTerminal=1",
    "Deposit=10000",
    "Currency=USD",
    "Leverage=1:100",
    "Visual=0",
    "UseLocal=1",
    "UseRemote=0",
    "UseCloud=0",
    "Port=$port"
  ) -join "`r`n"
  [System.IO.File]::WriteAllText($ini, $iniContent, [System.Text.Encoding]::ASCII)

  Write-Step "[$name] running in Strategy Tester ($Symbol, $from -> $to, agent port $port)..."
  $r = Invoke-TesterSuite $name $ini
  $results += [pscustomobject]@{ Suite = $name; Compile = "OK"; Tester = $r.status; Detail = $r.detail }
  $color = if ($r.status -eq "PASS") { "Green" } else { "Red" }
  Write-Host "    $($r.status): $($r.detail)" -ForegroundColor $color

  Remove-Item $ini -Force -ErrorAction SilentlyContinue

  # The MT5 tester AUTO-SAVES the parameters it just ran with to
  # MQL5\Profiles\Tester\<expert>.set at the end of a run.  A re-purge here
  # keeps the next invocation (full or -Suite) from loading those saved
  # values instead of the freshly compiled defaults — the exact stale-set
  # failure observed when InpMinTargetRR was pinned to 2.0 while the
  # geometry emitted RR 1.2.
  $testerProfiles = Join-Path $TerminalDataFolder "MQL5\Profiles\Tester"
  foreach ($setName in @(($name + ".set"), ($name.Replace("Tests", "") + ".set"))) {
    $setPath = Join-Path $testerProfiles $setName
    if (Test-Path $setPath) {
      Remove-Item $setPath -Force -ErrorAction SilentlyContinue
      Write-Host "    post-run purged tester-saved input set: $setPath" -ForegroundColor Yellow
    }
  }
}

# --- sniper walk-forward gate contract (Python harness) ---------------------
# Same contract-gate pattern as the band's depth-split check, applied to the
# sniper leg: a suppressed-vs-kept regression on the reference svcap cell must
# fail the loop.  Runs after the tester suites (it is corpus replay — no MT5
# dependency — so the terminal restore below is unaffected).
if ($SkipSniperGate) {
  Write-Step "Skipping sniper gate contract (-SkipSniperGate)"
} else {
  $g = Invoke-SniperGateCheck
  $results += [pscustomobject]@{
    Suite = "SniperGate"; Compile = "-"
    Tester = $(if ($g.ok) { "PASS" } elseif ($g.skipped) { "SKIP" } else { "FAIL" })
    Detail = $g.detail
  }
}

# --- restore the terminal if it was up when we started ----------------------
# The tester terminal (launched via /config with ShutdownTerminal=1) can still
# be winding down when we get here, and MT5's single-instance guard makes a
# fresh launch exit silently.  Retry until a live process exists.
if ($restoreTerminal -and -not (Get-Process -Name terminal64 -ErrorAction SilentlyContinue)) {
  Write-Step "Restoring the terminal (it was running when verification started)..."
  for ($try = 0; $try -lt 3; $try++) {
    Start-Process -FilePath $TerminalExe
    Start-Sleep -Seconds 8
    if (Get-Process -Name terminal64 -ErrorAction SilentlyContinue) { break }
  }
  if (-not (Get-Process -Name terminal64 -ErrorAction SilentlyContinue)) {
    Write-Host "WARNING: could not relaunch the terminal after 3 attempts - start it manually." -ForegroundColor Yellow
  }
}

Write-Step "Cleaning temp build dir"
Remove-Item $buildDir -Recurse -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "==================== MITEMSHUB verify summary ===================="
$results | Format-Table -AutoSize
# Compile "-" = Python harness row (no MQL5 compile); Tester "SKIP" = python
# unavailable / corpus too thin — neither is a failure.
$bad = @($results | Where-Object { ($_.Compile -ne "OK" -and $_.Compile -ne "-") -or ($_.Tester -ne "PASS" -and $_.Tester -ne "SKIP") })
if ($bad.Count -eq 0) {
  Write-Host "ALL SUITES PASSED (compile + Strategy Tester + sniper gate contract)." -ForegroundColor Green
  exit 0
}
Write-Host "$($bad.Count) suite(s) NOT green — see Detail column." -ForegroundColor Red
exit 1
