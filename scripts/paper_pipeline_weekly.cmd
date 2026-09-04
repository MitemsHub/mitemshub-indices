@echo off
rem Paper-pipeline weekly run — scheduled entry point (Sundays 06:30, after
rem the 06:00 "Mitemshub Weekly Data Refresh" that feeds it fresh bars).
rem %~dp0 = this script's folder, so the paths stay valid if the repo moves.
rem The pipeline itself is read-only: it re-executes the dynamic study tools,
rem reads registered artifacts as-is, and diffs verdicts vs the previous run.
cd /d "%~dp0.."
".venv\Scripts\python.exe" "scripts\paper_pipeline.py" >> "artifacts\v75_replay\paper_pipeline_sched.log" 2>&1
exit /b %errorlevel%
