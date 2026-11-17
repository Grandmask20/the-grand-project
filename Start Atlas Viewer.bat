@echo off
rem Opens The Grand Project. First time: run "Install (run once).bat".
cd /d "%~dp0"
where pyw >nul 2>nul && (start "" pyw -m grand_project & exit /b)
where pythonw >nul 2>nul && (start "" pythonw -m grand_project & exit /b)
python -m grand_project
if errorlevel 1 pause
