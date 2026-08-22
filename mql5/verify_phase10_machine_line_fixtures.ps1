# Fixture harness for the [PHASE10] machine-line parse contract.
#
# Regression target: on 2026-08-17 the Model=2 full-loop sweep flipped the
# band's sumR POSITIVE (+60.496).  The EA prints a leading sign only for
# NEGATIVE sums, but the gates' regexes required `sumR=([+-]...)`, so both
# machine-line gates bailed with "no [PHASE10] trades= machine line" instead
# of evaluating the flip.  The regexes were fixed to the shared $NumTok token
# (optional sign + exponent form) — this harness makes that fix a permanent
# contract by extracting the REAL $NumTok definition and the REAL gate pattern
# literals out of verify_all.ps1 and asserting a positive-sumR line parses
# end-to-end through the gates' actual parse path (Get-Phase10TradesLine +
# the gate regex), with a negative control proving the OLD ([+-]...) pattern
# would still bail.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File mql5/verify_phase10_machine_line_fixtures.ps1
$ErrorActionPreference = 'Stop'
$ps1 = Join-Path $PSScriptRoot 'verify_all.ps1'
$text = Get-Content $ps1 -Raw

# --- extract the REAL $NumTok definition (as the gates interpolate it) -------
$NumTok = [regex]::Match($text, '(?m)^\$NumTok = ''([^'']+)''').Groups[1].Value
if (-not $NumTok) { throw 'cannot extract $NumTok from verify_all.ps1' }

# --- extract EVERY EA machine-line pattern literal from verify_all.ps1 -------
# (one per gate: P10-A, Phase-6 risk gate, P10-E).  The literal is the
# double-quoted regex text in the file, e.g. "... sumR=$NumTok hit=...";
# each is evaluated with real interpolation below, exactly as the runtime does.
$patMatches = [regex]::Matches($text, '"trades=\(\\d\+\) exits=stop:.*?exec_rejects=\(\\d\+\)"', 'Singleline')
$patterns = @()
foreach ($pm in $patMatches) {
  $patterns += (& ([scriptblock]::Create($pm.Value)))
}

# --- extract the REAL Get-Phase10TradesLine function (balanced braces) -------
$start = $text.IndexOf('function Get-Phase10TradesLine')
if ($start -lt 0) { throw 'Get-Phase10TradesLine not found' }
# Comment-aware brace scan: an apostrophe inside a # comment (e.g. "the run's
# trades= line") must NOT flip string-mode tracking — 2026-08-18 regression
# where the scan derailed on the comment and never reached depth 0.
$depth = 0; $i = $start; $inStr = $false; $strCh = ''; $inComment = $false
for (; $i -lt $text.Length; $i++) {
  $ch = $text[$i]
  if ($inComment) {
    if ($ch -eq [char]10) { $inComment = $false }
    continue
  }
  if ($inStr) {
    if ($ch -eq $strCh) {
      if ($i + 1 -lt $text.Length -and $text[$i + 1] -eq $strCh) { $i++ } else { $inStr = $false }
    }
    continue
  }
  if ($ch -eq '#') { $inComment = $true; continue }
  if ($ch -eq "'" -or $ch -eq '"') { $inStr = $true; $strCh = $ch; continue }
  if ($ch -eq '{') { $depth++ }
  elseif ($ch -eq '}') { $depth--; if ($depth -eq 0) { break } }
}
Invoke-Expression ($text.Substring($start, $i - $start + 1))   # define Get-Phase10TradesLine

$script:failed = $false
function Assert-Case([string]$name, [bool]$cond, [string]$detail) {
  if ($cond) { Write-Host "PASS  $name  $detail" } else { Write-Host "FAIL  $name  $detail"; $script:failed = $true }
}

# --- synthetic tester-log lines (real formats) -------------------------------
# Run 1: 60s risk-gate run, NEGATIVE sumR (Phase-6 today path).
$line60 = '[PHASE10] trades=238 exits=stop:100,trail:50,target:80,time:8 sumR=-36.964 hit=12.00% avg_rr=1.20 floor=30.0% floor_verdict=NOT_BEAT risk_vetoes=318 exec_rejects=0'
# Run 2: 300s integration run, POSITIVE sumR — the Model=2 flip shape that
# broke the old ([+-]...) regex on 2026-08-17.
$line300 = '[PHASE10] trades=100 exits=stop:49,trail:20,target:26,time:5 sumR=60.496 hit=31.00% avg_rr=1.15 floor=30.0% floor_verdict=BEAT risk_vetoes=0 exec_rejects=0'
$bar60  = '[PHASE10] bar_sec=60 garch_mode=0 drift=OFF revert=0.00 trail=0.30 grace=OFF'
$bar300 = '[PHASE10] bar_sec=300 garch_mode=0 drift=OFF revert=0.00 trail=0.30 grace=OFF'
$decoy  = '[PHASE10] trades=98 exits=stop:40,trail:20,target:30,time:8 sumR=55.500 hit=30.00% avg_rr=1.14 floor=30.0% floor_verdict=BEAT risk_vetoes=0 exec_rejects=0'

