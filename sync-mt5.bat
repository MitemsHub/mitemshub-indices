@echo off
echo.
echo ========================================
echo   Syncing MQL5 files to MT5 terminal...
echo ========================================
echo.
powershell -ExecutionPolicy Bypass -File "%~dp0scripts\sync-mt5.ps1"
echo.
pause
