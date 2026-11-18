@echo off
rem Starts The Grand Project in your web browser. First time: run "Install (run once).bat".
rem It runs in the background; File > Quit the app on the page stops it.
cd /d "%~dp0"
where pyw >nul 2>nul && (start "" pyw -m grand_project & exit /b)
where pythonw >nul 2>nul && (start "" pythonw -m grand_project & exit /b)
python -m grand_project
if errorlevel 1 pause
