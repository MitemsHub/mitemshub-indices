# Fixture harness for the [VERIFY] summary-line contract.
#
# Locks the machine-readable ALL-GATES-GREEN line (parsed by the Task
# Scheduler email loop in run-mql5-verify-task.ps1) to byte-stable output:
# Get-VerifySummaryLine / Get-FirstProblem are extracted LIVE out of
# verify_all.ps1 and run against synthetic PASS/FAIL/SKIP rows, asserting the
# exact string each row-set must produce.  A future edit that changes the
# line's shape (token order, separator, slug vocabulary, missing failed=
# when red) fails this harness — and because it runs in verify_all.ps1's own
# pre-flight (step 7), the loop catches the drift before a single tester run.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File mql5/verify_verifyline_fixtures.ps1
$ErrorActionPreference = 'Stop'
$ps1 = Join-Path $PSScriptRoot 'verify_all.ps1'
$text = Get-Content $ps1 -Raw

# Extract each function with balanced braces and define it in THIS session.
# Invoke-Expression must run at script scope (not inside a helper function —
# function definitions created inside a function scope vanish when it returns;
# foreach is not a scope boundary, so this loop is fine).
foreach ($fnName in @('Get-FirstProblem', 'Get-VerifySummaryLine')) {
  $start = $text.IndexOf("function $fnName")
  if ($start -lt 0) { throw "function $fnName not found in verify_all.ps1" }
  # Comment-aware brace scan (apostrophes in # comments must not flip string mode).
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
  Invoke-Expression ($text.Substring($start, $i - $start + 1))
}

$script:failed = $false
function Assert-Line([string]$name, [object[]]$rows, [string]$expected) {
  $got = Get-VerifySummaryLine $rows
  if ($got -ceq $expected) { Write-Host "PASS  $name  $got" }
  else {
    Write-Host "FAIL  $name"
    Write-Host "      expected: $expected"
    Write-Host "      got:      $got"
    $script:failed = $true
  }
}
function Assert-Slug([string]$name, [string]$detail, [string]$expected) {
  $got = Get-FirstProblem $detail
  if ($got -ceq $expected) { Write-Host "PASS  $name  $got" }
  else {
    Write-Host "FAIL  $name  (detail='$detail') expected='$expected' got='$got'"
    $script:failed = $true
  }
}

function Row([string]$Suite, [string]$Compile, [string]$Tester, [string]$Detail) {
  return [pscustomobject]@{ Suite = $Suite; Compile = $Compile; Tester = $Tester; Detail = $Detail }
}

# --- byte-stable summary lines ----------------------------------------------
Assert-Line 'all-green' @(
  (Row 'Phase1Tests' 'OK' 'PASS' 'PASS - all good'),
  (Row 'SniperGate'  '-'  'PASS' 'PASS - n=277 exp +0.119R'),
  (Row 'CalibrationGate' '-' 'SKIP' 'python unavailable')
) '[VERIFY] summary ok=1 rows=3 green=2 red=0 skip=1'

Assert-Line 'single-fail-with-slug' @(
  (Row 'Phase1Tests' 'OK' 'PASS' 'PASS - all good'),
  (Row 'Phase10ESignGate' '-' 'FAIL' 'FAIL - P10-E SIGN FLIP: EA 300s sumR +60.496 vs CLI exp -0.393 disagree in sign; re-baseline deliberately'),
  (Row 'CalibrationGate' '-' 'SKIP' 'python unavailable')
) '[VERIFY] summary ok=0 rows=3 green=1 red=1 skip=1 failed=Phase10ESignGate:sign-flip'

Assert-Line 'two-fails-named-in-order' @(
  (Row 'Phase10Gate' '-' 'FAIL' 'FAIL - STRICT: EA hit 1.02% vs CLI 31.02% differs by more than 5pp; STRICT: EA sumR sign disagrees'),
  (Row 'Phase6RiskGate' '-' 'FAIL' 'FAIL - CLI reference TIMED OUT (900s) - backtest-vol hung'),
  (Row 'Phase10ESignGate' '-' 'PASS' 'PASS - real-tick sumR agrees in sign')
) '[VERIFY] summary ok=0 rows=3 green=1 red=2 skip=0 failed=Phase10Gate:strict-hit,Phase6RiskGate:timeout'

Assert-Line 'compile-fail-row' @(
  (Row 'BandBackTests' 'FAIL' '-' 'no .ex5 produced'),
  (Row 'Phase2Tests' 'OK' 'PASS' 'PASS - ok')
) '[VERIFY] summary ok=0 rows=2 green=1 red=1 skip=0 failed=BandBackTests:no-artifact'

Assert-Line 'empty-results' @() '[VERIFY] summary ok=1 rows=0 green=0 red=0 skip=0'

Assert-Line 'all-skip' @(
  (Row 'SniperGate' '-' 'SKIP' 'python unavailable'),
  (Row 'RealCorpus' '-' 'SKIP' 'corpus too thin')
) '[VERIFY] summary ok=1 rows=2 green=0 red=0 skip=2'

Assert-Line 'strict-trades-slug' @(
  (Row 'Phase10Gate' '-' 'FAIL' 'FAIL - STRICT: EA trades 98 vs CLI 112 differ by more than 10; STRICT: EA hit differs by more than 5pp')
) '[VERIFY] summary ok=0 rows=1 green=0 red=1 skip=0 failed=Phase10Gate:strict-trades'

# --- first-problem slug extraction ------------------------------------------
Assert-Slug 'slug: sign-flip'      'FAIL - P10-E SIGN FLIP: EA 300s sumR +60.496 vs CLI exp -0.393' 'sign-flip'
Assert-Slug 'slug: strict-hit'     'FAIL - STRICT: EA hit 1.02% vs CLI 31.02% differs by more than 5pp; STRICT: EA sumR sign disagrees' 'strict-hit'
Assert-Slug 'slug: strict-trades'  'FAIL - STRICT: EA trades 98 vs CLI 112 differ by more than 10' 'strict-trades'
Assert-Slug 'slug: no-machine-line' 'no [PHASE10] trades= machine line in verify_20260817.log - Phase10IntegrationTests did not run' 'no-machine-line'
Assert-Slug 'slug: timeout'        'CLI reference TIMED OUT (900s) - backtest-vol hung; treat as regression' 'timeout'
Assert-Slug 'slug: unparseable'    'CLI reference output unparseable (no trades=/win_rate=/expectancy_r=)' 'unparseable'
Assert-Slug 'slug: corpus-missing' 'R_75 corpus not found at data/backfill/R_75_ticks.csv - Phase-10 P10-A gate cannot run' 'corpus-missing'
Assert-Slug 'slug: run-failed'     'FAIL - R_100 four-leg sign-lock FAILED to run: python not on PATH' 'run-failed'
Assert-Slug 'slug: r75-sign-flip'  'FAIL - R_75 SIGN FLIP: CLI reference expectancy +0.310 (n=102) is non-negative' 'sign-flip'
Assert-Slug 'slug: sniper-ohlc-delta' 'FAIL - SNIPER-OHLC delta_max 9.87 R exceeds the 5.00 R model-robustness ceiling (machine verdict FLIP)' 'sniper-ohlc-delta'
Assert-Slug 'slug: generic-fallback' 'FAIL - something went wrong entirely; no rule matched' 'something-went'
Assert-Slug 'slug: empty'          '' 'no-detail'

if ($script:failed) { Write-Host "FIXTURES: FAILED" -ForegroundColor Red; exit 1 }
Write-Host "FIXTURES: ALL PASS" -ForegroundColor Green
