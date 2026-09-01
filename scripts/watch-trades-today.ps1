# watch-trades-today.ps1 — today's trade-relevant lines (entries/exits/skips/summaries) per terminal
$logDate = (Get-Date).ToString("yyyyMMdd")
$pattern = "BUY |SELL |CLOSE |TAKE PROFIT|STOP |FINAL|FADE-ENTRY|FADE-FILL|FADE-SKIP|CB-SKIP|ORDER|Equity|New day|HALT|reject"
Get-ChildItem "$env:APPDATA\MetaQuotes\Terminal\*\MQL5\Logs\$logDate.log" | ForEach-Object {
    $hits = Select-String -Path $_.FullName -Pattern $pattern | Where-Object { $_.Line -match "MitemshubAI" }
    if ($hits) {
        Write-Host ("=== " + $_.FullName.Split('\')[5] + " (" + $hits.Count + " lines) ===")
        $hits | ForEach-Object { Write-Host ($_.Line -replace "`r","") }
    }
}