$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ('phase10_ml_' + [guid]::NewGuid().ToString('N') + '.log')
function New-FakeLog([string]$content) {
  [System.IO.File]::WriteAllText($tmp, $content, [System.Text.Encoding]::Unicode)  # tester logs are UTF-16
}
try {
  # ---------------------------------------------------------------------------
  # 1. The gate regex (as extracted from verify_all.ps1) parses the positive
  #    sumR line with the right groups -> P10-A/P10-E/Phase-6 reach the
  #    evaluation instead of bailing with 'no [PHASE10] trades= machine line'.
  # ---------------------------------------------------------------------------
  Assert-Case 'patterns-extracted-3-gates' ($patterns.Count -eq 3) "count=$($patterns.Count)"
  $posOk = $true; $posDetail = ''
  foreach ($pat in $patterns) {
    $m = [regex]::Match($line300, $pat)
    if (-not ($m.Success -and $m.Groups[6].Value -eq '60.496' -and $m.Groups[1].Value -eq '100' -and $m.Groups[10].Value -eq 'BEAT' -and $m.Groups[11].Value -eq '0' -and $m.Groups[12].Value -eq '0' -and $m.Groups.Count -eq 13)) {
      $posOk = $false; $posDetail = 'groups: ' + $(if ($m.Success) { "sumR=$($m.Groups[6].Value) n=$($m.Groups[1].Value)" } else { 'no match' })
    }
  }
  Assert-Case 'positive-sumR parses in ALL gate regexes' $posOk $posDetail

  $m = [regex]::Match($line300, $patterns[0])
  $eaSumR = [double]$m.Groups[6].Value
  $eaN    = [int]$m.Groups[1].Value
  $eaHit  = [double]$m.Groups[7].Value
  $eaFloor = [double]$m.Groups[9].Value
  $eaVerdict = $m.Groups[10].Value
  # P10-A ALWAYS-consistency block must evaluate (not bail):
  $exitSum = [int]$m.Groups[2].Value + [int]$m.Groups[3].Value + [int]$m.Groups[4].Value + [int]$m.Groups[5].Value
  $beatsOk = ($eaVerdict -eq 'BEAT') -and ($eaHit -ge $eaFloor -and $eaN -ge 10)
  Assert-Case 'P10-A consistency evaluates on positive line' ($exitSum -eq $eaN -and $beatsOk -and $eaSumR -gt 0.0) "exits=$exitSum n=$eaN hit=$eaHit floor=$eaFloor"
  # P10-E sign logic evaluates (positive -> eaNeg=false -> SIGN FLIP detected,
  # not a bail):
  Assert-Case 'P10-E sign evaluates on positive line' (($eaSumR -lt 0.0) -eq $false) "eaSumR=$eaSumR"
  # Phase-6 groups (n / vetoes / rejects) parse for its 60s negative line:
  $m = [regex]::Match($line60, $patterns[1])
  Assert-Case 'Phase-6 negative line parses' ($m.Success -and $m.Groups[1].Value -eq '238' -and $m.Groups[6].Value -eq '-36.964' -and $m.Groups[11].Value -eq '318') "sumR=$($m.Groups[6].Value) vetoes=$($m.Groups[11].Value)"

  # 2. Get-Phase10TradesLine returns the right line per bar_sec (the exact
  #    path P10-A / Phase-6 / P10-E feed into the regexes above).
  New-FakeLog (($bar60, $line60, $bar300, $line300) -join "`r`n")
  $got300 = Get-Phase10TradesLine $tmp 300
  $got60  = Get-Phase10TradesLine $tmp 60
  Assert-Case 'Get-Phase10TradesLine 300 -> positive line' ($got300 -eq $line300) $got300
  Assert-Case 'Get-Phase10TradesLine 60 -> negative line' ($got60 -eq $line60) $got60

  # 3. Last-run-wins scoping (the reason the gates are bar_sec-scoped at all):
  #    a later 300s run must win, and the 60s pick must be unaffected.
  New-FakeLog (($bar60, $line60, $bar300, $line300, $bar300, $decoy) -join "`r`n")
  $got300b = Get-Phase10TradesLine $tmp 300
  $got60b  = Get-Phase10TradesLine $tmp 60
  Assert-Case 'scoping: last 300s run wins' ($got300b -eq $decoy) $got300b
  Assert-Case 'scoping: 60s pick unaffected' ($got60b -eq $line60) $got60b

  # 4. Zero and forced-plus sumR also parse (sign-optional + still accepts '+'):
  $zero = $line300 -replace 'sumR=60.496', 'sumR=0.000'
  $forced = $line300 -replace 'sumR=60.496', 'sumR=+60.496'
  $m = [regex]::Match($zero, $patterns[0])
  Assert-Case 'zero sumR parses' ($m.Success -and [double]$m.Groups[6].Value -eq 0.0) $m.Groups[6].Value
  $m = [regex]::Match($forced, $patterns[0])
  Assert-Case 'forced-plus sumR parses' ($m.Success -and [double]$m.Groups[6].Value -eq 60.496) $m.Groups[6].Value

  # 5. NEGATIVE CONTROL: the pre-fix ([+-]...) pattern must still bail on the
  #    positive line — proving this harness discriminates a regression back to
  #    a sign-required sumR.
  $old = 'trades=(\d+) exits=stop:(\d+),trail:(\d+),target:(\d+),time:(\d+) sumR=([+-][\d.]+) hit=([\d.]+)% avg_rr=([\d.]+) floor=([\d.]+)% floor_verdict=(BEAT|NOT_BEAT) risk_vetoes=(\d+) exec_rejects=(\d+)'
  $oldPos = [regex]::Match($line300, $old)
  $oldNeg = [regex]::Match($line60, $old)
  Assert-Case 'negative control: old ([+-]) pattern bails on positive line' (-not $oldPos.Success) 'must stay red'
  Assert-Case 'negative control: old ([+-]) pattern still parses negative line' $oldNeg.Success ''
} finally {
  Remove-Item $tmp -Force -ErrorAction SilentlyContinue
}

