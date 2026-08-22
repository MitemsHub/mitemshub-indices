# MITEMSHUB AI — Nightly Optimizer Setup
# Creates a Windows scheduled task to run the optimizer every night at 3:00 AM
# Usage: Run as Administrator

$TaskName = "MITEMSHUB_NightlyOptimizer"
$TaskDescription = "MITEMSHUB AI Nightly Strategy Optimization - Retrains the trading strategy on fresh data"
$ScriptPath = "$PSScriptRoot\..\src\nightly_optimizer.py"
$PythonPath = "python"
$WorkingDir = "$PSScriptRoot\..\src"

# Check if task already exists
$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existingTask) {
    Write-Host "[INFO] Task '$TaskName' already exists. Removing..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Create the action
$Action = New-ScheduledTaskAction `
    -Execute $PythonPath `
    -Argument $ScriptPath `
    -WorkingDirectory $WorkingDir

# Create trigger: Every day at 3:00 AM
$Trigger = New-ScheduledTaskTrigger `
    -Daily `
    -At "3:00AM"

# Create settings
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5)

# Register the task
$Principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Highest

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description $TaskDescription

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  MITEMSHUB AI Nightly Optimizer Setup" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Task Name:    $TaskName"
Write-Host "  Schedule:     Daily at 3:00 AM"
Write-Host "  Script:       $ScriptPath"
Write-Host "  Working Dir:  $WorkingDir"
Write-Host ""
Write-Host "  What it does:" -ForegroundColor Cyan
Write-Host "    1. Pulls latest 30 days of M5 data from Deriv MT5"
Write-Host "    2. Tests 3,000+ parameter combinations"
Write-Host "    3. Saves optimal params to data/optimal_params.json"
Write-Host "    4. Updates .set file in Deriv terminal"
Write-Host "    5. Logs results to data/optimizer_logs/"
Write-Host ""
Write-Host "  To run manually:" -ForegroundColor Yellow
Write-Host "    Start-ScheduledTask -TaskName '$TaskName'"
Write-Host ""
Write-Host "  To check status:" -ForegroundColor Yellow
Write-Host "    Get-ScheduledTask -TaskName '$TaskName' | Format-List"
Write-Host ""
Write-Host "  To disable:" -ForegroundColor Yellow
Write-Host "    Disable-ScheduledTask -TaskName '$TaskName'"
Write-Host ""
Write-Host "============================================" -ForegroundColor Green
