# Fixture harness for the multi-seed stability gate (Test-SeedStability) inside
# verify_all.ps1.  Extracts the function body and runs it against crafted
# per-seed row sets, asserting PASS/FAIL for each branch:
#   - stable means (PASS)
#   - the MEASURED 2026-08-12 5-seed numbers (mean +0.023R, spread 0.190R ->
#     must FAIL as seed noise)
#   - absolute spread > 0.25R (FAIL)
#   - fragile small positive mean (spread > 3x mean, FAIL)
#   - too few seeds (FAIL)
$ErrorActionPreference = 'Stop'
$ps1 = Join-Path $PSScriptRoot 'verify_all.ps1'
$text = Get-Content $ps1 -Raw

# Extract the Test-SeedStability function (balanced braces, string-aware).
$start = $text.IndexOf('function Test-SeedStability')
if ($start -lt 0) { throw 'Test-SeedStability not found' }
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
$fn = $text.Substring($start, $i - $start + 1)
Invoke-Expression $fn   # define Test-SeedStability in this session

function Assert-Case([string]$name, [bool]$cond, [string]$detail) {
  if ($cond) { Write-Host "PASS  $name  $detail" } else { Write-Host "FAIL  $name  $detail"; $script:failed = $true }
}

$script:failed = $false

# Rows: @{ n125; hit125; exp125; n200; hit200; exp200 }
function New-Row([double]$e125, [double]$e200, [long]$n125 = 100, [long]$n200 = 320, [double]$h125 = 28.0, [double]$h200 = 25.5) {
  return [pscustomobject]@{ n125 = $n125; hit125 = $h125; exp125 = $e125; n200 = $n200; hit200 = $h200; exp200 = $e200 }
}

# 1. Stable means: every seed solidly positive, tight spread -> PASS
$stable = @(
  (New-Row 0.22 0.24), (New-Row 0.26 0.28), (New-Row 0.20 0.22), (New-Row 0.24 0.26), (New-Row 0.28 0.30)
)
$r = Test-SeedStability $stable
$msg = ($r.msgs -join '; ')
Assert-Case 'stable-means' ($r.ok) "msgs=[$msg] stats=[$($r.stats -join ' | ')]"

# 2. THE MEASURED 2026-08-12 5-seed run at RR 3.0 (seed_sweep.ps1 output):
#    cap-2.00 exp -0.079..+0.111 (mean +0.023, spread 0.190),
#    cap-1.25 exp -0.257..+0.256 (mean -0.012, spread 0.513) -> FAIL both cells
$measured = @(
  (New-Row -0.038  0.018  -n200 323 -h200 25.4),
  (New-Row  0.256  0.033  -n200 329 -h200 25.8),
  (New-Row -0.241 -0.079  -n200 317 -h200 23.0),
  (New-Row -0.257  0.034  -n200 298 -h200 25.8),
  (New-Row  0.222  0.111  -n200 324 -h200 27.8)
)
$r = Test-SeedStability $measured
$msg = ($r.msgs -join '; ')
Assert-Case 'measured-noise-fails' (-not $r.ok) "msgs=[$msg]"
Assert-Case 'measured-noise-mean-msg' ($msg -match 'NOT positive after seed averaging') $msg
Assert-Case 'measured-noise-spread-msg' ($msg -match 'not distinguishable from seed noise') $msg

# 3. Absolute spread > 0.25R -> FAIL even though the mean clears the floor
$wide = @(
  (New-Row 0.25 0.25), (New-Row -0.05 -0.05), (New-Row 0.10 0.10), (New-Row 0.15 0.15), (New-Row 0.05 0.05)
)  # mean 0.10, spread 0.30 -> rule 2 fires
$r = Test-SeedStability $wide
$msg = ($r.msgs -join '; ')
Assert-Case 'absolute-spread-fails' (-not $r.ok -and $msg -match '> 0\.25R') $msg

# 4. Fragile small positive mean: mean 0.06 clears the floor, spread 0.21 is
#    within the absolute cap, but spread is 3.5x the mean -> rule 3 fires
$fragile = @(
  (New-Row 0.19 0.19), (New-Row -0.02 -0.02), (New-Row 0.08 0.08), (New-Row 0.06 0.06), (New-Row -0.01 -0.01)
)  # mean 0.06, spread 0.21, ratio 3.5x
$r = Test-SeedStability $fragile
$msg = ($r.msgs -join '; ')
Assert-Case 'fragile-small-mean-fails' (-not $r.ok -and $msg -match 'small mean not distinguishable') $msg

# 5. Too few seeds -> FAIL (aggregation meaningless)
$few = @((New-Row 0.20 0.25), (New-Row 0.22 0.27))
$r = Test-SeedStability $few
$msg = ($r.msgs -join '; ')
Assert-Case 'too-few-seeds-fails' (-not $r.ok -and $msg -match 'need >= 3 seeds') $msg

# 6. Healthy but mixed hit spreads -> still PASS (hit is reported, not gated)
$mixedHit = @(
  (New-Row 0.22 0.24 -h125 27.0 -h200 23.0),
  (New-Row 0.26 0.28 -h125 29.0 -h200 27.8),
  (New-Row 0.20 0.22 -h125 30.0 -h200 25.0),
  (New-Row 0.24 0.26 -h125 28.0 -h200 26.0),
  (New-Row 0.28 0.30 -h125 26.0 -h200 24.0)
)
$r = Test-SeedStability $mixedHit
$msg = ($r.msgs -join '; ')
Assert-Case 'hit-spread-not-gated' ($r.ok) "msgs=[$msg]"

if ($script:failed) { Write-Host "FIXTURES: FAILED" -ForegroundColor Red; exit 1 }
Write-Host "FIXTURES: ALL PASS" -ForegroundColor Green
