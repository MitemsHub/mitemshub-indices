# watch-v2614-today.ps1 — show v26.14 EA activity since reattach (~11:40) from all terminals
$logDate = (Get-Date).ToString("yyyyMMdd")
Get-ChildItem "$env:APPDATA\MetaQuotes\Terminal" -Directory | ForEach-Object {
    $log = Join-Path $_.FullName "MQL5\Logs\$logDate.log"
    if (Test-Path $log) {
        $hits = Select-String -Path $log -Pattern "MitemshubAI" |
            Where-Object { $_.Line -match "\t(11:(4[0-9]|5[0-9])|1[2-9]:[0-9]{2}|2[0-3]:[0-9]{2}):" }
        if ($hits) {
            Write-Host ("=== " + $_.Name + " (" + $hits.Count + " lines since 11:40) ===")
            $hits | ForEach-Object { Write-Host $_.Line }
        }
    }
}
