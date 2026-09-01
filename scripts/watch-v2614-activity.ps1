# watch-v2614-activity.ps1 — v26.14 trade activity since reattach (entries/closes/skips/events)
$logDate = (Get-Date).ToString("yyyyMMdd")
$pattern = "MitemshubAI|TickRecorder"
$events  = "BUY|SELL|CLOSE|ORDER|TAKE|STOP OUT|FILL|ENTRY|FADE-ENTRY|CB-SKIP|SPIKE #|TICKSPIKE|TICKFADE|HALT|FINAL|error|fail|reject|Reject|Equity|New day|POSITION|TELEMETRY|DECISION|SKIP"
Get-ChildItem "$env:APPDATA\MetaQuotes\Terminal" -Directory | ForEach-Object {
    $log = Join-Path $_.FullName "MQL5\Logs\$logDate.log"
    if (Test-Path $log) {
        $hits = Select-String -Path $log -Pattern $pattern |
            Where-Object { $_.Line -match "\t(1[2-9]:[0-9]{2}|2[0-3]:[0-9]{2}):" -and $_.Line -match $events }
        if ($hits) {
            Write-Host ("=== " + $_.Name + " (" + $hits.Count + " activity lines since 12:00) ===")
            $hits | ForEach-Object { Write-Host $_.Line }
        }
    }
}
