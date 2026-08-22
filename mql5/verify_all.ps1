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

  # Multi-seed depth-split gate: re-runs BandBackTests across 5 InpGeomSeed
  # values (7,42,123,777,2024) and FAILS if the depth-split cell MEANS are not
  # stable across seeds (a single-seed positive is seed noise, not signal).
  powershell -NoProfile -ExecutionPolicy Bypass -File mql5\verify_all.ps1 -SeedSweep -Seeds "7,42,123,777,2024"
#>
[CmdletBinding()]
param(
  [string]$Symbol = "SYN75",
  [int]$RangeDays = 1,
  [string]$Suite = "",        # filter: only run suites whose BaseName matches (e.g. "BandBackTests")
  [string]$Inputs = "",       # tester input overrides: "InpZEntry=0.8;InpGeomSweep=false;..." (written as a .set)
  [int]$TestModel = 1,         # tester price model for the SUITE loop only: 1 = every tick on real ticks
                               # (calibrated reference), 2 = 1-min OHLC (P10-E OHLC stress row).  The
                               # Phase-6 risk gate and the seed sweep keep Model=1 (their contracts were
                               # calibrated on real ticks — a different model there would silently change
                               # the contract they assert).
  [int]$MaxBars = 50000,       # cap on tester history per suite
  [string]$MetaEditor = "C:\Program Files\MetaTrader 5 Terminal\MetaEditor64.exe",
  [string]$TerminalExe = "C:\Program Files\MetaTrader 5 Terminal\terminal64.exe",
  [string]$TerminalDataFolder = "",
  [switch]$SkipSniperGate,        # skip the Python sniper walk-forward gate contract (runs by default)
  [switch]$SkipExecutionParity,   # skip the paper->live execution parity check (runs by default)
  [switch]$SkipRealCorpusGate,    # skip the Phase-6/7 real-corpus gate contracts (runs by default)
  [switch]$SkipPhase8Gate,        # skip the Phase-8 analytics gate contract (runs by default)
  [switch]$SkipPhase10Gate,       # skip the Phase-10 P10-A integration gate contract (runs by default)
  [switch]$SkipPhase10R100Gate,   # skip the R_100 four-leg sign-lock inside the Phase-10 gate (runs by default)
  [switch]$SkipPhase10ESignGate,  # skip the Phase-10 P10-E real-tick sign gate (runs by default)
  [switch]$SkipSniperOhlcGate,     # skip the Phase-10 sniper-OHLC model-robustness gate (runs by default)
  [switch]$SkipPhase6Gate,        # skip the Phase-6 risk-wiring gate contract (runs by default)
  [switch]$SkipCalibrationGate,   # skip the calibration-sanity gate contract (runs by default)
  [switch]$SeedSweep,             # ALSO run the depth-split gate across -Seeds and fail on unstable cell means
  [string]$Seeds = "7,42,123,777,2024"  # comma-separated InpGeomSeed list for -SeedSweep
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot   = Split-Path -Parent $scriptRoot   # repo root (mql5/ is a subdir)
$srcTree    = Join-Path $scriptRoot "MITEMSHUB_AI"
$buildDir   = Join-Path $scriptRoot "_verify_build"

function Write-Step([string]$msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan }

# --- discover the Deriv terminal data folder ----------------------------
if (-not $TerminalDataFolder) {
  $termBase = Join-Path $env:APPDATA "MetaQuotes\Terminal"
  $hit = Get-ChildItem $termBase -Directory -ErrorAction SilentlyContinue | Where-Object {
    $o = Join-Path $_.FullName "origin.txt"
    (Test-Path $o) -and ((Get-Content $o -Raw -ErrorAction SilentlyContinue) -match "Deriv")
  } | Select-Object -First 1
  if (-not $hit) {
    throw "Cannot auto-discover the Deriv terminal data folder under $termBase. Pass -TerminalDataFolder."
  }
  $TerminalDataFolder = $hit.FullName
}
$termTree      = Join-Path $TerminalDataFolder "MQL5\Experts\MITEMSHUB_AI"
$testerLogsDir = Join-Path $TerminalDataFolder "Tester\logs"
$todayStamp    = (Get-Date).ToString("yyyyMMdd")

# Machine-line numeric token shared by every gate regex below: OPTIONAL sign
# (the EA prints '-' only for negatives — positive values carry no '+' — and
# the Python harnesses force '+' via ':+' / MQL5 via '%+' today), fixed-point
# OR exponent form, so a value turning positive or a harness switching float
# format to %g/%e can never silently break a gate parse again.  It is ONE
# CAPTURING group (replacing the old ([+-][\d.]+) one-for-one), so interpolat-
# ing it into a pattern keeps every downstream group index unchanged.
$NumTok = '([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)'

if (-not (Test-Path $MetaEditor))  { throw "MetaEditor not found: $MetaEditor" }
if (-not (Test-Path $TerminalExe)) { throw "Terminal not found: $TerminalExe" }
if (-not (Test-Path $srcTree))     { throw "MITEMSHUB_AI tree not found: $srcTree" }

$restoreTerminal = [bool](Get-Process -Name terminal64 -ErrorAction SilentlyContinue)

Write-Step "MITEMSHUB verify — terminal data folder: $TerminalDataFolder"

# --- mutual pause with the live tick collector ------------------------------
# The tester runs below close the live terminal (Stop-Process terminal64), which
# the collector otherwise sees as a feed loss and reconnects against — and could
# attach to the TESTER instance and pollute the corpus with modeled ticks.  We
# write a pause marker the collector polls every cycle; it stands down until the
# marker is removed.  Path must match VERIFY_PAUSE_PATH in
# src/synthetic_trader/data/continuous_collector.py; the collector treats a
# marker older than 2h as expired, so a crashed verify self-heals.
$verifyPauseFlag = Join-Path $repoRoot ".data\verify_pause.flag"
$collectorStatus = Join-Path $repoRoot "data\live_tick_collector.json"

function Set-VerifyPause {
  New-Item -ItemType Directory -Path (Split-Path $verifyPauseFlag) -Force | Out-Null
  @{ started = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds(); pid = $PID; reason = "verify_all.ps1" } |
    ConvertTo-Json -Compress | Set-Content -Path $verifyPauseFlag -Encoding ascii
  Write-Host "    collector pause marker written: $verifyPauseFlag" -ForegroundColor Yellow
  # Acknowledge: wait until the collector reports the stand-down (it polls the
  # marker every cycle) so we never kill the terminal under a collecting client.
  for ($try = 0; $try -lt 20; $try++) {
    if (Test-Path $collectorStatus) {
      $st = Get-Content $collectorStatus -Raw | ConvertFrom-Json
      $paused = @($st.collectors.PSObject.Properties | Where-Object { $_.Value.paused_by }).Count
      if ($paused -gt 0) { Write-Host "    collector acknowledged the pause (status file)." -ForegroundColor Green; return }
    }
    Start-Sleep -Seconds 1
  }
  Write-Host "    WARNING: collector did not acknowledge the pause (is it running?) - the marker still blocks reconnects." -ForegroundColor Yellow
}

function Clear-VerifyPause {
  if (Test-Path $verifyPauseFlag) {
    Remove-Item $verifyPauseFlag -Force -ErrorAction SilentlyContinue
    Write-Host "    collector pause marker cleared." -ForegroundColor Green
  }
}

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

  # 5. machine-line parse-contract gates: the P10-A / Phase-6 / P10-E gates
  #    parse [PHASE10] machine lines out of the tester log, and the Phase-8
  #    gate parses [PHASE8-ANALYTICS] band/buckets/exit lines out of the
  #    analytics run — if any of those regexes regresses (a sign or format
  #    assumption, like the sumR positive-flip bug of 2026-08-17) the gates
  #    bail with "no machine line" and every verdict is silently bogus.
  #    verify_phase10_machine_line_fixtures.ps1 and
  #    verify_phase8_machine_line_fixtures.ps1 re-validate the LIVE pattern
  #    text (extracted from THIS file) against positive/zero/forced-sign
  #    lines — run both here, before anything compiles or stages, so the
  #    hourly scheduled loop fails in seconds instead of after a 20-minute
  #    tester run.  Cheap (~1s each) and always-on.
  $fixtures = Join-Path $scriptRoot "verify_phase10_machine_line_fixtures.ps1"
  if (-not (Test-Path $fixtures)) {
    Write-Host "    WARNING: $fixtures missing — machine-line parse-contract gate NOT run (restore it; the regex protection is absent)." -ForegroundColor Yellow
  } else {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $fixtures
    if ($LASTEXITCODE -ne 0) {
      $problems += "machine-line parse-contract gate FAILED (verify_phase10_machine_line_fixtures.ps1 exit $LASTEXITCODE) — a [PHASE10] gate regex regressed or the harness is out of date; fix verify_all.ps1 or the harness"
    } else {
      Write-Host "    ok: machine-line parse-contract fixtures pass ([PHASE10] gate regexes match their contract)." -ForegroundColor Green
    }
  }
  $phase8Fixtures = Join-Path $scriptRoot "verify_phase8_machine_line_fixtures.ps1"
  if (-not (Test-Path $phase8Fixtures)) {
    Write-Host "    WARNING: $phase8Fixtures missing — Phase-8 parse-contract gate NOT run (restore it; the band/buckets/exit regex protection is absent)." -ForegroundColor Yellow
  } else {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $phase8Fixtures
    if ($LASTEXITCODE -ne 0) {
      $problems += "Phase-8 machine-line parse-contract gate FAILED (verify_phase8_machine_line_fixtures.ps1 exit $LASTEXITCODE) — a [PHASE8-ANALYTICS] gate regex regressed or the harness is out of date; fix verify_all.ps1 or the harness"
    } else {
      Write-Host "    ok: Phase-8 machine-line parse-contract fixtures pass (band/buckets/exit regexes match their contract)." -ForegroundColor Green
    }
  }

  # 6. $NumTok fuzz gate: every machine-line number token must accept every
  #    sign/format variant an emitter is allowed to print (negative, positive
  #    without a sign, forced '+', zero, exponent).  The 2026-08-17 sumR flip
  #    proved the failure mode: the EA printed a positive sumR without '+',
  #    the old ([+-]...) regex stopped matching, and both gates bailed with
  #    "no machine line" instead of evaluating the flip.  This gate fuzzes
  #    EVERY $NumTok interpolation site in this file so a future emitter
  #    format change (a %g switch, a dropped forced sign, an exponent form)
  #    fails the loop HERE, in seconds, instead of at the first live flip.
  #    Each row's `pattern` must appear verbatim in this file (the table plus
  #    at least one real use site); the occurrence count is the drift check —
  #    editing a use-site regex without updating the table fails the run.
  $fuzzVariants = @(
    @{ value = '-36.964';    label = 'negative' },
    @{ value = '60.496';     label = 'positive (no sign)' },
    @{ value = '+60.496';    label = 'forced plus' },
    @{ value = '0.000';      label = 'zero' },
    @{ value = '-1.2e-05';   label = 'exponent (small)' },
    @{ value = '6.0496e+01'; label = 'exponent (large)' }
  )
  $fuzzRows = @(
    @{ label = 'EA [PHASE10] sumR';
       template = '[PHASE10] trades=238 exits=stop:100,trail:50,target:80,time:8 sumR={N} hit=12.00% avg_rr=1.20 floor=30.0% floor_verdict=NOT_BEAT risk_vetoes=318 exec_rejects=0';
       pattern = 'trades=(\d+) exits=stop:(\d+),trail:(\d+),target:(\d+),time:(\d+) sumR=$NumTok hit=([\d.]+)% avg_rr=([\d.]+) floor=([\d.]+)% floor_verdict=(BEAT|NOT_BEAT) risk_vetoes=(\d+) exec_rejects=(\d+)' },
    @{ label = 'BandBackTests depth-bucket exp';
       template = '[BANDBT]   depth <= 1.25:  n= 86  hit=31.4%  exp={N}R';
       pattern = 'depth <= ([\d.]+):\s+n=\s*(\d+)\s+hit=([\d.]+)%\s+exp=${NumTok}R' },
    @{ label = 'BandBackTests vol-regime exp';
       template = '[BANDBT]   vol<=1.25    n=1527 hit= 25.3% exp={N}R sumR=+22.0R';
       pattern = 'vol(<=1\.25|>1\.25)\s+n=\s*(\d+)\s+hit=\s*([\d.]+)%\s+exp=${NumTok}R' },
    @{ label = 'phase7 defaults sumR_py';
       template = '[PHASE7-REAL] mode=defaults bars=1000 signals=500 approved=480 vetoed=20 trades_py=480 trades_mq=480 sumR_py={N} sumR_mq=-36.96 grace_saved=12 trail_converted=8';
       pattern = 'sumR_py=$NumTok' },
    @{ label = 'phase7 defaults sumR_mq';
       template = '[PHASE7-REAL] mode=defaults bars=1000 signals=500 approved=480 vetoed=20 trades_py=480 trades_mq=480 sumR_py=-36.96 sumR_mq={N} grace_saved=12 trail_converted=8';
       pattern = 'sumR_mq=$NumTok' },
    @{ label = 'phase8 band exp/sumR';
       template = '[PHASE8-ANALYTICS] band n=65 hit=44.62% exp={N}R sumR={N}R maxDD=1.10R floor=30.0% beats=yes';
       pattern = 'n=(\d+) hit=([\d.]+)% exp=${NumTok}R sumR=${NumTok}R maxDD=([\d.]+)R floor=([\d.]+)% beats=(yes|no)' },
    @{ label = 'phase8 buckets strong/weak exp';
       template = '[PHASE8-ANALYTICS] buckets strong n=22 exp={N}R hit=18.18% | weak n=59 exp={N}R hit=8.47%';
       pattern = 'strong n=(\d+) exp=${NumTok}R hit=([\d.]+)% \| weak n=(\d+) exp=${NumTok}R hit=([\d.]+)%' },
    @{ label = 'R_100 four-leg leg expectancy';
       template = 'expectancy_r={N}';
       pattern = '^expectancy_r=$NumTok' },
    @{ label = 'CLI reference expectancy_r';
       template = 'expectancy_r={N}';
       pattern = 'expectancy_r=$NumTok' },
    @{ label = 'sniper-OHLC delta_max';
       template = '[SNIPER-OHLC] delta_max={N} threshold=5.00 verdict=OK wick_sumR=+88.16 close5_delta={N} close1_delta={N} wick1_delta={N} band_ohlc_delta=+92.47';
       pattern = 'delta_max=$NumTok threshold=$NumTok verdict=(OK|FLIP) wick_sumR=$NumTok close5_delta=$NumTok close1_delta=$NumTok wick1_delta=$NumTok band_ohlc_delta=$NumTok' }
  )
  $fuzzScript = Get-Content $PSCommandPath -Raw
  $fuzzFails = 0
  foreach ($row in $fuzzRows) {
    $occ = ([regex]::Matches($fuzzScript, [regex]::Escape($row.pattern))).Count
    if ($occ -lt 2) {
      $problems += "$($row.label): regex text not found verbatim in this file ($occ occurrence(s)) — the fuzz table is stale (a use-site regex was edited without the table, or the table entry drifted)"
      continue
    }
    $re = $row.pattern.Replace('${NumTok}', $NumTok).Replace('$NumTok', $NumTok)
    foreach ($v in $fuzzVariants) {
      $line = $row.template.Replace('{N}', $v.value)
      if (-not [regex]::Match($line, $re).Success) {
        $problems += "$($row.label): regex bails on '$($v.label)' value '$($v.value)' — line: $line"
        $fuzzFails++
      }
    }
  }
  # Negative control: the pre-$NumTok sign-required form must STILL bail on a
  # no-sign positive (proves this gate discriminates the sign class) and must
  # still parse a signed negative.
  $oldSumR = 'sumR=([+-][\d.]+) hit='
  if ([regex]::Match('[PHASE10] trades=238 exits=stop:100,trail:50,target:80,time:8 sumR=60.496 hit=12.00%', $oldSumR).Success) {
    $problems += '$NumTok fuzz negative control: sign-required pattern still parses a no-sign positive — the sign-optional fix regressed'
    $fuzzFails++
  }
  if (-not [regex]::Match('[PHASE10] trades=238 exits=stop:100,trail:50,target:80,time:8 sumR=-36.964 hit=12.00%', $oldSumR).Success) {
    $problems += '$NumTok fuzz negative control: sign-required pattern fails to parse a signed negative — control is broken'
    $fuzzFails++
  }
  if ($fuzzFails -eq 0) {
    Write-Host "    ok: $NumTok fuzz gate passes — all $($fuzzRows.Count) machine-line regexes parse every sign/format variant (incl. exponent)." -ForegroundColor Green
  }

  # 7. [VERIFY] summary-line byte-stability gate: the email loop parses the
  #    `[VERIFY] summary ok=...` line's exact shape (token order, failed=
  #    slug vocabulary).  verify_verifyline_fixtures.ps1 extracts the live
  #    Get-VerifySummaryLine / Get-FirstProblem functions out of THIS file
  #    and asserts byte-stable output against synthetic PASS/FAIL/SKIP rows —
  #    a future edit that shifts the shape fails the loop in pre-flight.
  $verifyLineFixtures = Join-Path $scriptRoot "verify_verifyline_fixtures.ps1"
  if (-not (Test-Path $verifyLineFixtures)) {
    Write-Host "    WARNING: $verifyLineFixtures missing — [VERIFY] summary-line byte-stability gate NOT run (restore it; the email loop's parse contract is unprotected)." -ForegroundColor Yellow
  } else {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $verifyLineFixtures
    if ($LASTEXITCODE -ne 0) {
      $problems += "[VERIFY] summary-line byte-stability gate FAILED (verify_verifyline_fixtures.ps1 exit $LASTEXITCODE) — the summary line's shape or slug vocabulary drifted; fix verify_all.ps1 and the fixture together"
    } else {
      Write-Host "    ok: [VERIFY] summary-line fixtures pass (line shape + problem slugs are byte-stable)." -ForegroundColor Green
    }
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
    $m = [regex]::Match($ln, "depth <= ([\d.]+):\s+n=\s*(\d+)\s+hit=([\d.]+)%\s+exp=${NumTok}R")
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
    $m = [regex]::Match($ln, "vol(<=1\.25|>1\.25)\s+n=\s*(\d+)\s+hit=\s*([\d.]+)%\s+exp=${NumTok}R")
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

# --- multi-seed stability of the depth-split cells ---------------------------
# The suite's per-signal geometry sweep (MathSrand(InpGeomSeed)) draws
# z_entry/stop_mult for EVERY gated signal, so a single seed (default 42) is
# ONE sample of a reshuffle distribution.  Measured 2026-08-12 across 5 seeds
# at RR 3.0 (mql5/seed_sweep.ps1): the cap-2.00 reference cell's exp spans
# -0.079R..+0.111R (mean +0.023R, spread 0.190R ~= 8x the mean) and the
# shallow <=1.25 cell flips sign (-0.257R..+0.256R).  A single-seed positive
# is not distinguishable from seed noise, so the multi-seed gate below FAILS
# when the cell MEANS are unstable — the loop then certifies cells on the
# averaged mean, not a lucky draw.  Hit spread is reported but NOT gated:
# the measured hit spread (4.8pp at n~320) is within counting noise, while
# exp is the decision metric and swings an order of magnitude wider.
# Rules (both reference cells must pass):
#   1. mean exp >= +0.05R         (positive after seed averaging)
#   2. exp spread <= 0.25R        (no quarter-R swing between seeds)
#   3. small positive means are fragile: if mean < 0.10R, spread must stay
#      under 3x the mean (otherwise the mean is noise, not signal)
function Test-SeedStability([object[]]$rows) {
  # rows: @{ n125; hit125; exp125; n200; hit200; exp200 } — one per seed.
  $msgs = @()
  $stats = @()
  if ($rows.Count -lt 3) {
    return @{ ok = $false; msgs = @("need >= 3 seeds with parsed rows, got $($rows.Count)"); stats = @() }
  }
  foreach ($cell in @('125', '200')) {
    $nTag = 'n' + $cell; $hTag = 'hit' + $cell; $eTag = 'exp' + $cell
    $ns   = @($rows | ForEach-Object { $_.$nTag })
    $hits = @($rows | ForEach-Object { $_.$hTag })
    $exps = @($rows | ForEach-Object { $_.$eTag })
    $capLabel = if ($cell -eq '125') { '<=1.25' } else { '<=2.00' }
    $meanN   = ($ns   | Measure-Object -Average).Average
    $meanH   = ($hits | Measure-Object -Average).Average
    $hSpread = ($hits | Measure-Object -Maximum).Maximum - ($hits | Measure-Object -Minimum).Minimum
    $meanE   = ($exps | Measure-Object -Average).Average
    $eSpread = ($exps | Measure-Object -Maximum).Maximum - ($exps | Measure-Object -Minimum).Minimum
    $stats += "cap $capLabel exp-mean=$('{0:+0.000;-0.000}' -f $meanE)R spread=$('{0:+0.000;-0.000}' -f $eSpread)R hit-mean=$('{0:0.0}' -f $meanH)% spread=$('{0:0.0}' -f $hSpread)pp n-mean=$('{0:0}' -f $meanN)"
    if ($meanE -lt 0.05) {
      $msgs += "cap $capLabel mean exp $('{0:+0.000;-0.000}' -f $meanE)R < +0.05R floor — the cell is NOT positive after seed averaging (single-seed positives were noise)"
    }
    if ($eSpread -gt 0.25) {
      $msgs += "cap $capLabel exp spread $('{0:+0.000;-0.000}' -f $eSpread)R > 0.25R — cell mean swings a quarter-R across seeds"
    }
    if ($meanE -lt 0.10 -and $eSpread -gt 3.0 * $meanE) {
      $ratio = $eSpread / [math]::Max($meanE, 0.001)
      $msgs += "cap $capLabel exp spread $('{0:+0.000;-0.000}' -f $eSpread)R is $('{0:0.0}' -f $ratio)x the $('{0:+0.000;-0.000}' -f $meanE)R mean — small mean not distinguishable from seed noise"
    }
  }
  return @{ ok = ($msgs.Count -eq 0); msgs = $msgs; stats = $stats }
}

# --- run the depth-split gate across N seeds ---------------------------------
# Compiles BandBackTests once (inputs arrive via the .set, not the build), then
# runs it in the tester once per seed (~25s each).  Each run's depth rows are
# parsed from the last block of the accumulated tester log; the rows feed
# Test-SeedStability.  Any seed whose run itself fails (TESTER_ERROR or a
# depth-split/floor/vol contract break) invalidates the multi-seed mean.
# -Inputs overrides are honored (InpGeomSeed is swept, the rest pass through).
function Invoke-SeedSweepGate {
  $seedList = @($Seeds -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
  if ($seedList.Count -lt 3) {
    return @{ ok = $false; skipped = $false; detail = "seed sweep needs >= 3 seeds, got $($seedList.Count) from -Seeds '$Seeds'" }
  }
  Write-Step "Seed-sweep depth gate: $($seedList.Count) seeds [$($seedList -join ', ')] (~25s each)..."
  $mq5src  = Join-Path $buildDir "Tests\BandBackTests.mq5"
  $compLog = Join-Path $buildDir "compile_BandBackTests_sweep"
  $c = Invoke-Compile $mq5src $compLog
  if (-not $c.ok) { return @{ ok = $false; skipped = $false; detail = "seed sweep compile failed: $($c.detail)" } }
  $ex5 = Join-Path $buildDir "Tests\BandBackTests.ex5"
  if (-not (Test-Path $ex5)) { return @{ ok = $false; skipped = $false; detail = "seed sweep: no BandBackTests.ex5 produced" } }
  Copy-Item $ex5 (Join-Path $termTree "Tests\BandBackTests.ex5") -Force

  $testerProfiles = Join-Path $TerminalDataFolder "MQL5\Profiles\Tester"
  $logFile = Join-Path $testerLogsDir ($todayStamp + ".log")
  $rows = @(); $failSeeds = @()
  foreach ($seed in $seedList) {
    foreach ($setName in @("BandBackTests.set", "BandBack.set")) {
      $setPath = Join-Path $testerProfiles $setName
      if (Test-Path $setPath) { Remove-Item $setPath -Force -ErrorAction SilentlyContinue }
    }
    # The sweep's own axis first, then any -Inputs pass through (stale sets are
    # purged above and again after the run, so the tester never re-pins them).
    $setLines = @("InpGeomSeed=$seed||$seed||0.0||10000.0||N")
    foreach ($pair in ($Inputs -split ';')) {
      $kv = $pair -split '=', 2
      if ($kv.Count -ne 2) { continue }
      $nm = $kv[0].Trim(); $val = $kv[1].Trim()
      if ($nm -eq 'InpGeomSeed') { continue }
      if ($val -eq 'true' -or $val -eq 'false') {
        $setLines += "$nm=$val||false||0||true||N"
      } else {
        $setLines += "$nm=$val||$val||0.0||10000.0||N"
      }
    }
    $setPath = Join-Path $testerProfiles "BandBackTests.set"
    [System.IO.File]::WriteAllText($setPath, ($setLines -join "`r`n"), [System.Text.Encoding]::Unicode)
    $port = Get-FreePort 3001
    $from = (Get-Date).AddDays(-$RangeDays).ToString("yyyy.MM.dd")
    $to   = (Get-Date).ToString("yyyy.MM.dd")
    $ini = Join-Path $TerminalDataFolder ("verify_BandBackTests_seed$seed.ini")
    $iniContent = @(
      "[Tester]",
      "Expert=MITEMSHUB_AI\Tests\BandBackTests",
      "ExpertParameters=BandBackTests.set",
      "Symbol=$Symbol",
      "Period=M5",
      "Model=1",
      "ExecutionMode=0",
      "Optimization=0",
      "OptimizationCriterion=0",
      "FromDate=$from",
      "ToDate=$to",
      "ForwardMode=0",
      "Report=verify_BandBackTests",
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
    Write-Host "    seed $seed running in Strategy Tester (agent port $port)..."
    $r = Invoke-TesterSuite "BandBackTests" $ini
    Remove-Item $ini -Force -ErrorAction SilentlyContinue
    foreach ($setName in @("BandBackTests.set", "BandBack.set")) {
      $setPath = Join-Path $testerProfiles $setName
      if (Test-Path $setPath) { Remove-Item $setPath -Force -ErrorAction SilentlyContinue }
    }
    if ($r.status -ne "PASS") {
      $failSeeds += "$seed($($r.status))"
      Write-Host "    seed $($seed): $($r.status) — $($r.detail)" -ForegroundColor Red
      continue
    }
    # This seed's rows = the LAST run block of the accumulated tester log.
    $lines = @()
    if (Test-Path $logFile) { $lines = Get-Content $logFile -Encoding Unicode }
    $startIdx = -1
    for ($i = 0; $i -lt $lines.Count; $i++) { if ($lines[$i] -match 'tester backtest on SYN75 M5 starting') { $startIdx = $i } }
    if ($startIdx -ge 0) { $lines = @($lines[$startIdx..($lines.Count - 1)]) }
    $d125 = $null; $d200 = $null
    foreach ($ln in $lines) {
      $m = [regex]::Match($ln, "depth <= ([\d.]+):\s+n=\s*(\d+)\s+hit=([\d.]+)%\s+exp=${NumTok}R")
      if ($m.Success) {
        $cv = [pscustomobject]@{ cap = [double]$m.Groups[1].Value; n = [long]$m.Groups[2].Value; hit = [double]$m.Groups[3].Value; exp = [double]$m.Groups[4].Value }
        if ($cv.cap -eq 1.25) { $d125 = $cv } elseif ($cv.cap -eq 2.00) { $d200 = $cv }
      }
    }
    $rows += [pscustomobject]@{
      n125 = if ($d125) { $d125.n } else { 0 }; hit125 = if ($d125) { $d125.hit } else { 0.0 }; exp125 = if ($d125) { $d125.exp } else { 0.0 }
      n200 = if ($d200) { $d200.n } else { 0 }; hit200 = if ($d200) { $d200.hit } else { 0.0 }; exp200 = if ($d200) { $d200.exp } else { 0.0 }
    }
    Write-Host ("    seed {0}: <=1.25 n={1} hit={2:0.0}% exp={3:+0.000;-0.000}R | <=2.00 n={4} hit={5:0.0}% exp={6:+0.000;-0.000}R" -f `
      $seed, $(if ($d125) { $d125.n } else { 0 }), $(if ($d125) { $d125.hit } else { 0 }), $(if ($d125) { $d125.exp } else { 0 }), `
      $(if ($d200) { $d200.n } else { 0 }), $(if ($d200) { $d200.hit } else { 0 }), $(if ($d200) { $d200.exp } else { 0 }))
  }
  if ($failSeeds.Count -gt 0) {
    return @{ ok = $false; skipped = $false; detail = "seed run(s) failed: $($failSeeds -join ', ') — a broken seed run invalidates the multi-seed mean" }
  }
  if ($rows.Count -lt 3) {
    return @{ ok = $false; skipped = $false; detail = "only $($rows.Count) seeds produced parseable depth rows (< 3) — cannot aggregate" }
  }
  $st = Test-SeedStability $rows
  $detail = "seeds=$($seedList -join ',') | " + ($st.stats -join " | ")
  if ($st.ok) {
    Write-Host "    seed-sweep depth gate: STABLE — cell means survive seed averaging." -ForegroundColor Green
  } else {
    $detail += " | UNSTABLE: " + ($st.msgs -join " ; ")
    Write-Host "    seed-sweep depth gate: UNSTABLE — $($st.msgs -join ' ; ')" -ForegroundColor Red
  }
  return @{ ok = $st.ok; skipped = $false; detail = $detail }
}

# --- paper->live execution parity contract (Python harness) -----------------
# The Python engine can execute an approved call via the SIMULATED backend
# (forward-demo paper fills), the MT5 python-API backend (the Python
# CTrade-equivalent), and the MQL5 SynthCallExecutor EA (which polls the call
# file ea_emitter writes).  These must behave as ONE execution layer.
# execution_parity_check.py replays deterministic signals + candle paths
# through the simulated and live backends (live runs against an in-memory
# CTrade-equivalent simulator — no MT5 dependency), asserts every submit /
# position-count / outcome agrees, verifies the live path rejects cleanly on
# broker rejection, and checks the EA call record carries exactly the levels
# executed.  A regression here — e.g. a close that stops being parity-clean —
# must fail the scheduled loop the same way the depth-split contract does.
function Invoke-ExecutionParityCheck {
  $py = Get-Command python -ErrorAction SilentlyContinue
  if (-not $py) {
    return @{ ok = $false; skipped = $true; detail = "python not on PATH — execution parity contract NOT run (install Python to arm it)" }
  }
  Write-Step "Running paper->live execution parity contract (execution_parity_check.py)..."
  $script = Join-Path $scriptRoot "execution_parity_check.py"
  if (-not (Test-Path $script)) {
    return @{ ok = $false; skipped = $false; detail = "execution_parity_check.py missing under $scriptRoot — parity contract cannot run" }
  }
  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = "python"
  $psi.Arguments = '"' + $script + '"'
  $psi.RedirectStandardOutput = $true
  $psi.RedirectStandardError = $true
  $psi.UseShellExecute = $false
  $proc = [System.Diagnostics.Process]::Start($psi)
  $stdout = $proc.StandardOutput.ReadToEnd()
  $stderr = $proc.StandardError.ReadToEnd()
  if (-not $proc.WaitForExit(300000)) {
    $proc.Kill()
    return @{ ok = $false; skipped = $false; detail = "execution parity check TIMED OUT (300s) — harness hung; treat as regression" }
  }
  $exit = $proc.ExitCode
  if ($stderr) { Write-Host "    (parity stderr): $($stderr.Trim())" -ForegroundColor Yellow }
  # Last [PARITY] verdict line wins (PASS / FAIL + detail).
  $last = $null
  foreach ($ln in ($stdout -split "`r?`n")) {
    $m = [regex]::Match($ln, [regex]::Escape('[PARITY]') + ' (PASS|FAIL): (.+)')
    if ($m.Success) { $last = $m }
  }
  if (-not $last) {
    return @{ ok = $false; skipped = $false; detail = "no [PARITY] verdict in harness output (exit $exit)" }
  }
  $verdict = $last.Groups[1].Value
  $detail = $last.Groups[2].Value
  $ok = ($verdict -ne 'FAIL')
  Write-Host "    execution parity contract: $verdict — $detail" -ForegroundColor $(if ($ok) { "Green" } else { "Red" })
  return @{ ok = $ok; skipped = $false; detail = "$verdict — $detail" }
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

# --- run the Phase-6/7 real-corpus gate contracts (Python harnesses) ---------
# phase6_real_corpus_check.py and phase7_real_corpus_check.py replay the real
# R_75 tick corpus through the MQL5 mirrors AND the real production Python
# engines (risk layer: RiskEngine; execution layer: SimulatedExecutionBackend),
# emitting [PHASE6-REAL] / [PHASE7-REAL] machine lines per mode.  Fast (~3s per
# invocation on the current corpus) and fully self-contained.
#
# Contracts (measured 2026-08-15 on the ~217h corpus):
#   phase6 aligned: veto_agree AND state_ok AND stake_ok must be 100% — the
#       risk engines are behaviorally identical on the shared gates.
#   phase6 defaults: disagreements are EXPECTED config drift (Python stricter
#       on daily-loss/consecutive; MQL5 adds trades/day + trades/hour caps + the
#       WEAK-verdict veto) — parse-only, but a crash/timeout still fails.
#   phase7 aligned: entry+exit parity must be 100% AND the min-RR 1.2 float
#       boundary must agree exactly (rr_boundary_disagree = 0).
#   phase7 defaults: the management edge must hold — the closed-candle grace +
#       BE trail must keep the MQL5 lane ahead of the Python wick journal on the
#       same entry set (sumR_mq > sumR_py, measured +104.6 vs -82.4) and the
#       grace/trail conversions must be present (grace_saved + trail_converted
#       > 0, measured 201 + 259).  A refactor that breaks the grace, the trail,
#       or the mirror flips these and fails the loop like the sniper gate.
function Invoke-RealCorpusGate {
  $py = Get-Command python -ErrorAction SilentlyContinue
  if (-not $py) {
    return @{ ok = $false; skipped = $true; detail = "python not on PATH — real-corpus gate contracts NOT run (install Python to arm them)" }
  }
  $harnesses = @(
    @{ script = "phase6_real_corpus_check.py"; mode = "aligned"  },
    @{ script = "phase6_real_corpus_check.py"; mode = "defaults" },
    @{ script = "phase7_real_corpus_check.py"; mode = "aligned"  },
    @{ script = "phase7_real_corpus_check.py"; mode = "defaults" }
  )
  $problems = @()
  $summaries = @()
  foreach ($h in $harnesses) {
    $script = Join-Path $scriptRoot $h.script
    if (-not (Test-Path $script)) {
      $problems += "$($h.script) missing under $scriptRoot — real-corpus gate cannot run"
      continue
    }
    Write-Step "Running real-corpus gate: $($h.script) --mode $($h.mode)"
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = "python"
    $psi.Arguments = '"' + $script + '" --mode ' + $h.mode
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.UseShellExecute = $false
    $proc = [System.Diagnostics.Process]::Start($psi)
    $stdout = $proc.StandardOutput.ReadToEnd()
    $stderr = $proc.StandardError.ReadToEnd()
    if (-not $proc.WaitForExit(900000)) {
      $proc.Kill()
      $problems += "$($h.script) --mode $($h.mode) TIMED OUT (900s) — harness hung; treat as regression"
      continue
    }
    if ($stderr) { Write-Host "    (stderr): $($stderr.Trim())" -ForegroundColor Yellow }
    $line = ($stdout -split "`r?`n" | Where-Object { $_ -match 'PHASE[67]-REAL' } | Select-Object -Last 1)
    if (-not $line) {
      $problems += "$($h.script) --mode $($h.mode) emitted no [PHASE[67]-REAL] machine line (exit $($proc.ExitCode)) — harness broken or corpus too thin"
      continue
    }
    $line = $line.Trim()
    $is6 = $h.script -match 'phase6'
    if ($is6) {
      if ($h.mode -eq 'aligned') {
        $va = [regex]::Match($line, 'veto_agree=(\d+)/(\d+) \(([\d.]+)%\)')
        $so = [regex]::Match($line, 'state_ok=(\d+)/(\d+)')
        $sk = [regex]::Match($line, 'stake_ok=(\d+)/(\d+)')
        if (-not $va.Success -or -not $so.Success -or -not $sk.Success) {
          $problems += "phase6 aligned machine line unparseable: $line"
          continue
        }
        $agreeN = [int]$va.Groups[2].Value; $stateN = [int]$so.Groups[2].Value; $stakeN = [int]$sk.Groups[2].Value
        if ($agreeN -le 0 -or [int]$va.Groups[1].Value -ne $agreeN) { $problems += "phase6 aligned veto parity dropped below 100%: $line" }
        if ($stateN -le 0 -or [int]$so.Groups[1].Value -ne $stateN) { $problems += "phase6 aligned stateful parity dropped below 100%: $line" }
        if ($stakeN -le 0 -or [int]$sk.Groups[1].Value -ne $stakeN)   { $problems += "phase6 aligned stake parity dropped below 100%: $line" }
        $summaries += "phase6 aligned $([int]$va.Groups[1].Value)/$agreeN veto 100%"
      } else {
        # defaults: config drift is expected (documented above) - parse-only.
        $summaries += "phase6 defaults ran (drift ok)"
      }
    } else {
      if ($h.mode -eq 'aligned') {
        $par = [regex]::Match($line, 'parity=(\d+)/(\d+) \(([\d.]+)%\)')
        $rr = [regex]::Match($line, 'rr_boundary_disagree=(\d+)')
        if (-not $par.Success -or -not $rr.Success) {
          $problems += "phase7 aligned machine line unparseable: $line"
          continue
        }
        $traded = [int]$par.Groups[2].Value
        if ($traded -le 0 -or [int]$par.Groups[1].Value -ne $traded) { $problems += "phase7 aligned entry+exit parity dropped below 100%: $line" }
        if ([int]$rr.Groups[1].Value -ne 0)                          { $problems += "phase7 aligned min-RR float boundary disagrees: $line" }
        $summaries += "phase7 aligned $([int]$par.Groups[1].Value)/$traded parity 100%"
      } else {
        $spy = [regex]::Match($line, "sumR_py=$NumTok")
        $smq = [regex]::Match($line, "sumR_mq=$NumTok")
        $gs  = [regex]::Match($line, 'grace_saved=(\d+)')
        $tc  = [regex]::Match($line, 'trail_converted=(\d+)')
        if (-not $spy.Success -or -not $smq.Success -or -not $gs.Success -or -not $tc.Success) {
          $problems += "phase7 defaults machine line unparseable: $line"
          continue
        }
        $rPy = [double]$spy.Groups[1].Value
        $rMq = [double]$smq.Groups[1].Value
        $conversions = [int]$gs.Groups[1].Value + [int]$tc.Groups[1].Value
        if ($conversions -le 0) { $problems += "phase7 defaults grace/trail conversions collapsed to zero — closed-candle grace or BE trail regressed: $line" }
        if ($rMq -le $rPy)      { $problems += "phase7 defaults management edge FLIPPED: MQL5 closed-candle+trail sumR $rMq <= Python wick journal $rPy — exit-split regression: $line" }
        $summaries += "phase7 defaults sumR $rMq vs py $rPy (grace $($gs.Groups[1].Value)+trail $($tc.Groups[1].Value))"
      }
    }
  }
  $detail = if ($problems.Count -eq 0) { "PASS - " + ($summaries -join ' | ') } else { "FAIL - " + ($problems -join '; ') }
  $ok = ($problems.Count -eq 0)
  Write-Host "    real-corpus gate: $(if ($ok) { 'PASS' } else { 'FAIL' }) — $detail" -ForegroundColor $(if ($ok) { "Green" } else { "Red" })
  return @{ ok = $ok; skipped = $false; detail = $detail }
}

# --- Phase-8 analytics gate contract -----------------------------------------
# phase8_analytics_check.py feeds a REAL band backtest (CLI-parity-verified)
# through the Phase-8 analytics stack and emits machine lines.  Contract:
#   - [PARITY] verdict=MATCH      -> the harness replication matches the CLI
#     `backtest-vol --mode band` (trades / win_rate / expectancy_r) — the
#     whole "this is a real band backtest" guarantee.
#   - band + buckets + exit lines must parse -> a refactor that drops the
#     analytics report or one of the splits fails loudly.
#   - structural consistency: strong + weak == total n (the buckets partition
#     the set), stop + trail + target + time == n (every outcome has an exit
#     reason), floor within the [10,60] clamp, and the beats verdict must be
#     consistent with (n >= min_samples AND hit >= floor).
function Invoke-Phase8Gate {
  $py = Get-Command python -ErrorAction SilentlyContinue
  if (-not $py) {
    return @{ ok = $false; skipped = $true; detail = "python not on PATH - Phase-8 analytics gate NOT run (install Python to arm it)" }
  }
  $script = Join-Path $scriptRoot "phase8_analytics_check.py"
  if (-not (Test-Path $script)) {
    return @{ ok = $false; skipped = $false; detail = "phase8_analytics_check.py missing under $scriptRoot - Phase-8 analytics gate cannot run" }
  }
  Write-Step "Running Phase-8 analytics gate: phase8_analytics_check.py (CLI parity + analytics machine lines)"
  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = "python"
  $psi.Arguments = '"' + $script + '"'
  $psi.RedirectStandardOutput = $true
  $psi.RedirectStandardError = $true
  $psi.UseShellExecute = $false
  $proc = [System.Diagnostics.Process]::Start($psi)
  $stdout = $proc.StandardOutput.ReadToEnd()
  $stderr = $proc.StandardError.ReadToEnd()
  if (-not $proc.WaitForExit(1500000)) {
    $proc.Kill()
    return @{ ok = $false; skipped = $false; detail = "phase8_analytics_check.py TIMED OUT (1500s) - harness hung; treat as regression" }
  }
  if ($stderr) { Write-Host "    (stderr): $($stderr.Trim())" -ForegroundColor Yellow }
  $problems = @()
  $summaries = @()

  $par = ($stdout -split "`r?`n" | Where-Object { $_ -match '\[PARITY\] verdict=' } | Select-Object -Last 1)
  if (-not $par) {
    $problems += "no [PARITY] verdict line - harness/CLI reference failed; treat as regression"
  } elseif ($par -match 'verdict=(MATCH|MISMATCH)' -and $Matches[1] -ne 'MATCH') {
    $problems += "band replication does NOT match the CLI backtest-vol reference (parity mismatch) - the 'real band backtest' guarantee broke"
  } else {
    $summaries += "parity=MATCH"
  }

  $band = ($stdout -split "`r?`n" | Where-Object { $_ -match '\[PHASE8-ANALYTICS\] band n=' } | Select-Object -Last 1)
  $bkts = ($stdout -split "`r?`n" | Where-Object { $_ -match '\[PHASE8-ANALYTICS\] buckets strong' } | Select-Object -Last 1)
  $exit = ($stdout -split "`r?`n" | Where-Object { $_ -match '\[PHASE8-ANALYTICS\] exit stop' } | Select-Object -Last 1)
  if (-not $band -or -not $bkts -or -not $exit) {
    $problems += "Phase-8 analytics machine lines missing (band/buckets/exit) - the analytics report or its splits regressed"
  } else {
    $bm = [regex]::Match($band, "n=(\d+) hit=([\d.]+)% exp=${NumTok}R sumR=${NumTok}R maxDD=([\d.]+)R floor=([\d.]+)% beats=(yes|no)")
    $km = [regex]::Match($bkts, "strong n=(\d+) exp=${NumTok}R hit=([\d.]+)% \| weak n=(\d+) exp=${NumTok}R hit=([\d.]+)%")
    $em = [regex]::Match($exit, 'stop n=(\d+) trail n=(\d+) target n=(\d+) time n=(\d+)')
    if (-not $bm.Success -or -not $km.Success -or -not $em.Success) {
      $problems += "Phase-8 analytics machine lines unparseable: band='$band' buckets='$bkts' exit='$exit'"
    } else {
      $n      = [int]$bm.Groups[1].Value
      $hit    = [double]$bm.Groups[2].Value
      $exp    = [double]$bm.Groups[3].Value
      $sumR   = [double]$bm.Groups[4].Value
      $maxDD  = [double]$bm.Groups[5].Value
      $floor  = [double]$bm.Groups[6].Value
      $beats  = $bm.Groups[7].Value
      $strongN = [int]$km.Groups[1].Value
      $strongE = [double]$km.Groups[2].Value
      $weakN   = [int]$km.Groups[4].Value
      $weakE   = [double]$km.Groups[5].Value
      $stopN  = [int]$em.Groups[1].Value
      $trailN = [int]$em.Groups[2].Value
      $targN  = [int]$em.Groups[3].Value
      $timeN  = [int]$em.Groups[4].Value

      if ($n -le 0) { $problems += "Phase-8 analytics n=0 - no trades; cannot gate" }
      if ($strongN + $weakN -ne $n) { $problems += "confidence buckets do not partition the set: strong $strongN + weak $weakN != n $n" }
      if ($stopN + $trailN + $targN + $timeN -ne $n) { $problems += "exit reasons do not account for every outcome: stop+trail+target+time = $($stopN + $trailN + $targN + $timeN) != n $n" }
      if ($floor -lt 10.0 -or $floor -gt 60.0) { $problems += "break-even floor $floor% outside the [10,60] clamp - floor math regressed" }
      if ($beats -eq 'yes' -and -not ($n -ge 10 -and $hit -ge $floor)) { $problems += "floor verdict says BEATS but hit $hit% < floor $floor% or n $n < 10 - inconsistent" }
      if ($beats -eq 'no' -and ($n -ge 10 -and $hit -ge $floor)) { $problems += "floor verdict says does NOT beat but hit $hit% >= floor $floor% with n $n - inconsistent" }
      if ($maxDD -lt 0.0) { $problems += "negative maxDD - drawdown math regressed" }
      $summaries += "band n=$n hit=$hit% exp=$exp R floor=$floor% beats=$beats | strong n=$strongN exp=$strongE | weak n=$weakN exp=$weakE"
    }
  }
  $detail = if ($problems.Count -eq 0) { "PASS - " + ($summaries -join ' | ') } else { "FAIL - " + ($problems -join '; ') }
  $ok = ($problems.Count -eq 0)
  Write-Host "    phase-8 analytics gate: $(if ($ok) { 'PASS' } else { 'FAIL' }) - $detail" -ForegroundColor $(if ($ok) { "Green" } else { "Red" })
  return @{ ok = $ok; skipped = $false; detail = $detail }
}

# --- calibration-sanity gate contract ------------------------------------------
# calibration_sanity_check.py loads the on-disk EGARCH calibration JSONs
# (data/garch_calibration/*.json — the exact files the live engine and the
# band reference load on startup) and verifies each fit would be accepted:
# convergence True, not rejected by _params_at_bounds (bound-pinned /
# no-clustering / absurd-NLL / bad long-run ratio), and vol_ratio inside the
# healthy band [0.02, 50].  A regenerated fit that drifts into a degenerate
# basin (the measured full-corpus R_100 case) or reports an absurd ratio must
# fail the loop loudly instead of silently seeding default priors.
function Invoke-CalibrationGate {
  $py = Get-Command python -ErrorAction SilentlyContinue
  if (-not $py) {
    return @{ ok = $false; skipped = $true; detail = "python not on PATH - calibration-sanity gate NOT run (install Python to arm it)" }
  }
  $script = Join-Path $scriptRoot "calibration_sanity_check.py"
  if (-not (Test-Path $script)) {
    return @{ ok = $false; skipped = $false; detail = "calibration_sanity_check.py missing under $scriptRoot - calibration-sanity gate cannot run" }
  }
  Write-Step "Running calibration-sanity gate: calibration_sanity_check.py (on-disk EGARCH calibration JSONs)"
  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = "python"
  $psi.Arguments = '"' + $script + '"'
  $psi.RedirectStandardOutput = $true
  $psi.RedirectStandardError = $true
  $psi.UseShellExecute = $false
  $proc = [System.Diagnostics.Process]::Start($psi)
  $stdout = $proc.StandardOutput.ReadToEnd()
  $stderr = $proc.StandardError.ReadToEnd()
  if (-not $proc.WaitForExit(300000)) {
    $proc.Kill()
    return @{ ok = $false; skipped = $false; detail = "calibration_sanity_check.py TIMED OUT (300s) - harness hung; treat as regression" }
  }
  if ($stderr) { Write-Host "    (stderr): $($stderr.Trim())" -ForegroundColor Yellow }
  $problems = @()
  $summaries = @()

  $sum = ($stdout -split "`r?`n" | Where-Object { $_ -match '\[CALIB\] summary ok=' } | Select-Object -Last 1)
  if (-not $sum) {
    $problems += "no [CALIB] summary machine line - calibration harness failed; treat as regression"
  } else {
    $sm = [regex]::Match($sum, 'summary ok=(\d+) n_problems=(\d+)')
    if (-not $sm.Success) {
      $problems += "[CALIB] summary line unparseable: $sum"
    } else {
      $okN = [int]$sm.Groups[1].Value
      $nProbs = [int]$sm.Groups[2].Value
      if ($okN -ne 1 -or $nProbs -gt 0) {
        $details = ($stdout -split "`r?`n" | Where-Object { $_ -match '\[CALIB\] problem' } | ForEach-Object { $_.Trim() })
        $problems += "calibration sanity FAILED: " + ($(if ($details) { ($details -join ' ; ') } else { "no [CALIB] problem lines" }))
      }
    }
  }
  $perSymbol = ($stdout -split "`r?`n" | Where-Object { $_ -match '\[CALIB\] symbol=' } | ForEach-Object {
    if ($_ -match 'symbol=(\S+) ok=(\d+) .* vol_ratio=([\d.]+) .* reason=(.*)$') {
      $r = $Matches[3]
      if ($Matches[2] -eq '1') { "$($Matches[1]) ok vol_ratio $r" } else { "$($Matches[1]) FAIL ($($Matches[4]))" }
    }
  })
  if ($perSymbol) { $summaries += ($perSymbol -join ' | ') }

  $detail = if ($problems.Count -eq 0) { "PASS - " + ($summaries -join ' | ') } else { "FAIL - " + ($problems -join '; ') }
  $ok = ($problems.Count -eq 0)
  Write-Host "    calibration-sanity gate: $(if ($ok) { 'PASS' } else { 'FAIL' }) - $detail" -ForegroundColor $(if ($ok) { "Green" } else { "Red" })
  return @{ ok = $ok; skipped = $false; detail = $detail }
}

# --- extract the [PHASE10] machine line for a specific bar_sec ---------------
# The integrated EA emits TWO consecutive [PHASE10] lines per run:
#   [PHASE10] bar_sec=300 garch_mode=0 drift=OFF revert=0.00 trail=0.30 grace=OFF
#   [PHASE10] trades=97 exits=... risk_vetoes=0 exec_rejects=0
# The tester log ACCUMULATES all of today's runs, so a plain "last trades line
# wins" parse is wrong the moment two EA runs with different bar_sec exist in
# the same log (P10-A at 300s + the Phase-6 risk gate at 60s).  This returns
# the trades= line that belongs to the LAST run whose bar_sec line matches
# $wantBarSec (the trades line immediately following it).
function Get-Phase10TradesLine([string]$logPath, [int]$wantBarSec) {
  $lines = @()
  if (Test-Path $logPath) { $lines = Get-Content $logPath -Encoding Unicode -ErrorAction SilentlyContinue }
  $want = ""
  for ($i = 0; $i -lt $lines.Count; $i++) {
    $bm = [regex]::Match([string]$lines[$i], '\[PHASE10\] bar_sec=(\d+)')
    if (-not $bm.Success) { continue }
    if ([int]$bm.Groups[1].Value -ne $wantBarSec) { continue }
    # the run's trades= line is the next [PHASE10] trades= line after the
    # bar_sec= line (the two prints are adjacent in OnTester)
    for ($j = $i + 1; $j -lt $lines.Count; $j++) {
      if ([string]$lines[$j] -match '\[PHASE10\] trades=') { $want = $lines[$j]; break }
    }
  }
  return $want
}

# --- R_100 four-leg head-to-head reference (the P10 matrix sign-lock) ---------
# The documented P10 matrix locks the R_100 side of the four-leg head-to-head
# (band / fade / momentum / sniper at 300s with realistic costs): ALL FOUR legs
# are NEGATIVE (band -0.591R, fade -0.198R, momentum -0.019R, sniper -0.029R,
# 2026-08-16 full-density corpus).  The sign-lock contract: if any leg's
# expectancy flips positive relative to that matrix, the loop must fail
# visibly — a sign flip means the leg's edge (or the cost model) changed
# materially and the matrix reference is stale.
# Returns @{ legs = @{label=@{trades=..; hit=..; exp=..}}; raw = $stdout } or
# $null when the CLI run itself fails (caller decides skip vs fail).
function Invoke-R100FourLegReference {
  $corpus = Join-Path $repoRoot "data\backfill\R_100_ticks.csv"
  if (-not (Test-Path $corpus)) {
    return @{ ok = $false; skipped = $true; detail = "R_100 corpus not found at $corpus - four-leg sign-lock NOT run" }
  }
  Write-Step "Running R_100 four-leg head-to-head reference (backtest-vol --compare @300s)..."
  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = "python"
  # Matrix cost basis pinned EXPLICITLY: the P10 matrix (2026-08-16) is
  # defined on realistic costs (0.05/0.05 ticks + 0.10 fee).  Relying on the
  # CLI's defaults here would silently re-baseline the four-leg sign-lock the
  # day someone edits those defaults — the audit (2026-08-17) makes them
  # explicit at every backtest-vol call site.  Risk basis stays the engine
  # default (4-streak / 2% daily) — the matrix basis; do NOT add the aligned
  # 9999/1.0 args here (that is the EA-pair basis, P10-A/P10-E only).
  $psi.Arguments = '-m synthetic_trader.cli backtest-vol --csv "' + $corpus + '" --symbol R_100 --timeframe 300 --mode band --compare --entry-slippage-ticks 0.05 --exit-slippage-ticks 0.05 --execution-penalty 0.10'
  $psi.RedirectStandardOutput = $true
  $psi.RedirectStandardError = $true
  $psi.UseShellExecute = $false
  $proc = [System.Diagnostics.Process]::Start($psi)
  $stdout = $proc.StandardOutput.ReadToEnd()
  $stderr = $proc.StandardError.ReadToEnd()
  if (-not $proc.WaitForExit(1500000)) {
    $proc.Kill()
    return @{ ok = $false; skipped = $false; detail = "R_100 four-leg reference TIMED OUT (1500s) - backtest-vol --compare hung; treat as regression" }
  }
  if ($stderr) { Write-Host "    (stderr): $($stderr.Trim())" -ForegroundColor Yellow }
  # Parse each leg's block: strategy=N / trades=N / win_rate=N% / expectancy_r=N
  $legs = @{}
  $cur = ""
  foreach ($ln in ($stdout -split "`r?`n")) {
    $sm = [regex]::Match($ln, '^strategy=(\S+)')
    if ($sm.Success) { $cur = $sm.Groups[1].Value; $legs[$cur] = @{ trades = 0; hit = 0.0; exp = 0.0; seen = $false }; continue }
    if ($cur -eq "") { continue }
    $tm = [regex]::Match($ln, '^trades=(\d+)')
    if ($tm.Success) { $legs[$cur].trades = [int]$tm.Groups[1].Value; continue }
    $hm = [regex]::Match($ln, '^win_rate=([\d.]+)%')
    if ($hm.Success) { $legs[$cur].hit = [double]$hm.Groups[1].Value; continue }
    $em = [regex]::Match($ln, "^expectancy_r=$NumTok")
    if ($em.Success) { $legs[$cur].exp = [double]$em.Groups[1].Value; $legs[$cur].seen = $true }
  }
  return @{ ok = $true; skipped = $false; legs = $legs; raw = $stdout }
}

# --- Phase-10 P10-A integration gate contract ----------------------------------
# MitemshubAI.mq5 (the integrated EA) emits [PHASE10] machine lines at the end
# of a tester run.  The Python reference is the CLI `backtest-vol --mode band`
# on the R_75 tick corpus, RE-BASELINED (2026-08-17) to the anchored fit in
# ALIGNED mode: the CLI now runs with the same permissive risk as the EA's
# aligned config (--max-consecutive-losses 9999 --max-daily-loss-frac 1.0,
# matching InpMaxConsecLosses=9999 / InpMaxDailyLossPct=1.0) so the reference
# approves every signal exactly like the EA (both load the anchored r_75.json
# GARCH fit).  Previously the reference ran with the default 4-streak / 2%
# daily-loss halts, which vetoed ~16 signals and drove the strict trade-count
# pair to EA 98 vs CLI 87 (Δ11 > 10); on the aligned basis the accepted pair
# is EA 98 vs CLI ~97 (Δ≈1).  The corpus is the WINDOWED reference
# (data\backfill\R_75_ticks.windowed.csv): union of the pre-repair head
# (Jul 30 -> Aug 09, preserved when the live file was re-created) and the live
# backfill, repaired from the terminal's M1 history, then clipped EXACTLY to
# the tester window (Jul 30 00:00 -> Aug 16 00:00) — so the CLI reference and
# the EA see identical bars and the residual Δ4 gap disappears.  The live
# collector file keeps growing for the engine; this frozen windowed file is
# the parity basis.  The gate always enforces internal consistency + a rate
# guard, and enforces the strict parity contract (|trades - 98| <= 10).
function Invoke-Phase10Gate([string]$corpus) {
  $py = Get-Command python -ErrorAction SilentlyContinue
  if (-not $py) {
    return @{ ok = $false; skipped = $true; detail = "python not on PATH - Phase-10 P10-A gate NOT run (install Python to arm it)" }
  }
  if (-not (Test-Path $corpus)) {
    return @{ ok = $false; skipped = $false; detail = "R_75 corpus not found at $corpus - Phase-10 P10-A gate cannot run" }
  }
  # --- EA machine lines from the tester log (the 300s run specifically — the
  # log also holds the Phase-6 risk gate's 60s run, which must NOT be picked
  # up here; Get-Phase10TradesLine scopes by bar_sec) ----------------------
  $logFile = Join-Path $testerLogsDir ($todayStamp + ".log")
  $eaLine = Get-Phase10TradesLine $logFile 300
  # NOTE: sumR's sign is OPTIONAL in the machine line — the EA prints a
  # leading '-' only for negative sums.  The 2026-08-17 full-loop run at
  # -TestModel 2 exposed this: the OHLC model flipped the band's sumR
  # positive (+60.496, printed without '+'), so the old ([+-]...) pattern
  # stopped matching and both machine-line gates bailed with "no machine
  # line" instead of evaluating the actual flip.
  $em = [regex]::Match([string]$eaLine,
        "trades=(\d+) exits=stop:(\d+),trail:(\d+),target:(\d+),time:(\d+) sumR=$NumTok hit=([\d.]+)% avg_rr=([\d.]+) floor=([\d.]+)% floor_verdict=(BEAT|NOT_BEAT) risk_vetoes=(\d+) exec_rejects=(\d+)")
  if (-not $em.Success) {
    return @{ ok = $false; skipped = $false; detail = "no [PHASE10] trades= machine line in $logFile - Phase10IntegrationTests did not run (or its summary regressed)" }
  }
  $eaN      = [int]$em.Groups[1].Value
  $stopN    = [int]$em.Groups[2].Value
  $trailN   = [int]$em.Groups[3].Value
  $targN    = [int]$em.Groups[4].Value
  $timeN    = [int]$em.Groups[5].Value
  $eaSumR   = [double]$em.Groups[6].Value
  $eaHit    = [double]$em.Groups[7].Value
  $eaRR     = [double]$em.Groups[8].Value
  $eaFloor  = [double]$em.Groups[9].Value
  $eaVerdict = $em.Groups[10].Value
  $eaVeto   = [int]$em.Groups[11].Value
  $eaReject = [int]$em.Groups[12].Value

  # --- CLI reference (windowed parity corpus — the phase8 gate replays the
  # live collector file; P10-A must see the tester window exactly) -----------
  Write-Step "Running Phase-10 P10-A gate: CLI reference + [PHASE10] machine-line contract"
  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = "python"
  # Realistic-cost basis pinned explicitly (same reasoning as the four-leg
  # reference): P10-A's CLI side must measure on the documented cost model,
  # not whatever the CLI defaults happen to be.  Risk args stay ALIGNED
  # (9999/1.0 = EA's InpMaxConsecLosses=9999 / InpMaxDailyLossPct=1.0).
  $psi.Arguments = '-m synthetic_trader.cli backtest-vol --csv "' + $corpus + '" --symbol R_75 --timeframe 300 --mode band --max-consecutive-losses 9999 --max-daily-loss-frac 1.0 --entry-slippage-ticks 0.05 --exit-slippage-ticks 0.05 --execution-penalty 0.10'
  $psi.RedirectStandardOutput = $true
  $psi.RedirectStandardError = $true
  $psi.UseShellExecute = $false
  $proc = [System.Diagnostics.Process]::Start($psi)
  $stdout = $proc.StandardOutput.ReadToEnd()
  $stderr = $proc.StandardError.ReadToEnd()
  if (-not $proc.WaitForExit(900000)) {
    $proc.Kill()
    return @{ ok = $false; skipped = $false; detail = "CLI reference TIMED OUT (900s) - backtest-vol hung; treat as regression" }
  }
  if ($stderr) { Write-Host "    (stderr): $($stderr.Trim())" -ForegroundColor Yellow }
  $tradesM = [regex]::Match($stdout, 'trades=(\d+)')
  $winM    = [regex]::Match($stdout, 'win_rate=([\d.]+)%')
  $expM    = [regex]::Match($stdout, "expectancy_r=$NumTok")
  if (-not $tradesM.Success -or -not $winM.Success -or -not $expM.Success) {
    return @{ ok = $false; skipped = $false; detail = "CLI reference output unparseable (no trades=/win_rate=/expectancy_r=) - treat as regression" }
  }
  $refN    = [int]$tradesM.Groups[1].Value
  $refHit  = [double]$winM.Groups[1].Value
  $refExp  = [double]$expM.Groups[1].Value

  # --- corpus density (unique M5 buckets / expected full-density buckets) --
  $dens = python -c @"
import csv, sys
buckets = set()
lo = None
hi = None
for row in csv.reader(open(r'$corpus', encoding='utf-8')):
    try:
        ep = float(row[0])
    except Exception:
        continue
    buckets.add(int(ep // 300) * 300)
    if lo is None or ep < lo:
        lo = ep
    if hi is None or ep > hi:
        hi = ep
if not buckets:
    sys.exit(2)
days = (hi - lo) / 86400.0 + 1.0
n = len(buckets)
print('%.3f %d %.2f' % (n / (days * 288.0), n, days))
"@
  $dparts = ($dens -split '\s+')
  $density = if ($dparts.Count -ge 1) { [double]$dparts[0] } else { 0.0 }
  $corpusBuckets = if ($dparts.Count -ge 2) { [int]$dparts[1] } else { 0 }

  $problems = @()
  $summaries = @()

  # --- ALWAYS: internal consistency --------------------------------------
  if ($stopN + $trailN + $targN + $timeN -ne $eaN) {
    $problems += "EA exit split does not sum to trades: stop+trail+target+time = $($stopN+$trailN+$targN+$timeN) != $eaN"
  }
  if ($eaRR -lt 1.0) { $problems += "EA avg_rr $eaRR below 1.0 - geometry regressed" }
  if ($eaFloor -lt 10.0 -or $eaFloor -gt 60.0) { $problems += "EA break-even floor $eaFloor% outside the [10,60] clamp" }
  $beatsOk = ($eaVerdict -eq 'BEAT') -and ($eaHit -ge $eaFloor -and $eaN -ge 10)
  $notBeatsOk = ($eaVerdict -eq 'NOT_BEAT') -and -not ($eaHit -ge $eaFloor -and $eaN -ge 10)
  if (-not $beatsOk -and -not $notBeatsOk) {
    $problems += "EA floor verdict '$eaVerdict' inconsistent with hit $eaHit% floor $eaFloor% n $eaN"
  }
  if ($eaVeto -ne 0 -or $eaReject -ne 0) {
    $problems += "EA aligned run had risk vetoes $eaVeto / exec rejects $eaReject (expected 0 in P10-A aligned mode)"
  }

  # --- data-state classification ------------------------------------------
  if ($density -ge 0.80) {
    # Strict contract: same-data trade-for-trade parity is enforceable.
    if ([Math]::Abs($eaN - $refN) -gt 10) { $problems += "STRICT: EA trades $eaN vs CLI $refN differ by more than 10" }
    if ([Math]::Abs($eaHit - $refHit) -gt 5.0) { $problems += "STRICT: EA hit $eaHit% vs CLI $refHit% differs by more than 5pp" }
    if (($eaSumR -lt 0) -ne ($refExp -lt 0)) { $problems += "STRICT: EA sumR $eaSumR sign disagrees with CLI expectancy $refExp" }
    $summaries += "density=${density} STRICT: EA n=$eaN hit=$eaHit% sumR=$eaSumR | CLI n=$refN hit=$refHit% exp=$refExp"
  } else {
    # Sparse corpus: same-data parity impossible (tester cache is dense).
    # Enforce the RATE guard as the engine-regression tripwire: EA signals
    # per TESTER bar (parsed from the tester log's 'bars generated' line)
    # vs CLI signals per CORPUS candle.
    $eaBars = 0
    if (Test-Path $logFile) {
      $barLine = (Get-Content $logFile -Encoding Unicode -ErrorAction SilentlyContinue |
                  Where-Object { $_ -match 'M5: \d+ ticks, \d+ bars generated' } | Select-Object -Last 1)
      $bm = [regex]::Match([string]$barLine, 'M5: \d+ ticks, (\d+) bars generated')
      if ($bm.Success) { $eaBars = [int]$bm.Groups[1].Value }
    }
    if ($eaBars -le 0) { $eaBars = $corpusBuckets }   # fall back to the corpus scale
    $cliRate = if ($corpusBuckets -gt 0) { $refN / $corpusBuckets } else { 0.0 }
    $eaRate  = if ($eaBars -gt 0) { $eaN / $eaBars } else { 0.0 }
    if ($cliRate -gt 0.0 -and $eaRate -gt 0.0) {
      $ratio = $eaRate / $cliRate
      if ($ratio -gt 3.0 -or $ratio -lt 0.25) {
        $problems += "RATE GUARD: EA signal rate $($eaRate.ToString('0.0000'))/bar vs CLI rate $($cliRate.ToString('0.0000'))/candle ratio $($ratio.ToString('0.00')) outside [0.25, 3.0] - entry-gate regression"
      }
      $summaries += "rate-guard ratio $($ratio.ToString('0.00')) (EA $eaN/$eaBars bars vs CLI $refN/$corpusBuckets candles)"
    }
    $summaries += "data mismatch (corpus density ${density} - sparse tail; same-window trade parity NOT claimed)"
  }

  # --- R_75 sign-lock (absolute, on the CLI reference itself) --------------
  # The P10 matrix locks the R_75 band NEGATIVE on the calibrated real-tick
  # basis (aligned CLI reference, 2026-08-17: trades=102 exp=-0.393R).  The
  # STRICT branch above only checks EA-vs-CLI sign AGREEMENT — a flip that
  # moves BOTH sides positive together (a re-baseline, a cost-model edit, or
  # a systematic edge change) still satisfies parity and would pass silently.
  # This block asserts the REFERENCE'S OWN sign against the documented
  # matrix, exactly like the R_100 four-leg block: a non-negative expectancy
  # on a leg that actually traded fails the loop regardless of parity.
  if ($refN -gt 0 -and $refExp -ge 0.0) {
    $problems += "R_75 SIGN FLIP: CLI reference expectancy $refExp (n=$refN) is non-negative (documented matrix: -0.393R on the aligned real-tick basis) - matrix reference stale or the band's edge/cost model changed; re-baseline deliberately, do not carry a stale matrix"
  } else {
    $summaries += "R_75 sign-lock: CLI exp=$refExp (n=$refN) stays NEGATIVE (documented -0.393R)"
  }

  # --- R_100 four-leg sign-lock (P10 matrix reference) ---------------------
  # The documented P10 matrix (2026-08-16, full-density corpus, realistic
  # costs) locks ALL FOUR R_100 legs at 300s as NEGATIVE: band -0.591R /
  # fade -0.198R / momentum -0.019R / sniper -0.029R.  A leg flipping
  # non-negative means the matrix reference is stale or the leg's edge / cost
  # model changed materially — fail visibly.  -SkipPhase10R100Gate opts out
  # (the four-leg run replays the sniper via run_ticks, which is the slow
  # leg of the head-to-head).
  if ($SkipPhase10R100Gate) {
    $summaries += "R_100 four-leg sign-lock SKIPPED (-SkipPhase10R100Gate)"
  } else {
    $r100 = Invoke-R100FourLegReference
    if ($r100.skipped) {
      $summaries += "R_100 four-leg sign-lock NOT RUN ($($r100.detail))"
    } elseif (-not $r100.ok) {
      $problems += "R_100 four-leg sign-lock FAILED to run: $($r100.detail)"
    } else {
      # documented expectancy for each leg (negative per the P10 matrix)
      $docSigns = @{ "vol-band" = "-0.591"; "vol-reversion" = "-0.198"; "vol-momentum" = "-0.019"; "sniper" = "-0.029" }
      foreach ($leg in ($docSigns.Keys | Sort-Object)) {
        if (-not $r100.legs.ContainsKey($leg)) {
          $problems += "R_100 four-leg: leg '$leg' missing from head-to-head output - matrix contract broken"
          continue
        }
        $l = $r100.legs[$leg]
        if (-not $l.seen) {
          $problems += "R_100 four-leg: leg '$leg' has no expectancy_r line - output parse regression"
          continue
        }
        $summaries += "R_100 $leg n=$($l.trades) hit=$($l.hit)% exp=$($l.exp)R"
        if ($l.trades -gt 0 -and $l.exp -ge 0.0) {
          $problems += "R_100 SIGN FLIP: $leg expectancy $($l.exp)R is non-negative (documented matrix: $($docSigns[$leg])R) - matrix reference stale or leg edge/cost changed"
        }
      }
    }
  }

  # Detail shows the problems AND the summaries, so a P10-A failure still
  # surfaces the R_100 four-leg numbers the sign-lock measured.
  $detail = if ($problems.Count -eq 0) { "PASS - " + ($summaries -join ' | ') } else { "FAIL - " + ($problems -join '; ') + " | " + ($summaries -join ' | ') }
  $ok = ($problems.Count -eq 0)
  Write-Host "    phase-10 gate: $(if ($ok) { 'PASS' } else { 'FAIL' }) - $detail" -ForegroundColor $(if ($ok) { "Green" } else { "Red" })
  return @{ ok = $ok; skipped = $false; detail = $detail }
}

# --- Phase-6 risk-wiring gate: the EA's hard limits must actually fire -----
# P10-B exposed a defect where the integrated EA fired 523 trades with 0 risk
# vetoes: its §12 risk breakers (consecutive-loss / daily-loss / equity-DD)
# could not fire because outcomes were never registered.  The fix made
# vetoes real (238 trades / 318 vetoes on the 17-day window at 60s with
# Python's default risk).  THIS gate re-runs that exact configuration and
# FAILS if risk_vetoes is 0 again — a P10-B-class risk-wiring regression
# fails the loop visibly instead of slipping past as "trades fire".
#
# Runs the integrated EA (Phase10IntegrationTests wrapper) at InpBarSec=60
# (M1) with the Python default risk (consec 4, daily 2% = 0.02, equity-DD
# disabled) — the same -Inputs as the documented P10-B run.  Trade count is
# required to be meaningful (>0) so a run that traded nothing cannot pass the
# vetoes>0 check vacuously.
function Invoke-Phase6RiskGate {
  Write-Step "Phase-6 risk-wiring gate: EA at 60s with Python default risk (vetoes must be non-zero)..."
  # Compile + stage the EA wrapper (mirrors the seed-sweep pattern: inputs
  # arrive via the .set, not the build).
  $mq5src  = Join-Path $buildDir "Tests\Phase10IntegrationTests.mq5"
  $compLog = Join-Path $buildDir "compile_Phase10IntegrationTests_riskgate"
  $c = Invoke-Compile $mq5src $compLog
  if (-not $c.ok) { return @{ ok = $false; skipped = $false; detail = "Phase-6 risk gate compile failed: $($c.detail)" } }
  $ex5 = Join-Path $buildDir "Tests\Phase10IntegrationTests.ex5"
  if (-not (Test-Path $ex5)) { return @{ ok = $false; skipped = $false; detail = "Phase-6 risk gate: no Phase10IntegrationTests.ex5 produced" } }
  Copy-Item $ex5 (Join-Path $termTree "Tests\Phase10IntegrationTests.ex5") -Force

  # Python-default risk config (P10-B inputs): consec 4, daily 2% (=0.02
  # fraction — the RiskLimits setters take FRACTIONS, not percents), equity
  # drawdown DISABLED (0.0 = off per the RiskEngine >0 guard semantics).
  $testerProfiles = Join-Path $TerminalDataFolder "MQL5\Profiles\Tester"
  foreach ($setName in @("Phase10IntegrationTests.set", "Phase10Integration.set", "MitemshubAIBacktest.set", "MitemshubAI.set")) {
    $setPath = Join-Path $testerProfiles $setName
    if (Test-Path $setPath) { Remove-Item $setPath -Force -ErrorAction SilentlyContinue }
  }
  # Format mirrors the suite loop's -Inputs writer exactly: name=value||start||step||stop||optimize
  $setLines = @(
    "InpBarSec=60||60||0.0||10000.0||N",
    "InpMaxConsecLosses=4||4||0.0||10000.0||N",
    "InpMaxDailyLossPct=0.02||0.02||0.0||10000.0||N",
    "InpMaxEquityDDPct=0.0||0.0||0.0||10000.0||N"
  )
  $setPath = Join-Path $testerProfiles "Phase10IntegrationTests.set"
  [System.IO.File]::WriteAllText($setPath, ($setLines -join "`r`n"), [System.Text.Encoding]::Unicode)
  $port = Get-FreePort 3001
  $from = (Get-Date).AddDays(-$RangeDays).ToString("yyyy.MM.dd")
  $to   = (Get-Date).ToString("yyyy.MM.dd")
  $ini = Join-Path $TerminalDataFolder "verify_Phase10RiskGate.ini"
  $iniContent = @(
    "[Tester]",
    "Expert=MITEMSHUB_AI\Tests\Phase10IntegrationTests",
    "ExpertParameters=Phase10IntegrationTests.set",
    "Symbol=$Symbol",
    "Period=M1",
    "Model=1",
    "ExecutionMode=0",
    "Optimization=0",
    "OptimizationCriterion=0",
    "FromDate=$from",
    "ToDate=$to",
    "ForwardMode=0",
    "Report=verify_Phase10RiskGate",
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
  Write-Host "    EA risk gate running in Strategy Tester ($Symbol M1, $from -> $to, agent port $port)..."
  $r = Invoke-TesterSuite "Phase10IntegrationTests" $ini
  Remove-Item $ini -Force -ErrorAction SilentlyContinue
  foreach ($setName in @("Phase10IntegrationTests.set", "Phase10Integration.set", "MitemshubAIBacktest.set", "MitemshubAI.set")) {
    $setPath = Join-Path $testerProfiles $setName
    if (Test-Path $setPath) { Remove-Item $setPath -Force -ErrorAction SilentlyContinue }
  }
  if ($r.status -ne "PASS") {
    return @{ ok = $false; skipped = $false; detail = "EA risk gate run failed: $($r.detail)" }
  }

  # Parse the 60s run's machine line (bar_sec-scoped — the log also holds
  # today's P10-A 300s run and any earlier 60s runs).
  $logFile = Join-Path $testerLogsDir ($todayStamp + ".log")
  $eaLine = Get-Phase10TradesLine $logFile 60
  $em = [regex]::Match([string]$eaLine,
        "trades=(\d+) exits=stop:(\d+),trail:(\d+),target:(\d+),time:(\d+) sumR=$NumTok hit=([\d.]+)% avg_rr=([\d.]+) floor=([\d.]+)% floor_verdict=(BEAT|NOT_BEAT) risk_vetoes=(\d+) exec_rejects=(\d+)")
  if (-not $em.Success) {
    return @{ ok = $false; skipped = $false; detail = "no [PHASE10] bar_sec=60 machine line in $logFile after the risk-gate run - the EA summary regressed" }
  }
  $eaN    = [int]$em.Groups[1].Value
  $eaVeto = [int]$em.Groups[11].Value
  $eaRej  = [int]$em.Groups[12].Value
  if ($eaN -le 0) {
    return @{ ok = $false; skipped = $false; detail = "EA risk gate: 0 trades at 60s with Python default risk - cannot assert vetoes on a run that traded nothing (P10-B reference: 238 trades / 318 vetoes on 17d)" }
  }
  if ($eaVeto -le 0) {
    return @{ ok = $false; skipped = $false; detail = "EA fired $eaN trades with $eaVeto risk vetoes at 60s + Python default risk - P10-B-class risk-wiring regression (outcomes not registered / breakers dead); reference: 238 trades / 318 vetoes" }
  }
  $detail = "trades=$eaN vetoes=$eaVeto rejects=$eaRej (P10-B ref: 238 / 318 / 0)"
  Write-Host "    Phase-6 risk gate: PASS - $detail" -ForegroundColor Green
  return @{ ok = $true; skipped = $false; detail = $detail }
}

# --- Phase-10 P10-E real-tick sign-lock gate ----------------------------------
# The P10-E OHLC stress row (2026-08-16) proved the tester's price model can
# FLIP the EA's PnL sign: the same window/config that loses -36.964R on real
# ticks (Model=1) shows +55.502R under 1-min OHLC (Model=2).  Only the
# real-tick basis is trustworthy for the band's wick-sensitive geometry, so
# this row makes the real-tick sign a HARD contract: if the EA's 300s
# real-tick sumR ever disagrees in sign with the CLI band reference on the
# repaired corpus (the P10 matrix locks R_75 NEGATIVE), the loop fails
# loudly.  A flip means the calibration/geometry/cost basis changed
# materially - re-baseline the matrix deliberately, don't carry a stale one.
#
# P10-E note (2026-08-18): the closed-candle grace the OHLC model implicitly
# applies is BAND-GEOMETRY-SPECIFIC.  The band's ~92R Model=2 swing exists
# because its wide stops are mostly wick-only touches (the close stays
# inside); the SNIPER's tight 1R stops convert ~nothing under close-based
# resolution (_probe_sniper_ohlc.py: 129 real-tick stop-outs, 122
# close-throughs vs 7 wick-only, closed-candle grace saves 0-1) - so the
# ~92R wick-save ceiling must never be misread as sniper-harvestable.  A
# positive band sumR on real ticks is a basis flip; a small sniper delta is
# NOT (the sniper is model-robust, sign unchanged).
# Contract-location rule identical to the Phase-6 risk-wiring row: skips when
# Phase10IntegrationTests is not in this run's suites (the [PHASE10] machine
# lines live there).  No extra tester run needed - the suite loop's Model=1
# 300s run is the real-tick basis the row asserts on.
function Invoke-Phase10ESignGate {
  Write-Step "Phase-10 P10-E sign gate: EA real-tick sumR sign vs CLI R_75 band reference (a flip fails loudly)..."
  $py = Get-Command python -ErrorAction SilentlyContinue
  if (-not $py) {
    return @{ ok = $false; skipped = $true; detail = "python not on PATH - P10-E sign gate NOT run (install Python to arm it)" }
  }
  # Windowed reference corpus (Jul 30 00:00 -> Aug 16 00:00, the exact tester
  # window): rebuilt 2026-08-18 as union(pre-repair, live) + terminal-M1 repair,
  # so the CLI reference and the EA see identical bars.  The live collector file
  # (data\backfill\R_75_ticks.csv) keeps growing for the engine; the windowed
  # file is the frozen parity basis the P10 matrix is defined on.
  $corpus = Join-Path $repoRoot "data\backfill\R_75_ticks.windowed.csv"
  if (-not (Test-Path $corpus)) {
    return @{ ok = $false; skipped = $false; detail = "R_75 windowed corpus not found at $corpus - P10-E sign gate cannot run (rebuild via the README corpus recipe)" }
  }

  # EA real-tick machine line (bar_sec=300 - the suite loop's Model=1 run;
  # the log also holds the Phase-6 gate's 60s run, which must NOT be picked
  # up here; Get-Phase10TradesLine scopes by bar_sec).
  $logFile = Join-Path $testerLogsDir ($todayStamp + ".log")
  $eaLine = Get-Phase10TradesLine $logFile 300
  # sumR's sign is optional (the EA prints '-' only for negatives; a
  # positive sumR — e.g. the OHLC Model=2 flip — prints without '+').
  $em = [regex]::Match([string]$eaLine,
        "trades=(\d+) exits=stop:(\d+),trail:(\d+),target:(\d+),time:(\d+) sumR=$NumTok hit=([\d.]+)% avg_rr=([\d.]+) floor=([\d.]+)% floor_verdict=(BEAT|NOT_BEAT) risk_vetoes=(\d+) exec_rejects=(\d+)")
  if (-not $em.Success) {
    return @{ ok = $false; skipped = $false; detail = "no [PHASE10] bar_sec=300 machine line in $logFile - Phase10IntegrationTests did not run (or its summary regressed)" }
  }
  $eaN    = [int]$em.Groups[1].Value
  $eaSumR = [double]$em.Groups[6].Value

  if ($eaN -le 0) {
    return @{ ok = $false; skipped = $false; detail = "P10-E: EA real-tick run traded 0 at 300s - cannot confirm a sign on an empty run (would pass vacuously)" }
  }
  if ($eaSumR -eq 0.0) {
    return @{ ok = $false; skipped = $false; detail = "P10-E: EA real-tick sumR is exactly 0.0 - the sign is undefined; treat as a flip until deliberately re-baselined" }
  }

  # CLI band reference on the repaired corpus (the same command P10-A runs).
  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = "python"
  $psi.Arguments = '-m synthetic_trader.cli backtest-vol --csv "' + $corpus + '" --symbol R_75 --timeframe 300 --mode band --max-consecutive-losses 9999 --max-daily-loss-frac 1.0 --entry-slippage-ticks 0.05 --exit-slippage-ticks 0.05 --execution-penalty 0.10'
  $psi.RedirectStandardOutput = $true
  $psi.RedirectStandardError = $true
  $psi.UseShellExecute = $false
  $proc = [System.Diagnostics.Process]::Start($psi)
  $stdout = $proc.StandardOutput.ReadToEnd()
  $stderr = $proc.StandardError.ReadToEnd()
  if (-not $proc.WaitForExit(900000)) {
    $proc.Kill()
    return @{ ok = $false; skipped = $false; detail = "P10-E: CLI reference TIMED OUT (900s) - backtest-vol hung; treat as regression" }
  }
  if ($stderr) { Write-Host "    (stderr): $($stderr.Trim())" -ForegroundColor Yellow }
  $expM = [regex]::Match($stdout, "expectancy_r=$NumTok")
  if (-not $expM.Success) {
    return @{ ok = $false; skipped = $false; detail = "P10-E: CLI reference output unparseable (no expectancy_r=) - treat as regression" }
  }
  $refExp = [double]$expM.Groups[1].Value
  # (The P10-E CLI reference above runs with the aligned risk args + explicit
  # realistic-cost args — same pinned basis as P10-A; see that call site.)
  if ($refExp -eq 0.0) {
    return @{ ok = $false; skipped = $false; detail = "P10-E: CLI reference expectancy is exactly 0.0 - sign undefined; re-baseline the matrix before arming" }
  }

  $eaNeg  = $eaSumR -lt 0.0
  $refNeg = $refExp -lt 0.0
  if ($eaNeg -ne $refNeg) {
    return @{ ok = $false; skipped = $false; detail = "P10-E SIGN FLIP: EA 300s sumR $eaSumR (n=$eaN) vs CLI reference exp $refExp disagree in sign - the P10 matrix locks R_75 NEGATIVE on the calibrated real-tick basis; a positive EA sumR means either the suite loop ran on the OHLC model (the P10-E flip — Model=2 full-loop sweep 2026-08-17: +60.496 vs real-corpus -0.393) or the real-tick edge regressed; re-baseline deliberately, do not carry a stale matrix" }
  }
  $detail = "real-tick sumR=$eaSumR (n=$eaN) agrees in sign with CLI exp=$refExp (both NEGATIVE)"
  Write-Host "    P10-E sign gate: PASS - $detail" -ForegroundColor Green
  return @{ ok = $true; skipped = $false; detail = $detail }
}

# --- Phase-10 sniper-OHLC model-robustness gate -----------------------------
# The P10-E flip (the band's -36.964R -> +55.502R under Model=2) proved the
# tester's price model can FLIP the band's PnL sign.  There is NO sniper EA in
# the tester, so the equivalent is _probe_sniper_ohlc.py: a replay of the REAL
# captured sniper entry set under close-based exit resolution at both M5 and
# the tester's 1-min OHLC granularity.  The 2026-08-18 finding: the sniper
# does NOT flip — max OHLC delta 1.4-2.3R (vs the band's +92.5R Model=2
# swing), sign unchanged, only 0-1 of 129 stop-outs saved.  This gate locks
# the model-robustness finding in: it parses the probe's [SNIPER-OHLC] machine
# line and FAILS if delta_max ever exceeds ~5R — an order-of-magnitude
# tripwire that still leaves headroom over the measured deltas, so a future
# swing toward band-like wick-grace sensitivity fails the loop loudly.
# Mirrors the P10-E sign gate: skips only when python is unavailable; a
# missing probe / unparseable machine line / timeout is a FAIL (the contract
# is armed by default, -SkipSniperOhlcGate opts out).
function Invoke-SniperOhlcGate {
  $py = Get-Command python -ErrorAction SilentlyContinue
  if (-not $py) {
    return @{ ok = $false; skipped = $true; detail = "python not on PATH - sniper-OHLC gate NOT run (install Python to arm it)" }
  }
  Write-Step "Running sniper-OHLC model-robustness gate (_probe_sniper_ohlc.py, ~1-2 min)..."
  $script = Join-Path $repoRoot "_probe_sniper_ohlc.py"
  if (-not (Test-Path $script)) {
    return @{ ok = $false; skipped = $false; detail = "_probe_sniper_ohlc.py missing at $script - sniper-OHLC gate cannot run" }
  }
  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = "python"
  $psi.Arguments = '"' + $script + '"'
  $psi.RedirectStandardOutput = $true
  $psi.RedirectStandardError = $true
  $psi.UseShellExecute = $false
  $proc = [System.Diagnostics.Process]::Start($psi)
  $stdout = $proc.StandardOutput.ReadToEnd()
  $stderr = $proc.StandardError.ReadToEnd()
  if (-not $proc.WaitForExit(900000)) {
    $proc.Kill()
    return @{ ok = $false; skipped = $false; detail = "sniper-OHLC probe TIMED OUT (900s) - harness hung; treat as regression" }
  }
  if ($stderr) { Write-Host "    (probe stderr): $($stderr.Trim())" -ForegroundColor Yellow }
  $m = [regex]::Match($stdout, "delta_max=$NumTok threshold=$NumTok verdict=(OK|FLIP) wick_sumR=$NumTok close5_delta=$NumTok close1_delta=$NumTok wick1_delta=$NumTok band_ohlc_delta=$NumTok")
  if (-not $m.Success) {
    return @{ ok = $false; skipped = $false; detail = "no [SNIPER-OHLC] machine line in probe output - the harness output regressed" }
  }
  $deltaMax   = [double]$m.Groups[1].Value
  $threshold  = [double]$m.Groups[2].Value
  $verdict    = $m.Groups[3].Value
  if ($verdict -eq "FLIP" -or $deltaMax -gt $threshold) {
    return @{ ok = $false; skipped = $false; detail = "SNIPER-OHLC delta_max $deltaMax R exceeds the $threshold R model-robustness ceiling (machine verdict $verdict) - the sniper's OHLC-model swing is no longer ~0 (measured 1.4-2.3R vs the band's +92.5R flip); re-baseline deliberately, do not carry a stale finding" }
  }
  $detail = "delta_max=$deltaMax R <= $threshold R ceiling (sniper stays model-robust under OHLC: measured lanes 1.4-2.3R vs band +92.5R, sign unchanged)"
  Write-Host "    sniper-OHLC gate: PASS - $detail" -ForegroundColor Green
  return @{ ok = $true; skipped = $false; detail = $detail }
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

# From here on the tester owns the terminal: signal the live tick collector to
# stand down BEFORE the first suite closes it (and clear after restore below).
Set-VerifyPause

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
    "Model=$TestModel",
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

# --- paper->live execution parity contract row -----------------------------
if ($SkipExecutionParity) {
  Write-Step "Skipping execution parity contract (-SkipExecutionParity)"
} else {
  $ep = Invoke-ExecutionParityCheck
  $results += [pscustomobject]@{
    Suite = "ExecutionParity"; Compile = "-"
    Tester = $(if ($ep.ok) { "PASS" } elseif ($ep.skipped) { "SKIP" } else { "FAIL" })
    Detail = $ep.detail
  }
}

# --- Phase-6/7 real-corpus gate contracts row -------------------------------
if ($SkipRealCorpusGate) {
  Write-Step "Skipping real-corpus gate contracts (-SkipRealCorpusGate)"
} else {
  $rc = Invoke-RealCorpusGate
  $results += [pscustomobject]@{
    Suite = "RealCorpus"; Compile = "-"
    Tester = $(if ($rc.ok) { "PASS" } elseif ($rc.skipped) { "SKIP" } else { "FAIL" })
    Detail = $rc.detail
  }
}

# --- Phase-8 analytics gate contract row ------------------------------------
if ($SkipPhase8Gate) {
  Write-Step "Skipping Phase-8 analytics gate contract (-SkipPhase8Gate)"
} else {
  $p8 = Invoke-Phase8Gate
  $results += [pscustomobject]@{
    Suite = "Phase8Gate"; Compile = "-"
    Tester = $(if ($p8.ok) { "PASS" } elseif ($p8.skipped) { "SKIP" } else { "FAIL" })
    Detail = $p8.detail
  }
}

# --- Phase-10 P10-A integration gate contract row ---------------------------
# Only meaningful when the integrated EA ran in this invocation (its machine
# lines are parsed from today's tester log).  Without it the gate would
# compare stale lines, so it SKIPs like SeedSweep does for BandBackTests.
if ($SkipPhase10Gate) {
  Write-Step "Skipping Phase-10 P10-A gate contract (-SkipPhase10Gate)"
} else {
  $eaInTests = @($tests | Where-Object { $_.BaseName -eq "Phase10IntegrationTests" }).Count -gt 0
  if (-not $eaInTests) {
    Write-Step "Skipping Phase-10 P10-A gate (Phase10IntegrationTests not among the suites in this run - its machine lines live in that suite)"
    $results += [pscustomobject]@{ Suite = "Phase10Gate"; Compile = "-"; Tester = "SKIP"; Detail = "Phase10IntegrationTests is not in this run's suites - the [PHASE10] machine-line contract lives there" }
  } else {
    $p10 = Invoke-Phase10Gate (Join-Path $repoRoot "data\backfill\R_75_ticks.windowed.csv")
    $results += [pscustomobject]@{
      Suite = "Phase10Gate"; Compile = "-"
      Tester = $(if ($p10.ok) { "PASS" } elseif ($p10.skipped) { "SKIP" } else { "FAIL" })
      Detail = $p10.detail
    }
  }
}

# --- Phase-6 risk-wiring gate contract row ------------------------------------
# Runs the integrated EA at 60s with Python default risk and FAILS if
# risk_vetoes is 0 (the P10-B regression signature: 523 trades / 0 vetoes).
# Skips when Phase10IntegrationTests is not in this run's suites (the EA
# wrapper that emits the machine lines) — same contract-location rule as the
# Phase-10 gate.
if ($SkipPhase6Gate) {
  Write-Step "Skipping Phase-6 risk-wiring gate contract (-SkipPhase6Gate)"
} else {
  $eaInTests6 = @($tests | Where-Object { $_.BaseName -eq "Phase10IntegrationTests" }).Count -gt 0
  if (-not $eaInTests6) {
    Write-Step "Skipping Phase-6 risk-wiring gate (Phase10IntegrationTests not among the suites in this run - its machine lines live in that suite)"
    $results += [pscustomobject]@{ Suite = "Phase6RiskGate"; Compile = "-"; Tester = "SKIP"; Detail = "Phase10IntegrationTests is not in this run's suites - the risk-wiring contract lives there" }
  } else {
    $p6 = Invoke-Phase6RiskGate
    $results += [pscustomobject]@{
      Suite = "Phase6RiskGate"; Compile = "-"
      Tester = $(if ($p6.ok) { "PASS" } elseif ($p6.skipped) { "SKIP" } else { "FAIL" })
      Detail = $p6.detail
    }
  }
}

# --- Phase-10 P10-E real-tick sign-lock contract row -------------------------
# Asserts the EA's 300s REAL-TICK (Model=1) sumR sign agrees with the CLI
# band reference on the repaired corpus — the P10-E lesson (the OHLC model
# flipped the same window to +55.502) made the real-tick basis a hard
# contract.  Same contract-location rule as the Phase-6 risk-wiring row:
# skips when Phase10IntegrationTests is not in this run's suites.
if ($SkipPhase10ESignGate) {
  Write-Step "Skipping Phase-10 P10-E real-tick sign gate (-SkipPhase10ESignGate)"
} else {
  $eaInTests10e = @($tests | Where-Object { $_.BaseName -eq "Phase10IntegrationTests" }).Count -gt 0
  if (-not $eaInTests10e) {
    Write-Step "Skipping Phase-10 P10-E sign gate (Phase10IntegrationTests not among the suites in this run - its machine lines live in that suite)"
    $results += [pscustomobject]@{ Suite = "Phase10ESignGate"; Compile = "-"; Tester = "SKIP"; Detail = "Phase10IntegrationTests is not in this run's suites - the [PHASE10] machine-line contract lives there" }
  } else {
    $p10e = Invoke-Phase10ESignGate
    $results += [pscustomobject]@{
      Suite = "Phase10ESignGate"; Compile = "-"
      Tester = $(if ($p10e.ok) { "PASS" } elseif ($p10e.skipped) { "SKIP" } else { "FAIL" })
      Detail = $p10e.detail
    }
  }
}

# --- Phase-10 sniper-OHLC model-robustness gate row --------------------------
# Asserts the sniper's OHLC-model sumR delta stays under the ~5R ceiling (the
# model-robustness finding, mirror of the P10-E sign gate: the BAND flips under
# Model=2, the SNIPER does not).  No MT5 dependency - the probe replays the
# cached sniper capture over the real corpus bars, so it runs anywhere python
# does.
if ($SkipSniperOhlcGate) {
  Write-Step "Skipping sniper-OHLC model-robustness gate (-SkipSniperOhlcGate)"
} else {
  $so = Invoke-SniperOhlcGate
  $results += [pscustomobject]@{
    Suite = "SniperOhlcGate"; Compile = "-"
    Tester = $(if ($so.ok) { "PASS" } elseif ($so.skipped) { "SKIP" } else { "FAIL" })
    Detail = $so.detail
  }
}

# --- calibration-sanity gate contract row -------------------------------------
if ($SkipCalibrationGate) {
  Write-Step "Skipping calibration-sanity gate contract (-SkipCalibrationGate)"
} else {
  $cg = Invoke-CalibrationGate
  $results += [pscustomobject]@{
    Suite = "CalibrationGate"; Compile = "-"
    Tester = $(if ($cg.ok) { "PASS" } elseif ($cg.skipped) { "SKIP" } else { "FAIL" })
    Detail = $cg.detail
  }
}

# --- seed-sweep depth gate (multi-seed cell means) --------------------------
# Opt-in (-SeedSweep): re-runs BandBackTests across -Seeds and fails when the
# depth-split cell MEANS are unstable (see Test-SeedStability).  Only relevant
# to BandBackTests — the depth-split contract lives in that suite, so a sweep
# request without it is a SKIP, not a failure.
if ($SeedSweep) {
  $bandInTests = @($tests | Where-Object { $_.BaseName -eq "BandBackTests" }).Count -gt 0
  if (-not $bandInTests) {
    Write-Step "Skipping seed-sweep depth gate (BandBackTests not among the suites in this run: $((($tests | ForEach-Object { $_.BaseName }) -join ', ')))"
    $results += [pscustomobject]@{ Suite = "SeedSweep"; Compile = "-"; Tester = "SKIP"; Detail = "-SeedSweep given but BandBackTests is not in this run's suites — the depth-split contract lives there" }
  } else {
    $sw = Invoke-SeedSweepGate
    $results += [pscustomobject]@{
      Suite = "SeedSweep"; Compile = "-"
      Tester = $(if ($sw.ok) { "PASS" } elseif ($sw.skipped) { "SKIP" } else { "FAIL" })
      Detail = $sw.detail
    }
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

# Tester phase is over and the terminal is (re)launched: release the collector
# so it resumes polling the live feed.  Runs on the no-restore path too.
Clear-VerifyPause

Write-Step "Cleaning temp build dir"
Remove-Item $buildDir -Recurse -Force -ErrorAction SilentlyContinue

# --- [VERIFY] summary-line contract (machine-readable, email loop) ----------
# Get-FirstProblem maps a gate's Detail string to a compact problem slug;
# Get-VerifySummaryLine builds the byte-stable line the email loop parses.
# Both are extracted and pinned by mql5/verify_verifyline_fixtures.ps1 (see
# the pre-flight step 7) — change them only together with that fixture.
function Get-FirstProblem([string]$detail) {
  if (-not $detail) { return 'no-detail' }
  # Take the FIRST problem clause (details are "FAIL - p1; p2 | summary...").
  $t = $detail -replace '^\s*FAIL\s*[-:]\s*', ''
  $t = ($t -split ';\s*|\|\s*|\r?\n')[0]
  $rules = @(
    @{ re = '(?i)^(?:P10-E\s+)?SIGN\s+FLIP'; slug = 'sign-flip' },
    @{ re = '(?i)^R_75\s+SIGN\s+FLIP';        slug = 'sign-flip' },
    @{ re = '(?i)^SNIPER-?OHLC';                slug = 'sniper-ohlc-delta' },
    @{ re = '(?i)^STRICT: EA trades';          slug = 'strict-trades' },
    @{ re = '(?i)^STRICT: EA hit';             slug = 'strict-hit' },
    @{ re = '(?i)^STRICT: EA sumR .*sign disagrees'; slug = 'strict-sign' },
    @{ re = '(?i)^RATE\s+GUARD';               slug = 'rate-guard' },
    @{ re = '(?i)no .*machine line';           slug = 'no-machine-line' },
    @{ re = '(?i)timed out';                   slug = 'timeout' },
    @{ re = '(?i)unparseable';                 slug = 'unparseable' },
    @{ re = '(?i)not found at|corpus not found'; slug = 'corpus-missing' },
    @{ re = '(?i)no \.ex5 produced|did not produce|compile error'; slug = 'no-artifact' },
    @{ re = '(?i)missing';                     slug = 'missing' },
    @{ re = '(?i)failed to run';               slug = 'run-failed' }
  )
  foreach ($r in $rules) { if ($t -match $r.re) { return $r.slug } }
  # Generic fallback: first two words, slugified, lowercased.
  $words = @($t -replace '[^A-Za-z0-9 ]', ' ' -split '\s+' | Where-Object { $_ })
  if ($words.Count -ge 2) { return (($words[0] + '-' + $words[1]).ToLowerInvariant()) }
  if ($words.Count -eq 1) { return $words[0].ToLowerInvariant() }
  return 'no-detail'
}

function Get-VerifySummaryLine([object[]]$results) {
  $bad = @($results | Where-Object { ($_.Compile -ne "OK" -and $_.Compile -ne "-") -or ($_.Tester -ne "PASS" -and $_.Tester -ne "SKIP") })
  $nGreen = @($results | Where-Object { ($_.Compile -eq "OK" -or $_.Compile -eq "-") -and $_.Tester -eq "PASS" }).Count
  $nSkip  = @($results | Where-Object { $_.Tester -eq "SKIP" }).Count
  $nRed   = $bad.Count
  $nRows  = $results.Count
  $line = "[VERIFY] summary ok=$(if ($bad.Count -eq 0) { 1 } else { 0 }) rows=$nRows green=$nGreen red=$nRed skip=$nSkip"
  if ($bad.Count -gt 0) {
    $line += " failed=" + (@($bad | ForEach-Object { "$($_.Suite):$(Get-FirstProblem $_.Detail)" }) -join ",")
  }
  return $line
}

Write-Host ""
Write-Host "==================== MITEMSHUB verify summary ===================="
$results | Format-Table -AutoSize
# Compile "-" = Python harness row (no MQL5 compile); Tester "SKIP" = python
# unavailable / corpus too thin — neither is a failure.
$bad = @($results | Where-Object { ($_.Compile -ne "OK" -and $_.Compile -ne "-") -or ($_.Tester -ne "PASS" -and $_.Tester -ne "SKIP") })
# --- machine-readable ALL-GATES-GREEN line (Task Scheduler email loop) ------
# run-mql5-verify-task.ps1 parses `[VERIFY] summary ...` to build the email
# subject; the human table above is not a stable parse target.  ok=1 green /
# ok=0 red; every red row rides on the same line as `Suite:first-problem`
# (e.g. failed=Phase10Gate:strict-hit,Phase10ESignGate:sign-flip) so the
# email names each gate's first failure without scraping the Detail column.
# Follows the [CALIB] summary / [PARITY] verdict machine-line convention.
# Printed on EVERY full run (green and red) so the loop can rely on its
# presence; pre-flight throws (which skip this line) are covered by the
# runner's PRE-FLIGHT fallback.  Byte-stability is fixture-guarded by
# verify_verifyline_fixtures.ps1 (pre-flight step 7) — edit the functions
# below and the fixture together, never one without the other.
$verifyLine = Get-VerifySummaryLine $results
Write-Host $verifyLine
if ($bad.Count -eq 0) {
  $what = "compile + Strategy Tester + sniper gate contract"
  if ($SeedSweep) { $what += " + seed-sweep depth gate" }
  if (-not $SkipExecutionParity) { $what += " + execution parity" }
  if (-not $SkipRealCorpusGate) { $what += " + real-corpus gates" }
  if (-not $SkipPhase8Gate) { $what += " + phase-8 analytics gate" }
  if (-not $SkipPhase10Gate) {
    $what += " + phase-10 P10-A gate"
    if (-not $SkipPhase10R100Gate) { $what += " + R_100 four-leg sign-lock" }
  }
  if (-not $SkipPhase6Gate) { $what += " + phase-6 risk-wiring gate" }
  if (-not $SkipPhase10ESignGate) { $what += " + phase-10 P10-E real-tick sign gate" }
  if (-not $SkipSniperOhlcGate) { $what += " + sniper-OHLC model-robustness gate" }
  if (-not $SkipCalibrationGate) { $what += " + calibration-sanity gate" }
  Write-Host "ALL SUITES PASSED ($what)." -ForegroundColor Green
  exit 0
}
Write-Host "$($bad.Count) suite(s) NOT green — see Detail column." -ForegroundColor Red
exit 1
