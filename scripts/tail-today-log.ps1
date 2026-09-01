# tail-today-log.ps1 — current time + last 40 lines of the most recently written Experts log
Write-Host ("NOW: " + (Get-Date).ToString("yyyy-MM-dd HH:mm:ss"))
$logDate = (Get-Date).ToString("yyyyMMdd")
$latest = Get-ChildItem "$env:APPDATA\MetaQuotes\Terminal\*\MQL5\Logs\$logDate.log" |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
Write-Host ("LOG: " + $latest.FullName + " (last write " + $latest.LastWriteTime.ToString("HH:mm:ss") + ")`n")
Get-Content $latest.FullName -Tail 40
