# Fixture harness for the vol-regime contract inside Test-DepthSplit.
# Extracts the function body from verify_all.ps1 and runs it against crafted
# log lines (REAL tester-log formats, verified against 20260812.log), asserting
# PASS/FAIL for each branch.
$ErrorActionPreference = 'Stop'
$ps1 = Join-Path $PSScriptRoot 'verify_all.ps1'
$text = Get-Content $ps1 -Raw

# Extract the Test-DepthSplit function (balanced braces).
$start = $text.IndexOf('function Test-DepthSplit')
if ($start -lt 0) { throw 'Test-DepthSplit not found' }
$depth = 0; $i = $start; $inStr = $false; $strCh = ''
for (; $i -lt $text.Length; $i++) {
  $ch = $text[$i]
  if ($inStr) {
    if ($ch -eq $strCh) {
      if ($i + 1 -lt $text.Length -and $text[$i + 1] -eq $strCh) { $i++ } else { $inStr = $false }
    }
    continue
  }
  if ($ch -eq "'" -or $ch -eq '"') { $inStr = $true; $strCh = $ch; continue }
  if ($ch -eq '{') { $depth++ }
  elseif ($ch -eq '}') { $depth--; if ($depth -eq 0) { break } }
}
$fn = $text.Substring($start, $i - $start + 1)
Invoke-Expression $fn   # define Test-DepthSplit in this session

# Real formats from the tester log (2026-08-12 default RR-3.0 run):
#   [BANDBT]   depth <= 1.50:  n=171  hit=26.3%  exp=+0.053R  (mean floor at entry 30.0%)  -> misses the floor
#   [BANDBT]   vol<=1.25    n=1527 hit= 25.3% exp=+0.014R sumR=+22.0R  hold= 2.0b  stop-outs=74.6%
#   [BANDBT]   vol>1.25     n=  10 hit= 30.0% exp=+0.200R sumR=+2.0R  hold= 2.5b  stop-outs=70.0%
$runBlock = @(
  '2026.08.12 07:00:44 Core 1  [BANDBT] === BandGeometry tester backtest on SYN75 M5 starting ===',
  '2026.08.12 07:00:44 Core 1  [BANDBT]   depth <= 1.25:  n= 86  hit=31.4%  exp=+0.256R  (mean floor at entry 30.0%)  -> CLEARS the floor',
  '2026.08.12 07:00:44 Core 1  [BANDBT]   depth <= 1.50:  n=171  hit=26.3%  exp=+0.053R  (mean floor at entry 30.0%)  -> misses the floor',
  '2026.08.12 07:00:44 Core 1  [BANDBT]   depth <= 2.00:  n=329  hit=25.8%  exp=+0.033R  (mean floor at entry 30.0%)  -> misses the floor',
  '2026.08.12 07:00:44 Core 1  [BANDBT]   depth <= 2.50:  n=497  hit=26.0%  exp=+0.038R  (mean floor at entry 30.0%)  -> misses the floor',
  '2026.08.12 07:00:44 Core 1  [BANDBT]   depth <= 3.00:  n=693  hit=25.4%  exp=+0.017R  (mean floor at entry 30.0%)  -> misses the floor',
  '2026.08.12 07:00:44 Core 1  [BANDBT] vol-regime split at entry (prev_sigma / sigma_ema):',
  '2026.08.12 07:00:44 Core 1  [BANDBT]   vol<=1.25    n=1527 hit= 25.3% exp=+0.014R sumR=+22.0R  hold= 2.0b  stop-outs=74.6%',
  '2026.08.12 07:00:44 Core 1  [BANDBT]   vol>1.25     n=  10 hit= 30.0% exp=+0.200R sumR=+2.0R  hold= 2.5b  stop-outs=70.0%',
  '2026.08.12 07:00:44 Core 1  [BANDBT] Stage-3 empirical floor gate (TradeQualityEngine.BreakEvenFloor):',
  '2026.08.12 07:00:44 Core 1  [BANDBT]   floor = 1/(1+avg planned RR) + margin;  margin=0.05  min_samples=10  (journal@last-entry: n=1536 hit=25.3% avgRR=3.00 exp=+0.014R)',
  '2026.08.12 07:00:44 Core 1  [BANDBT]   mean floor at entry 30.0%  (band 3.00-RR geometry needs 30.0% to break even)',
  '2026.08.12 07:00:44 Core 1  [BANDBT]   VERDICT: achieved hit 25.4% does NOT beat the 30.0% floor  the band''s 3.00-RR geometry is NOT floor-beatable on this window  the gate stands aside',
  '2026.08.12 07:00:44 Core 1  [BANDBT] DEPTHPROFILE caps=1.25,1.50,2.00,2.50,3.00 n=86,171,329,497,693 hit=31.4,26.3,25.8,26.0,25.4 exp=+0.256,+0.053,+0.033,+0.038,+0.017 share=12.4,24.7,47.5,71.7,100.0 total=693',
  '2026.08.12 07:00:44 Core 1  [BANDBT] FLOORVERDICT floor=30.0 achieved=25.4 verdict=NOT_BEAT mean_rr=3.00'
)

