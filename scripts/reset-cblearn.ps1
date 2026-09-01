# reset-cblearn.ps1 — back up then delete MitemshubAI_cblearn_*.csv (gate resets to OPEN on next init)
$backup = Join-Path $PSScriptRoot "..\.data\cblearn_backup_$(Get-Date -Format yyyyMMdd_HHmmss)"
New-Item -ItemType Directory -Path $backup -Force | Out-Null
Get-ChildItem "$env:APPDATA\MetaQuotes\Terminal\*\MQL5\Files\MitemshubAI_cblearn_*.csv" | ForEach-Object {
    Copy-Item $_.FullName $backup -Force
    Remove-Item $_.FullName -Force
    Write-Host ("reset: " + $_.FullName)
}
Write-Host ("backup dir: " + $backup)