# -----------------------------------------------------------------------------
# CLI-reference + R_100 four-leg value parses (the P10-A / P10-E feeds).
# P10-A also parses the CLI `backtest-vol` reference output (trades=/win_rate=/
# expectancy_r=) and the R_100 four-leg head-to-head (strategy= blocks) that
# feeds the P10 matrix sign-lock — pin every one of those value parses here so
# a format regression on those lines is caught before it can silently bail the
# gates.  The CLI prints `expectancy_r={:.3f}` with NO forced sign, so a
# positive flip appears as '0.397' — the exact class that broke the EA line.
# -----------------------------------------------------------------------------
# Extract the REAL four-leg block patterns (Invoke-R100FourLegReference uses
# per-line Match($ln, ...) — the four Match($ln, ...) calls in that function,
# in order: strategy / trades / win_rate / expectancy_r).
$legStart = $text.IndexOf('function Invoke-R100FourLegReference')
if ($legStart -lt 0) { throw 'Invoke-R100FourLegReference not found' }
$legText = $text.Substring($legStart)
$legPats = @()
foreach ($lit in [regex]::Matches($legText, 'Match\(\$ln, (''[^'']+''|"[^"]+")\)')) {
  $legPats += (& ([scriptblock]::Create($lit.Groups[1].Value)))
}
# Extract the REAL CLI-reference patterns (Invoke-Phase10Gate + the P10-E gate
# both parse backtest-vol stdout with Match($stdout, ...)); dedupe (the two
# gates share the identical expectancy_r= pattern).  Scoped to end where the
# sniper-OHLC gate begins: that gate has its OWN Match($stdout, ...) call (the
# [SNIPER-OHLC] machine line, pinned separately below) and must not be counted
# among the backtest-vol CLI-reference patterns.
$cliStart = $text.IndexOf('function Invoke-Phase10Gate')
if ($cliStart -lt 0) { throw 'Invoke-Phase10Gate not found' }
$cliEnd = $text.IndexOf('function Invoke-SniperOhlcGate')
if ($cliEnd -lt 0) { $cliEnd = $text.Length }
$cliText = $text.Substring($cliStart, $cliEnd - $cliStart)
$cliPats = @()
foreach ($lit in [regex]::Matches($cliText, 'Match\(\$stdout, (''[^'']+''|"[^"]+")\)')) {
  $cliPats += (& ([scriptblock]::Create($lit.Groups[1].Value)))
}
$cliPats = @($cliPats | Select-Object -Unique)