function Assert-Case([string]$name, [bool]$cond, [string]$detail) {
  if ($cond) { Write-Host "PASS  $name  $detail" } else { Write-Host "FAIL  $name  $detail"; $script:failed = $true }
}

$script:failed = $false

# 1. Healthy current state: tiny high-vol share, positive exp -> PASS, state in okMsg
$r = Test-DepthSplit $runBlock
Assert-Case 'healthy-tiny-share' ($r.ok) "msgs=[$($r.msgs -join '; ')] okMsg=$($r.okMsg)"
if ($r.okMsg -notmatch 'vol-split:.*>1\.25 n=10 hit=30\.0% exp=\+0\.200R \(0\.7% of trades\)') {
  Assert-Case 'healthy-state-in-okMsg' $false "missing vol-split state: $($r.okMsg)"
} else { Assert-Case 'healthy-state-in-okMsg' $true $r.okMsg }

# 2. Meaningful share + negative exp -> FAIL
$bleed = $runBlock | ForEach-Object { $_ -replace 'vol>1\.25\s+n=\s*10\s+hit=\s*30\.0%\s+exp=\+0\.200R', 'vol>1.25     n= 400 hit= 18.0% exp=-0.120R' }
$r = Test-DepthSplit $bleed
$msg = ($r.msgs -join '; ')
Assert-Case 'meaningful-share-negative-exp' (-not $r.ok -and $msg -match 'vol>1\.25 cell is .*% of trades with exp -0\.12R') $msg

# 3. Meaningful share + positive exp -> PASS (reported, not failed)
$bigpos = $runBlock | ForEach-Object { $_ -replace 'vol>1\.25\s+n=\s*10\s+hit=\s*30\.0%\s+exp=\+0\.200R', 'vol>1.25     n= 400 hit= 32.0% exp=+0.150R' }
$r = Test-DepthSplit $bigpos
Assert-Case 'meaningful-share-positive-exp' ($r.ok -and $r.okMsg -match '>1\.25 n=400 hit=32\.0% exp=\+0\.150R') $r.okMsg

# 4. Share >= 35% -> FAIL unconditionally (even with positive exp)
$dom = $runBlock | ForEach-Object { $_ -replace 'vol>1\.25\s+n=\s*10\s+hit=\s*30\.0%\s+exp=\+0\.200R', 'vol>1.25     n= 900 hit= 35.0% exp=+0.100R' }
$r = Test-DepthSplit $dom
$msg = ($r.msgs -join '; ')
Assert-Case 'share-dominates-book' (-not $r.ok -and $msg -match 'cell IS the book') $msg

# 5. vol>1.25 line absent entirely (zero high-vol trades) -> PASS, n=0 state
$zero = $runBlock | Where-Object { $_ -notmatch 'vol>1\.25' }
$r = Test-DepthSplit $zero
Assert-Case 'zero-high-vol-cell' ($r.ok -and $r.okMsg -match '>1\.25 n=0 \(0\.0% of trades\)') $r.okMsg

# 6. split header missing -> FAIL
$noHeader = $runBlock | Where-Object { $_ -notmatch 'vol-regime split at entry' }
$r = Test-DepthSplit $noHeader
$msg = ($r.msgs -join '; ')
Assert-Case 'missing-vol-header' (-not $r.ok -and $msg -match 'vol-regime split report MISSING') $msg

