@echo off
set SCRIPT_DIR=%~dp0
echo [Launcher] Starting MitemsHub Indices...

powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%launch-mitemshub-indices.ps1"
if %errorlevel% neq 0 (
  echo [Launcher] Failed with exit code %errorlevel%. Press any key to close.
  pause > nul
)
