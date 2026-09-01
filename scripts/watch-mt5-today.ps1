# watch-mt5-today.ps1 — dump today's MitemshubAI lines from every terminal's Experts log
$logDate = (Get-Date).ToString("yyyyMMdd")
Get-ChildItem "$env:APPDATA\MetaQuotes\Terminal" -Directory | ForEach-Object {
    $log = Join-Path $_.FullName "MQL5\Logs\$logDate.log"
    if (Test-Path $log) {
        $hits = Select-String -Path $log -Pattern "MitemshubAI|v26\.14"
        if ($hits) {
            Write-Host ("=== " + $_.Name + " (" + $hits.Count + " lines) ===")
            $hits | ForEach-Object { Write-Host $_.Line }
        }
    }
}
