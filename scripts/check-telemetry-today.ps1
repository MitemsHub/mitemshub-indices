# check-telemetry-today.ps1 — today's telemetry event counts per instance
$today = (Get-Date).ToString("yyyy-MM-dd")
Get-ChildItem "$env:APPDATA\MetaQuotes\Terminal\*\MQL5\Files\MitemshubAI_v23_telemetry_*.jsonl" |
    Sort-Object LastWriteTime -Descending | Select-Object -First 2 | ForEach-Object {
        Write-Host ("=== " + $_.Name + " ===")
        $todayLines = Select-String -Path $_.FullName -Pattern $today
        Write-Host ("today rows: " + $todayLines.Count)
        $todayLines | ForEach-Object { $_.Line } |
            ForEach-Object { if ($_ -match '"(type|event|reason)"\s*:\s*"([^"]+)"') { $Matches[2] } } |
            Group-Object | Sort-Object Count -Descending |
            ForEach-Object { Write-Host ("  " + $_.Name + ": " + $_.Count) }
        Write-Host "-- last 3 rows --"
        $todayLines | Select-Object -Last 3 | ForEach-Object { Write-Host $_.Line }
    }
