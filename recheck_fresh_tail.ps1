# recheck_fresh_tail.ps1 — R_100 fresh-tail verdict vs the 2026-08-16 four-leg matrix
#
# After the live tick collector was restarted (2026-08-17 14:18 UTC, ending the
# 17.75h collector-down gap), the corpus tail is "fresh" — ticks appended by the
# new collector only.  This script re-runs the corpus analysis + four-leg
# head-to-head on THAT tail and compares every traded leg's expectancy sign
# against the documented P10 matrix (band −0.591R / fade −0.198R / momentum
# −0.019R / sniper −0.029R, all negative on realistic costs).
#
# Exit codes (consumed by Task Scheduler Last Result and the operator):
#   0 = AGREE      — every traded leg's sign matches the matrix
#   1 = DISAGREE   — at least one traded leg flipped non-negative (matrix stale
#                    or the fresh edge changed materially — same rule as the
#                    P10-A R_100 four-leg sign-lock)
#   2 = INSUFFICIENT — no leg traded yet on the tail (keep collecting)
#   3 = ERROR      — no corpus / python missing / parse failure
#
# Re-runnable any day: `powershell -File recheck_fresh_tail.ps1` (or
# `schtasks /Run` on the registered FreshTailR100Recheck task).
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$appDir = $scriptDir
$corpus = Join-Path $appDir "data\backfill\R_100_ticks.csv"
$tailCsv = Join-Path $appDir "data\backfill\R_100_tail_fresh.csv"
$artifact = Join-Path $appDir "artifacts\fresh_tail_verdict_r100.json"
$taskLog = Join-Path $appDir ".data\fresh_tail_recheck.log"

# First fresh-tail tick epoch: 2026-08-17 14:18:28 UTC (collector restarted,
# ending the 17.75h gap).  Ticks >= this cutoff are "fresh" by construction;
# the cutoff is fixed so the tail GROWS with each passing day instead of
# re-anchoring to whatever the current largest gap happens to be.
$TailCutoffEpoch = 1786969000.0

function Write-TaskLog([string]$msg) {
  try {
    Add-Content -Path $taskLog -Value ("{0:HH:mm:ss} {1}" -f (Get-Date), $msg) -Encoding UTF8
  } catch { }
  Write-Host $msg
}

function Get-PythonRunner {
  if (Get-Command python -ErrorAction SilentlyContinue) { return "python" }
  if (Get-Command py -ErrorAction SilentlyContinue) { return "py" }
  return $null
}

function New-TailCsv {
  param([string]$Csv, [string]$Out, [double]$Cutoff)
  # Extract every tick with epoch >= cutoff, keeping epoch,price — the two
  # columns backtest-vol needs.  Returns the number of tail rows.
  $lines = [System.IO.File]::ReadAllLines($Csv)
  $sb = New-Object System.Text.StringBuilder
  [void]$sb.AppendLine("epoch,price")
  $count = 0
  for ($i = 1; $i -lt $lines.Length; $i++) {
    $parts = $lines[$i].Split(",")
    if ($parts.Length -lt 2) { continue }
    $e = 0.0
    if (-not [double]::TryParse($parts[0], [ref]$e)) { continue }
    if ($e -lt $Cutoff) { continue }
    [void]$sb.AppendLine(("{0},{1}" -f $parts[0], $parts[2]))
    $count++
  }
  [System.IO.File]::WriteAllText($Out, $sb.ToString(), [System.Text.Encoding]::ASCII)
  return $count
}

function Invoke-CorpusAnalysis {
  param([string]$TailCsv)
  # M5 bucket density of the tail: distinct floor(epoch/300) buckets vs span.
  $lines = [System.IO.File]::ReadAllLines($TailCsv)
  if ($lines.Length -lt 2) { return @{ rows = 0; span_h = 0.0; buckets = 0; expected = 0; density = 0.0; first = 0.0; last = 0.0 } }
  $buckets = @{}
  $first = [double]::MaxValue
  $last = [double]::MinValue
  for ($i = 1; $i -lt $lines.Length; $i++) {
    $parts = $lines[$i].Split(",")
    if ($parts.Length -lt 2) { continue }
    $e = [double]$parts[0]
    if ($e -lt $first) { $first = $e }
    if ($e -gt $last)  { $last = $e }
    $b = [math]::Floor($e / 300.0)
    $buckets[$b] = $true
  }
  $spanS = $last - $first
  $expected = [math]::Floor($spanS / 300.0) + 1
  $density = if ($expected -gt 0) { [math]::Round($buckets.Count / $expected, 3) } else { 0.0 }
  return @{
    rows = $lines.Length - 1
    span_h = [math]::Round($spanS / 3600.0, 2)
    buckets = $buckets.Count
    expected = $expected
    density = $density
    first = $first
    last = $last
  }
}

$python = Get-PythonRunner
if (-not $python) {
  Write-TaskLog "[FRESH-TAIL] verdict=ERROR reason=python-not-found"
  exit 3
}
if (-not (Test-Path $corpus)) {
  Write-TaskLog "[FRESH-TAIL] verdict=ERROR reason=corpus-missing $corpus"
  exit 3
}

New-Item -ItemType Directory -Force -Path (Split-Path $artifact) | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path $taskLog) | Out-Null

