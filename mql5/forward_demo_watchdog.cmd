@echo off
rem Forward-demo journal watchdog — scheduled entry point (every 15 min).
rem %~dp0 = this script's folder, so the paths stay valid if the repo moves.
"C:\Python314\python.exe" "%~dp0forward_demo_watchdog.py" >> "%~dp0..\.freebuff\forward_demo_watchdog_sched.log" 2>&1
exit /b %errorlevel%