# 7. header present but no vol<=1.25 row -> FAIL
$noLo = $runBlock | Where-Object { $_ -notmatch 'vol<=1\.25' }
$r = Test-DepthSplit $noLo
$msg = ($r.msgs -join '; ')
Assert-Case 'missing-vol-lo-row' (-not $r.ok -and $msg -match 'no vol<=1\.25 row') $msg

# 8. healthy depth profile: composition in bands -> PASS, depth-comp state in okMsg
$r = Test-DepthSplit $runBlock
if ($r.okMsg -notmatch 'depth-comp: <=1\.25 12\.4% \| <=1\.50 24\.7% \| <=2\.50 71\.7% \(total 693\)') {
  Assert-Case 'depth-comp-in-okMsg' $false "missing depth-comp state: $($r.okMsg)"
} else { Assert-Case 'depth-comp-in-okMsg' $true $r.okMsg }

# 9. bucket composition shifted: deep dominates (<=1.25 share 2.0%) -> FAIL
$deep = $runBlock | ForEach-Object { $_ -replace 'n=86,171,329,497,693 .*? total=693', 'n=14,28,120,520,693 hit=27.8,27.5,23.2,24.2,24.3 exp=+0.111,+0.101,-0.073,-0.032,-0.026 share=2.0,4.0,17.3,75.0,100.0 total=693' }
$r = Test-DepthSplit $deep
$msg = ($r.msgs -join '; ')
Assert-Case 'composition-deep-dominant' (-not $r.ok -and $msg -match 'bucket composition shifted') $msg

# 10. DEPTHPROFILE line missing -> FAIL
$noDp = $runBlock | Where-Object { $_ -notmatch 'DEPTHPROFILE' }
$r = Test-DepthSplit $noDp
$msg = ($r.msgs -join '; ')
Assert-Case 'missing-depthprofile' (-not $r.ok -and $msg -match 'DEPTHPROFILE line MISSING') $msg

# 11. FLOORVERDICT line missing -> FAIL
$noFv = $runBlock | Where-Object { $_ -notmatch 'FLOORVERDICT' }
$r = Test-DepthSplit $noFv
$msg = ($r.msgs -join '; ')
Assert-Case 'missing-floorverdict' (-not $r.ok -and $msg -match 'FLOORVERDICT line MISSING') $msg

# 12. FLOORVERDICT contradicts the human VERDICT -> FAIL
$badFv = $runBlock | ForEach-Object { $_ -replace 'FLOORVERDICT floor=30\.0 achieved=25\.4 verdict=NOT_BEAT', 'FLOORVERDICT floor=30.0 achieved=25.4 verdict=BEAT' }
$r = Test-DepthSplit $badFv
$msg = ($r.msgs -join '; ')
Assert-Case 'floorverdict-mismatch' (-not $r.ok -and $msg -match 'contradicts human VERDICT') $msg

# 13. thin window (total < 50): composition bands skipped -> PASS
$small = $runBlock | ForEach-Object {
  $_ -replace 'depth <= 1\.25:  n= 86', 'depth <= 1.25:  n=  1' `
     -replace 'depth <= 1\.50:  n=171', 'depth <= 1.50:  n=  2' `
     -replace 'depth <= 2\.00:  n=329', 'depth <= 2.00:  n=  3' `
     -replace 'depth <= 2\.50:  n=497', 'depth <= 2.50:  n=  5' `
     -replace 'depth <= 3\.00:  n=693', 'depth <= 3.00:  n= 30' `
     -replace 'n=86,171,329,497,693 .*? total=693', 'n=1,2,3,5,30 hit=31.4,26.3,25.8,26.0,25.4 exp=+0.256,+0.053,+0.033,+0.038,+0.017 share=3.3,6.7,10.0,16.7,100.0 total=30'
}
$r = Test-DepthSplit $small
$msg = ($r.msgs -join '; ')
Assert-Case 'thin-window-composition-skipped' ($r.ok) "msgs=[$msg]"

if ($script:failed) { Write-Host "FIXTURES: FAILED" -ForegroundColor Red; exit 1 }
Write-Host "FIXTURES: ALL PASS" -ForegroundColor Green
