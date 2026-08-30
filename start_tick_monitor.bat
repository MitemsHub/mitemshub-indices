@echo off
rem MITEMSHUB live Boom-1000 tick monitor launcher (run from YOUR session so
rem it survives; processes spawned by the coding agent get reaped).
cd /d "C:\Users\USER\Desktop\Projects\Synthetic Indices Bot"
start "MITEMSHUB Tick Monitor" /MIN cmd /c ".venv\Scripts\python.exe -u scripts\live_tick_monitor.py >> artifacts\live_monitor.log 2>&1"
echo Monitor started minimized. Live log: artifacts\live_monitor.log
timeout /t 2 >nul
