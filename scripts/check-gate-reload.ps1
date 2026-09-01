# check-gate-reload.ps1 — look for EA re-init / gate re-evaluation lines after 12:35 today
$logDate = (Get-Date).ToString("yyyyMMdd")
Get-ChildItem "$env:APPDATA\MetaQuotes\Terminal\*\MQL5\Logs\$logDate.log" | ForEach-Object {
    $hits = Select-String -Path $_.FullName -Pattern "CB-SPIKE GATE|v26\.14\] MITEMSHUB AI v26\.14 started|GATE re-evaluated|LEARNING restored" |
        Where-Object { $_.Line -match "\t(1[2-9]:[0-9]{2}|2[0-3]:[0-9]{2}):" }
    if ($hits) {
        Write-Host ("=== " + $_.FullName.Split('\')[5] + " ===")
        $hits | ForEach-Object { Write-Host ($_.Line -replace "`r","") }
    }
}
