# seed_sweep.ps1 — quantify the RNG-reshuffle confound in BandBackTests.
#
# The suite's per-signal geometry sweep (MathSrand(InpGeomSeed)) draws z_entry
# in [0.7, 1.6] and stop_mult in [0.15, 0.35] (target = InpDerivedTargetRR x
# stop) for EVERY gated signal, so the seed decides which signals pass the z
# gate, their stop width, and their edge-depth bucket.  A single seed (default
# 42) is ONE sample of that distribution — this script runs several seeds at
# the RR-3.0 default geometry and reports the hit/exp spread of the depth
# cap-2.0 cell (the reference cell used in the docs) so seed noise can be
# separated from real signal.
#
#   powershell -File mql5/seed_sweep.ps1            # default: 7,42,123,777,2024
#   powershell -File mql5/seed_sweep.ps1 -Seeds "11,42,99" -RangeDays 180
#
# Each seed = one verify_all.ps1 invocation (compile + 6-month tester,
# sniper gate skipped), ~25-40s each.  The tester log is copied per seed so
# the full depth-split rows can be parsed; logs land in mql5/seed_sweep/.
#
# NOTE on the parsed-array variable: the param is [string]$Seeds, which
# TYPE-CONSTRAINS the variable.  Assigning the split result to a same-named
# (case-insensitive) variable like `$seeds = @($Seeds -split ',')` silently
# converts the array back to a string (space-joined) — a real PowerShell 5.1
# trap that produced `count=1 items=[11 42 99]`.  The parsed list must use a
# DISTINCT name ($seedList below).
param(
  [string]$Seeds = "7,42,123,777,2024",
  [int]$RangeDays = 180
)
$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$outDir = Join-Path $scriptRoot 'seed_sweep'
New-Item -ItemType Directory -Path $outDir -Force | Out-Null

# Machine-line numeric token (same convention as verify_all.ps1): optional
# sign + fixed-point/exponent form, so a positive exp (the BandBackTests
# emitter forces '%+' today) or a %g/%e format switch cannot break the parse.
# One capturing group, so downstream group indexes are unchanged.
$NumTok = '([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)'

