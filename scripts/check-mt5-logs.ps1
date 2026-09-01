# check-mt5-logs.ps1 — show today's Experts-log lines for MitemshubAI in every terminal
$logDate = (Get-Date).ToString("yyyyMMdd")
Get-ChildItem "$env:APPDATA\MetaQuotes\Terminal" -Directory | ForEach-Object {
    $log = Join-Path $_.FullName "MQL5\Logs\$logDate.log"
    if (Test-Path $log) {
        $hits = Select-String -Path $log -Pattern "MitemshubAI|initialized|failed|error" | Select-Object -Last 8
        if ($hits) {
            Write-Host ("=== " + $_.Name + " ===")
            $hits | ForEach-Object { Write-Host $_.Line }
        }
    }
}
