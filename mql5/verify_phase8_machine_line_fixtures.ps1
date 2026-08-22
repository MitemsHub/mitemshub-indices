# Fixture harness for the [PHASE8-ANALYTICS] machine-line parse contract.
#
# Regression targets (2026-08-17 audit):
#  1. beats vocabulary: the harness previously emitted `beats=BEATS` while the
#     gate's regex required `beats=(yes|no)` — a case-sensitive [regex]::Match
#     never matches `BEATS`, so the FIRST BEATS verdict would have bailed the
#     gate as "unparseable" instead of failing the loop loudly (the masked-flip
#     failure the Model=2 sweep exposed, re-armed on the positive/proven side).
#     The emitter now prints `beats=yes|no`; this harness makes BOTH sides a
#     permanent contract: the gate pattern's `(yes|no)` must still parse real
#     yes/no lines AND must NOT parse a `beats=BEATS` line, and the Python
#     emitter must still contain the yes/no vocabulary line.
#  2. exp=/sumR= sign assumptions: the band/buckets emitters force `%+` signs
#     today (`:+.3f` / `:+.2f`); if a harness drops the forced sign (a %g/%f
#     format switch) or a regex reverts to `[+-]`-required, a positive
#     expectancy bails as unparseable.  The gate now uses the shared $NumTok
#     token (optional sign + exponent form); this harness asserts forced-plus,
#     no-sign, zero, and negative values all parse, with a negative control
#     pinning that a sign-required pattern still bails on the no-sign line.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File mql5/verify_phase8_machine_line_fixtures.ps1
$ErrorActionPreference = 'Stop'
$ps1 = Join-Path $PSScriptRoot 'verify_all.ps1'
$py  = Join-Path $PSScriptRoot 'phase8_analytics_check.py'
if (-not (Test-Path $ps1)) { throw "verify_all.ps1 not found at $ps1" }
if (-not (Test-Path $py))  { throw "phase8_analytics_check.py not found at $py" }
$text  = Get-Content $ps1 -Raw
$pySrc = Get-Content $py -Raw

# --- extract the REAL $NumTok definition (as the gates interpolate it) -------
$NumTok = [regex]::Match($text, '(?m)^\$NumTok = ''([^'']+)''').Groups[1].Value
if (-not $NumTok) { throw 'cannot extract $NumTok from verify_all.ps1' }

# --- extract the REAL Phase-8 gate pattern literals (band / buckets / exit) --
# Each is captured WITH its surrounding quotes so [scriptblock]::Create parses
# it as a PowerShell string literal (the same mechanism as the Phase-10
# harness) — evaluating it interpolates $NumTok and yields the exact regex
# string the runtime uses.  band/buckets are double-quoted in the file (they
# interpolate $NumTok); exit is single-quoted.
$bandPat = [regex]::Match($text, 'Match\(\$band, ("[^"]+")\)').Groups[1].Value
$bktsPat = [regex]::Match($text, 'Match\(\$bkts, ("[^"]+")\)').Groups[1].Value
$exitPat = [regex]::Match($text, 'Match\(\$exit, (''[^'']+'')\)').Groups[1].Value
if (-not $bandPat -or -not $bktsPat -or -not $exitPat) { throw 'cannot extract Phase-8 gate patterns from verify_all.ps1' }
$bandRe = & ([scriptblock]::Create($bandPat))
$bktsRe = & ([scriptblock]::Create($bktsPat))
$exitRe = & ([scriptblock]::Create($exitPat))

$script:failed = $false
function Assert-Case([string]$name, [bool]$cond, [string]$detail) {
  if ($cond) { Write-Host "PASS  $name  $detail" } else { Write-Host "FAIL  $name  $detail"; $script:failed = $true }
}

# --- synthetic machine lines in the REAL emitter format -----------------------
# band: n / hit / exp (forced +) / sumR (forced +) / maxDD / floor / beats
$bandNeg = '[PHASE8-ANALYTICS] band n=81 hit=3.70% exp=-0.591R sumR=-47.87R maxDD=2.34R floor=30.0% beats=no'
# Positive flip shape (the class the sign audit protects) — forced '+' today.
$bandPos = '[PHASE8-ANALYTICS] band n=65 hit=44.62% exp=+0.397R sumR=+25.81R maxDD=1.10R floor=30.0% beats=yes'
# No-sign positive — what a %g/%f emitter switch would print; must still parse.
$bandNoSign = '[PHASE8-ANALYTICS] band n=65 hit=44.62% exp=0.397R sumR=25.81R maxDD=1.10R floor=30.0% beats=yes'
$bandZero = '[PHASE8-ANALYTICS] band n=40 hit=25.00% exp=+0.000R sumR=+0.00R maxDD=0.90R floor=25.0% beats=no'
# buckets: strong n / exp (forced +) / hit | weak n / exp (forced +) / hit
$bkts = '[PHASE8-ANALYTICS] buckets strong n=22 exp=-0.812R hit=18.18% | weak n=59 exp=-0.509R hit=8.47%'
# exit: stop / trail / target / time counts
$exit = '[PHASE8-ANALYTICS] exit stop n=40 trail n=12 target n=21 time n=8'
# The masked-flip shape: an emitter that regressed to the old BEATS vocabulary.
$beatsBad = '[PHASE8-ANALYTICS] band n=65 hit=44.62% exp=+0.397R sumR=+25.81R maxDD=1.10R floor=30.0% beats=BEATS'

Assert-Case 'phase8-patterns-extracted' ($bandPat -and $bktsPat -and $exitPat) "band=$($bandPat.Length)b buckets=$($bktsPat.Length)b exit=$($exitPat.Length)b"