# Deriv terminal data folder (same discovery as verify_all.ps1)
$termBase = Join-Path $env:APPDATA 'MetaQuotes\Terminal'
$td = Get-ChildItem $termBase -Directory -ErrorAction SilentlyContinue | Where-Object {
  $o = Join-Path $_.FullName 'origin.txt'
  (Test-Path $o) -and ((Get-Content $o -Raw -ErrorAction SilentlyContinue) -match 'Deriv')
} | Select-Object -First 1
if (-not $td) { throw 'Cannot discover the Deriv terminal data folder' }
$testerLog = Join-Path $td.FullName ("Tester\logs\" + (Get-Date).ToString('yyyyMMdd') + '.log')

# Distinct name — see the NOTE above about [string]-param type constraints.
$seedList = @($Seeds -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
Write-Host "==> seed sweep: seeds=[$($seedList -join ', ')] rangeDays=$RangeDays"

foreach ($seed in $seedList) {
  Write-Host "==> seed $seed ($(Get-Date -Format 'HH:mm:ss'))"
  & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $scriptRoot 'verify_all.ps1') `
    -Suite BandBackTests -RangeDays $RangeDays -SkipSniperGate `
    -Inputs "InpGeomSeed=$seed" | Out-Null
  if ($LASTEXITCODE -ne 0) { Write-Host "    WARNING: verify_all exited $LASTEXITCODE for seed $seed" }
  if (Test-Path $testerLog) {
    Copy-Item $testerLog (Join-Path $outDir ("tester_seed_$seed.log")) -Force
  } else {
    Write-Host "    WARNING: no tester log to copy for seed $seed"
  }
}

# --- parse: per seed, take the LAST run block (that seed) and pull the rows --
$rows = @()
foreach ($seed in $seedList) {
  $f = Join-Path $outDir ("tester_seed_$seed.log")
  if (-not (Test-Path $f)) { $rows += [pscustomobject]@{ seed = $seed; n200 = 0; hit200 = 0.0; exp200 = 0.0; n125 = 0; hit125 = 0.0; exp125 = 0.0; n300 = 0; hit300 = 0.0; exp300 = 0.0; vn = 0; vexp = 0.0 }; continue }
  $lines = @(Get-Content $f -Encoding Unicode)
  $startIdx = -1
  for ($i = 0; $i -lt $lines.Count; $i++) { if ($lines[$i] -match 'tester backtest on SYN75 M5 starting') { $startIdx = $i } }
  if ($startIdx -ge 0) { $lines = @($lines[$startIdx..($lines.Count - 1)]) }
  $d125 = $null; $d200 = $null; $d300 = $null; $vhi = $null
  foreach ($ln in $lines) {
    $m = [regex]::Match($ln, "depth <= ([\d.]+):\s+n=\s*(\d+)\s+hit=([\d.]+)%\s+exp=${NumTok}R")
    if ($m.Success) {
      $c = [pscustomobject]@{ cap = [double]$m.Groups[1].Value; n = [long]$m.Groups[2].Value; hit = [double]$m.Groups[3].Value; exp = [double]$m.Groups[4].Value }
      if ($c.cap -eq 1.25) { $d125 = $c } elseif ($c.cap -eq 2.00) { $d200 = $c } elseif ($c.cap -eq 3.00) { $d300 = $c }
    }
    $mv = [regex]::Match($ln, "vol(<=1\.25|>1\.25)\s+n=\s*(\d+)\s+hit=\s*([\d.]+)%\s+exp=${NumTok}R")
    if ($mv.Success -and $mv.Groups[1].Value -eq '>1.25') {
      $vhi = [pscustomobject]@{ n = [long]$mv.Groups[2].Value; exp = [double]$mv.Groups[4].Value }
    }
  }
  $rows += [pscustomobject]@{
    seed = $seed
    n125 = if ($d125) { $d125.n } else { 0 }; hit125 = if ($d125) { $d125.hit } else { 0.0 }; exp125 = if ($d125) { $d125.exp } else { 0.0 }
    n200 = if ($d200) { $d200.n } else { 0 }; hit200 = if ($d200) { $d200.hit } else { 0.0 }; exp200 = if ($d200) { $d200.exp } else { 0.0 }
    n300 = if ($d300) { $d300.n } else { 0 }; hit300 = if ($d300) { $d300.hit } else { 0.0 }; exp300 = if ($d300) { $d300.exp } else { 0.0 }
    vn = if ($vhi) { $vhi.n } else { 0 }; vexp = if ($vhi) { $vhi.exp } else { 0.0 }
  }
}

Write-Host ''
Write-Host ('{0,5} | {1,7} | {2,7} | {3,7}' -f 'seed', '<=1.25', '<=2.00', '<=3.00')
foreach ($r in $rows) {
  Write-Host ('{0,5} | {1,3}n {2,5}% {3,7}R | {4,3}n {5,5}% {6,7}R | {7,3}n {8,5}% {9,7}R' -f `
    $r.seed, $r.n125, ('{0:0.0}' -f $r.hit125), ('{0:+0.000;-0.000}' -f $r.exp125), `
    $r.n200, ('{0:0.0}' -f $r.hit200), ('{0:+0.000;-0.000}' -f $r.exp200), `
    $r.n300, ('{0:0.0}' -f $r.hit300), ('{0:+0.000;-0.000}' -f $r.exp300))
}
$hits = @($rows | ForEach-Object { $_.hit200 }); $exps = @($rows | ForEach-Object { $_.exp200 }); $ns = @($rows | ForEach-Object { $_.n200 })
$hMin = ($hits | Measure-Object -Minimum).Minimum; $hMax = ($hits | Measure-Object -Maximum).Maximum; $hAvg = ($hits | Measure-Object -Average).Average
$eMin = ($exps | Measure-Object -Minimum).Minimum; $eMax = ($exps | Measure-Object -Maximum).Maximum; $eAvg = ($exps | Measure-Object -Average).Average
$nMin = ($ns | Measure-Object -Minimum).Minimum; $nMax = ($ns | Measure-Object -Maximum).Maximum
Write-Host ''
Write-Host ('cap-2.0 hit : min={0:0.0}% max={1:0.0}% mean={2:0.0}% spread={3:0.0}pp' -f $hMin, $hMax, $hAvg, ($hMax - $hMin))
Write-Host ('cap-2.0 exp : min={0:+0.000;-0.000}R max={1:+0.000;-0.000}R mean={2:+0.000;-0.000}R spread={3:+0.000;-0.000}R' -f $eMin, $eMax, $eAvg, ($eMax - $eMin))
Write-Host ('cap-2.0 n   : min={0} max={1} mean={2:0.0}' -f $nMin, $nMax, ($ns | Measure-Object -Average).Average)