Assert-Case 'cli-ref-patterns-extracted-3' ($cliPats.Count -eq 3) "count=$($cliPats.Count)"
Assert-Case 'four-leg-patterns-extracted-4' ($legPats.Count -eq 4) "count=$($legPats.Count)"

# --- CLI reference stdout (real backtest-vol shapes, other lines included) ---
$cliOut = @('symbol=R_75', 'timeframe_sec=300', 'trades=81', 'signals=96', 'rejected_signals=0',
            'win_rate=3.70%', 'profit_factor=0.50', 'expectancy_r=-0.591', 'net_pnl=-254.51') -join "`r`n"
$tm = [regex]::Match($cliOut, $cliPats[0])
$hm = [regex]::Match($cliOut, $cliPats[1])
$em = [regex]::Match($cliOut, $cliPats[2])
Assert-Case 'cli-ref trades= parses' ($tm.Success -and $tm.Groups[1].Value -eq '81') ''
Assert-Case 'cli-ref win_rate= parses' ($hm.Success -and [double]$hm.Groups[1].Value -eq 3.70) ''
Assert-Case 'cli-ref negative expectancy parses' ($em.Success -and [double]$em.Groups[1].Value -eq -0.591) ''
# Positive flip: '0.397' (no sign) must parse through the live pattern.
$cliPos = $cliOut -replace 'expectancy_r=-0.591', 'expectancy_r=0.397'
$em = [regex]::Match($cliPos, $cliPats[2])
Assert-Case 'cli-ref positive no-sign expectancy parses' ($em.Success -and [double]$em.Groups[1].Value -eq 0.397) ''
$cliZero = $cliOut -replace 'expectancy_r=-0.591', 'expectancy_r=0.000'
Assert-Case 'cli-ref zero expectancy parses' ([regex]::Match($cliZero, $cliPats[2]).Success) ''

# --- R_100 four-leg head-to-head stdout (real --compare shapes) --------------
$fourLeg = @(
  'strategy=vol-band',      'trades=81', 'win_rate=3.70%',   'expectancy_r=-0.591',
  'strategy=vol-reversion', 'trades=49', 'win_rate=18.37%',  'expectancy_r=-0.198',
  'strategy=vol-momentum',  'trades=53', 'win_rate=47.17%',  'expectancy_r=-0.019',
  'strategy=sniper',        'trades=41', 'win_rate=48.78%',  'expectancy_r=-0.029'
) -join "`r`n"
# Replicate the block parser from Invoke-R100FourLegReference exactly (per-line
# Match($ln, ...), $cur tracks the current strategy block).
$legs = @{}; $cur = ''
foreach ($ln4 in ($fourLeg -split "`r?`n")) {
  $sm = [regex]::Match($ln4, $legPats[0])
  if ($sm.Success) { $cur = $sm.Groups[1].Value; $legs[$cur] = @{ trades = 0; hit = 0.0; exp = 0.0; seen = $false }; continue }
  if ($cur -eq '') { continue }
  $tm = [regex]::Match($ln4, $legPats[1])
  if ($tm.Success) { $legs[$cur].trades = [int]$tm.Groups[1].Value; continue }
  $hm = [regex]::Match($ln4, $legPats[2])
  if ($hm.Success) { $legs[$cur].hit = [double]$hm.Groups[1].Value; continue }
  $em = [regex]::Match($ln4, $legPats[3])
  if ($em.Success) { $legs[$cur].exp = [double]$em.Groups[1].Value; $legs[$cur].seen = $true }
}
Assert-Case 'four-leg all 4 legs seen with expectancy' ($legs.Count -eq 4 -and @($legs.Values | Where-Object { -not $_.seen }).Count -eq 0) "legs=$($legs.Count)"
Assert-Case 'four-leg vol-band n/exp' ($legs['vol-band'].trades -eq 81 -and $legs['vol-band'].exp -eq -0.591) ''
Assert-Case 'four-leg vol-reversion exp' ($legs['vol-reversion'].exp -eq -0.198) ''
Assert-Case 'four-leg vol-momentum exp' ($legs['vol-momentum'].exp -eq -0.019) ''
Assert-Case 'four-leg sniper exp' ($legs['sniper'].exp -eq -0.029) ''
$flips = @($legs.Keys | Where-Object { $legs[$_].trades -gt 0 -and $legs[$_].exp -ge 0.0 })
Assert-Case 'four-leg sign-lock: no flips on negative legs' ($flips.Count -eq 0) "flips=$($flips -join ',')"
# NEGATIVE CONTROL: a flipped (positive) leg must be DETECTED by the same
# parse + sign-lock evaluation — the sign-lock's actual regression target.
$flipLeg = $fourLeg -replace 'expectancy_r=-0.591', 'expectancy_r=+0.310'
$legs2 = @{}; $cur = ''
foreach ($ln4 in ($flipLeg -split "`r?`n")) {
  $sm = [regex]::Match($ln4, $legPats[0])
  if ($sm.Success) { $cur = $sm.Groups[1].Value; $legs2[$cur] = @{ trades = 0; hit = 0.0; exp = 0.0; seen = $false }; continue }
  if ($cur -eq '') { continue }
  $tm = [regex]::Match($ln4, $legPats[1])
  if ($tm.Success) { $legs2[$cur].trades = [int]$tm.Groups[1].Value; continue }
  $hm = [regex]::Match($ln4, $legPats[2])
  if ($hm.Success) { $legs2[$cur].hit = [double]$hm.Groups[1].Value; continue }
  $em = [regex]::Match($ln4, $legPats[3])
  if ($em.Success) { $legs2[$cur].exp = [double]$em.Groups[1].Value; $legs2[$cur].seen = $true }
}
$flips2 = @($legs2.Keys | Where-Object { $legs2[$_].trades -gt 0 -and $legs2[$_].exp -ge 0.0 })
Assert-Case 'negative control: flipped leg detected by sign-lock' ($flips2 -contains 'vol-band') "flips=$($flips2 -join ',')"

