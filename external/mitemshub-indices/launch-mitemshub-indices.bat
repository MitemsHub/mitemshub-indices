@echo off
set SCRIPT_DIR=%~dp0
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%launch-mitemshub-indices.ps1"
if errorlevel 1 pause
