@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" -m jobs.daily_job %*
