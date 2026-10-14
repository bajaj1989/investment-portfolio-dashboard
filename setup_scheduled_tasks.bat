@echo off
cd /d "%~dp0"
set JOB=%~dp0run_job.bat

echo Creating scheduled tasks for the portfolio dashboard...
schtasks /create /f /tn "PortfolioDashboard\Daily" /sc daily /st 07:00 /tr "\"%JOB%\" daily"
schtasks /create /f /tn "PortfolioDashboard\AtLogon" /sc onlogon /delay 0005:00 /tr "\"%JOB%\" daily"
schtasks /create /f /tn "PortfolioDashboard\CryptoHourly" /sc hourly /mo 1 /tr "\"%JOB%\" crypto"

echo.
echo Done. To remove them later run:  schtasks /delete /tn "PortfolioDashboard\Daily" /f  (and the same for AtLogon, CryptoHourly)
pause
