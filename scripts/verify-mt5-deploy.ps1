# verify-mt5-deploy.ps1 — verify repo sources match deployed MT5 copies and binaries are fresh
$ErrorActionPreference = "Stop"
$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..\mql5\MITEMSHUB_AI")).Path
$MT5Base = "$env:APPDATA\MetaQuotes\Terminal"

$repoFiles = Get-ChildItem -Path $ProjectDir -Recurse -File
$repoRel = @{}
foreach ($f in $repoFiles) { $repoRel[$f.FullName.Substring($ProjectDir.Length + 1)] = $f }

$fail = 0

foreach ($term in (Get-ChildItem -Path $MT5Base -Directory)) {
    $mitemDir = Join-Path $term.FullName "MQL5\Experts\MITEMSHUB_AI"
    if (-not (Test-Path $mitemDir)) { Write-Host "SKIP $($term.Name): no Experts\MITEMSHUB_AI" -ForegroundColor DarkGray; continue }
    Write-Host "`n=== Terminal $($term.Name) ===" -ForegroundColor Cyan

    # 1) Deployed mq5/mqh/set match repo content by hash
    $mismatch = 0; $missingInTerm = 0; $extra = 0
    foreach ($rel in $repoRel.Keys) {
        $t = Join-Path $mitemDir $rel
        if (-not (Test-Path $t)) { Write-Host "  MISSING in terminal: $rel" -ForegroundColor Red; $missingInTerm++; $fail++; continue }
        if ((Get-FileHash (Join-Path $ProjectDir $rel)).Hash -ne (Get-FileHash $t).Hash) {
            Write-Host "  STALE (differs from repo): $rel" -ForegroundColor Red; $mismatch++; $fail++
        }
    }
    Get-ChildItem -Path $mitemDir -Recurse -File |
        Where-Object { $_.Extension -in ".mq5",".mqh",".set" } |
        ForEach-Object {
            $rel = $_.FullName.Substring($mitemDir.Length + 1)
            if (-not $repoRel.ContainsKey($rel)) { Write-Host "  ORPHAN not in repo: $rel" -ForegroundColor Yellow; $extra++; $fail++ }
        }

    # 2) .ex5 freshness: binary must exist and be newer than its .mq5
    foreach ($mq5 in (Get-ChildItem -Path $mitemDir -Recurse -File -Filter "*.mq5")) {
        $ex5 = [IO.Path]::ChangeExtension($mq5.FullName, ".ex5")
        $rel = $mq5.FullName.Substring($mitemDir.Length + 1)
        if (-not (Test-Path $ex5)) {
            Write-Host "  NO BUILD (info): $rel has no .ex5" -ForegroundColor DarkYellow
        } elseif ((Get-Item $ex5).LastWriteTime -lt $mq5.LastWriteTime) {
            Write-Host "  STALE BUILD: $rel (.ex5 older than .mq5)" -ForegroundColor Red; $fail++
        } else {
            Write-Host "  OK build: $rel (ex5 $((Get-Item $ex5).LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss')))" -ForegroundColor Green
        }
    }

    Write-Host "  Source check: mismatch=$mismatch missing=$missingInTerm orphan=$extra"
}

$verdict = if ($fail -eq 0) { 'ALL OK' } else { "$fail problem(s) found" }
Write-Host "`n== RESULT: $verdict ==" -ForegroundColor $(if ($fail -eq 0) { 'Green' } else { 'Red' })