# 1. band line parses with the REAL gate groups: 1=n 2=hit 3=exp 4=sumR
#    5=maxDD 6=floor 7=beats.
$m = [regex]::Match($bandNeg, $bandRe)
Assert-Case 'band negative parses' ($m.Success -and $m.Groups[1].Value -eq '81' -and [double]$m.Groups[3].Value -eq -0.591 -and [double]$m.Groups[4].Value -eq -47.87 -and $m.Groups[7].Value -eq 'no') "n=$($m.Groups[1].Value) exp=$($m.Groups[3].Value) beats=$($m.Groups[7].Value)"

# 2. forced-plus positive (today's emitter) parses.
$m = [regex]::Match($bandPos, $bandRe)
Assert-Case 'band forced-plus positive parses' ($m.Success -and [double]$m.Groups[3].Value -eq 0.397 -and [double]$m.Groups[4].Value -eq 25.81 -and $m.Groups[7].Value -eq 'yes') "exp=$($m.Groups[3].Value) sumR=$($m.Groups[4].Value)"

# 3. no-sign positive (a dropped forced sign) parses — the $NumTok guard.
$m = [regex]::Match($bandNoSign, $bandRe)
Assert-Case 'band no-sign positive parses' ($m.Success -and [double]$m.Groups[3].Value -eq 0.397) "exp=$($m.Groups[3].Value)"

# 4. zero parses.
$m = [regex]::Match($bandZero, $bandRe)
Assert-Case 'band zero parses' ($m.Success -and [double]$m.Groups[3].Value -eq 0.0) "exp=$($m.Groups[3].Value)"

# 5. buckets parses with the REAL groups: 1=strongN 2=strongE 3=strongHit
#    4=weakN 5=weakE 6=weakHit.
$m = [regex]::Match($bkts, $bktsRe)
Assert-Case 'buckets parses' ($m.Success -and $m.Groups[1].Value -eq '22' -and [double]$m.Groups[2].Value -eq -0.812 -and $m.Groups[4].Value -eq '59' -and [double]$m.Groups[5].Value -eq -0.509) "strong $($m.Groups[1].Value)@$($m.Groups[2].Value)R | weak $($m.Groups[4].Value)@$($m.Groups[5].Value)R"

# 6. exit parses with the REAL groups: 1=stop 2=trail 3=target 4=time.
$m = [regex]::Match($exit, $exitRe)
Assert-Case 'exit parses' ($m.Success -and $m.Groups[1].Value -eq '40' -and $m.Groups[2].Value -eq '12' -and $m.Groups[3].Value -eq '21' -and $m.Groups[4].Value -eq '8') "stop $($m.Groups[1].Value) trail $($m.Groups[2].Value) target $($m.Groups[3].Value) time $($m.Groups[4].Value)"

# 7. beats vocabulary: both real values parse through the gate pattern.
$mYes = [regex]::Match($bandPos, $bandRe)
$mNo  = [regex]::Match($bandNeg, $bandRe)
Assert-Case 'beats yes|no vocabulary parses' ($mYes.Groups[7].Value -eq 'yes' -and $mNo.Groups[7].Value -eq 'no') "yes=$($mYes.Groups[7].Value) no=$($mNo.Groups[7].Value)"

# 8. NEGATIVE CONTROL: a beats=BEATS line must NOT parse — the masked-flip
#    regression.  If the gate's (yes|no) ever regresses to accept BEATS, this
#    fails; if an emitter regresses to emitting BEATS, the gate bails loudly
#    (unparseable) instead of silently passing.
Assert-Case 'negative control: beats=BEATS does not parse' (-not [regex]::Match($beatsBad, $bandRe).Success) ''

# 9. NEGATIVE CONTROL: a sign-required exp pattern (the pre-$NumTok form) must
#    still bail on the no-sign positive line — pinning what this harness
#    discriminates for the sign class.
$oldSign = 'n=(\d+) hit=([\d.]+)% exp=([+-][\d.]+)R sumR=([+-][\d.]+)R maxDD=([\d.]+)R floor=([\d.]+)% beats=(yes|no)'
Assert-Case 'negative control: sign-required pattern bails on no-sign positive' (-not [regex]::Match($bandNoSign, $oldSign).Success) 'must stay red'
Assert-Case 'negative control: sign-required pattern still parses signed negative' ([regex]::Match($bandNeg, $oldSign).Success) ''

# 10. EMITTER contract (phase8_analytics_check.py source): the vocabulary and
#     forced signs must still be present, so a beats=BEATS-style regression or
#     a dropped forced sign is caught before it ever reaches the gate.
Assert-Case 'emitter: beats vocabulary is yes|no' $pySrc.Contains('beats = "yes" if v["beats_floor"] else "no"') ''
Assert-Case 'emitter: band exp forced + sign' $pySrc.Contains('exp={summary.avg_r:+.3f}R') ''
Assert-Case 'emitter: band sumR forced + sign' $pySrc.Contains('sumR={summary.sum_r:+.2f}R') ''
Assert-Case 'emitter: buckets exps forced + sign' ($pySrc.Contains('exp={by_conf[1].avg_r():+.3f}R') -and $pySrc.Contains('exp={by_conf[0].avg_r():+.3f}R')) ''
Assert-Case 'emitter: band/buckets/exit line prefixes' ($pySrc.Contains('[PHASE8-ANALYTICS] band n=') -and $pySrc.Contains('[PHASE8-ANALYTICS] buckets strong') -and $pySrc.Contains('[PHASE8-ANALYTICS] exit stop')) ''

if ($script:failed) { Write-Host "FIXTURES: FAILED" -ForegroundColor Red; exit 1 }
Write-Host "FIXTURES: ALL PASS" -ForegroundColor Green
