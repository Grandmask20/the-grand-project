@echo off
rem Opens the Atlas Viewer. First time: run "Install (run once).bat".
cd /d "%~dp0program"
where pyw >nul 2>nul && (start "" pyw atlas_viewer.py & exit /b)
where pythonw >nul 2>nul && (start "" pythonw atlas_viewer.py & exit /b)
python atlas_viewer.py
if errorlevel 1 pause