# --- sniper-OHLC machine line (the model-robustness gate's parse) ------------
# Invoke-SniperOhlcGate parses the [SNIPER-OHLC] line _probe_sniper_ohlc.py
# emits.  Pin the pattern literal (extracted live from verify_all.ps1, with
# $NumTok interpolated exactly as the runtime does) against a real OK line and
# a flipped line — a format regression on that line must fail here, in
# seconds, instead of bailing the gate mid-loop.
$soLit = [regex]::Match($text, '"delta_max=\$NumTok threshold=\$NumTok verdict=\(OK\|FLIP\) wick_sumR=\$NumTok close5_delta=\$NumTok close1_delta=\$NumTok wick1_delta=\$NumTok band_ohlc_delta=\$NumTok"')
if (-not $soLit.Success) { throw 'sniper-OHLC machine-line pattern not found in verify_all.ps1 (Invoke-SniperOhlcGate regex was edited?)' }
$soPat = & ([scriptblock]::Create($soLit.Value))
$soOk = '[SNIPER-OHLC] delta_max=2.31 threshold=5.00 verdict=OK wick_sumR=+88.16 close5_delta=-2.31 close1_delta=-1.41 wick1_delta=-1.41 band_ohlc_delta=+92.47'
$m = [regex]::Match($soOk, $soPat)
Assert-Case 'sniper-ohlc OK line parses' ($m.Success -and [double]$m.Groups[1].Value -eq 2.31 -and [double]$m.Groups[2].Value -eq 5.00 -and $m.Groups[3].Value -eq 'OK') "delta=$($m.Groups[1].Value) verdict=$($m.Groups[3].Value)"
$soFlip = $soOk -replace 'delta_max=2.31', 'delta_max=9.87' -replace 'verdict=OK', 'verdict=FLIP'
$m = [regex]::Match($soFlip, $soPat)
Assert-Case 'sniper-ohlc FLIP line parses' ($m.Success -and [double]$m.Groups[1].Value -eq 9.87 -and $m.Groups[3].Value -eq 'FLIP') "delta=$($m.Groups[1].Value) verdict=$($m.Groups[3].Value)"
$soNeg = $soOk -replace 'delta_max=2.31', 'delta_max=-36.964' -replace 'close5_delta=-2.31', 'close5_delta=-36.964'
Assert-Case 'sniper-ohlc negative delta parses' ([regex]::Match($soNeg, $soPat).Success -and [double][regex]::Match($soNeg, $soPat).Groups[1].Value -eq -36.964) ''

if ($script:failed) { Write-Host "FIXTURES: FAILED" -ForegroundColor Red; exit 1 }
Write-Host "FIXTURES: ALL PASS" -ForegroundColor Green