$rows = New-TailCsv -Csv $corpus -Out $tailCsv -Cutoff $TailCutoffEpoch
Write-TaskLog "fresh tail extracted: $rows rows -> $tailCsv"
if ($rows -lt 60) {
  Write-TaskLog "[FRESH-TAIL] verdict=INSUFFICIENT reason=tail-too-thin rows=$rows"
  exit 2
}
$ana = Invoke-CorpusAnalysis -TailCsv $tailCsv
Write-TaskLog ("tail span_h={0} buckets={1}/{2} density={3}" -f $ana.span_h, $ana.buckets, $ana.expected, $ana.density)

# Four-leg head-to-head on the tail, same basis as the P10 matrix
# (--symbol R_100 --timeframe 300 --compare, realistic costs default).
$out = & $python -m synthetic_trader.cli backtest-vol `
  --mode band --symbol R_100 --timeframe 300 --compare `
  --csv $tailCsv 2>&1 | Out-String
$exit = $LASTEXITCODE
if ($exit -ne 0) {
  Write-TaskLog "[FRESH-TAIL] verdict=ERROR reason=backtest-exit-$exit $out"
  exit 3
}

# Parse each leg's block (same block grammar as verify_all.ps1's
# Invoke-R100FourLegReference): strategy=N starts a block, then trades=N /
# expectancy_r=N lines fill it.
$legs = [ordered]@{ band = $null; "vol-reversion" = $null; "vol-momentum" = $null; sniper = $null }
$cur = ""
foreach ($line in ($out -split "`r?`n")) {
  $sm = [regex]::Match($line, '^strategy=(\S+)')
  if ($sm.Success) {
    $cur = $sm.Groups[1].Value
    if ($legs.Contains($cur)) { $legs[$cur] = @{ trades = 0; exp = 0.0; seen = $false } }
    continue
  }
  if ($cur -eq "" -or -not $legs.Contains($cur)) { continue }
  $tm = [regex]::Match($line, '^trades=(\d+)')
  if ($tm.Success) { $legs[$cur].trades = [int]$tm.Groups[1].Value; continue }
  $em = [regex]::Match($line, '^expectancy_r=([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)')
  if ($em.Success) { $legs[$cur].exp = [double]$em.Groups[1].Value; $legs[$cur].seen = $true }
}

# Reference signs from the documented P10 matrix (all four legs NEGATIVE).
$ref = @{ band = -0.591; "vol-reversion" = -0.198; "vol-momentum" = -0.019; sniper = -0.029 }
$traded = @()
$flips = @()
foreach ($name in $legs.Keys) {
  $leg = $legs[$name]
  if ($null -eq $leg -or -not $leg.seen) {
    Write-TaskLog "[FRESH-TAIL] ERROR: leg '$name' missing/unparseable in head-to-head output"
    exit 3
  }
  if ($leg.trades -le 0) { continue }  # a 0-trade leg cannot prove a flip
  $traded += $name
  $neg = $leg.exp -lt 0.0
  if (-not $neg) { $flips += ("{0}:{1:+0.000;-0.000;+0.000}R" -f $name, $leg.exp) }
}

$legSum = (($legs.Keys | ForEach-Object {
  $l = $legs[$_]
  "{0}={1}:{2:+0.000;-0.000;+0.000}R" -f $_, $l.trades, $l.exp
}) -join "|")

if ($flips.Count -gt 0) {
  $detail = "fresh-tail sign FLIP on traded leg(s) $($flips -join ', ') vs matrix (all four legs negative) - re-baseline deliberately"
  Write-TaskLog "[FRESH-TAIL] verdict=DISAGREE trades=$($traded -join ',') $legSum tail_span_h=$($ana.span_h) density=$($ana.density)"
  Write-TaskLog "    detail: $detail"
  @{ verdict = "DISAGREE"; detail = $detail; tail_span_h = $ana.span_h; density = $ana.density;
     legs = $legs; traded = $traded; flips = $flips; generated_utc = (Get-Date).ToUniversalTime().ToString("o") } |
    ConvertTo-Json -Depth 4 | Set-Content -Path $artifact -Encoding UTF8
  exit 1
}

if ($traded.Count -eq 0) {
  Write-TaskLog "[FRESH-TAIL] verdict=INSUFFICIENT trades=none $legSum tail_span_h=$($ana.span_h) density=$($ana.density) - keep collecting"
  @{ verdict = "INSUFFICIENT"; detail = "no leg traded on the fresh tail yet";
     tail_span_h = $ana.span_h; density = $ana.density; legs = $legs;
     generated_utc = (Get-Date).ToUniversalTime().ToString("o") } |
    ConvertTo-Json -Depth 4 | Set-Content -Path $artifact -Encoding UTF8
  exit 2
}

$detail = "fresh-tail traded leg(s) $($traded -join ', ') all NEGATIVE - agrees with the 2026-08-16 four-leg matrix (band -0.591R / fade -0.198R / momentum -0.019R / sniper -0.029R)"
Write-TaskLog "[FRESH-TAIL] verdict=AGREE trades=$($traded -join ',') $legSum tail_span_h=$($ana.span_h) density=$($ana.density)"
Write-TaskLog "    detail: $detail"
@{ verdict = "AGREE"; detail = $detail; tail_span_h = $ana.span_h; density = $ana.density;
   legs = $legs; traded = $traded; flips = @(); generated_utc = (Get-Date).ToUniversalTime().ToString("o") } |
  ConvertTo-Json -Depth 4 | Set-Content -Path $artifact -Encoding UTF8
exit 0
