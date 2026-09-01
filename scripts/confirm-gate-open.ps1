# confirm-gate-open.ps1 — after reattach, verify: fresh init lines + gate OPEN + no cblearn block
$logDate = (Get-Date).ToString("yyyyMMdd")
$liveLog = "$env:APPDATA\MetaQuotes\Terminal\FB9A56D617EDDDFE29EE54EBEFFE96C1\MQL5\Logs\$logDate.log"
Write-Host ("log: " + $liveLog)
$hits = Select-String -Path $liveLog -Pattern "MITEMSHUB AI v26\.14 started|CB-SPIKE LEARNING restored|CB-SPIKE GATE|GATE re-evaluated|TICKFADE\] armed|BLOCKED"
$hits | Select-Object -Last 14 | ForEach-Object { Write-Host ($_.Line -replace "`r","") }
Write-Host ""
$cb = Get-ChildItem "$env:APPDATA\MetaQuotes\Terminal\FB9A56D617EDDDFE29EE54EBEFFE96C1\MQL5\Files\MitemshubAI_cblearn_*.csv" -ErrorAction SilentlyContinue
if ($cb) { $cb | ForEach-Object { Write-Host ($_.Name + ": " + (Get-Content $_.FullName -Raw)) } }
else { Write-Host "cblearn: no state files yet (fresh gate, OPEN until first trades)" }
