@echo off
cd /d "%~dp0"
echo Starting portfolio dashboard... (close this window to stop it)
".venv\Scripts\python.exe" -m streamlit run app.py
pause
