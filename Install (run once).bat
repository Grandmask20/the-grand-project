@echo off
rem Installs the Python packages the viewer needs (Python 3.11+ from python.org must be installed).
cd /d "%~dp0"
where py >nul 2>nul && (py -m pip install -r requirements.txt) || (python -m pip install -r requirements.txt)
echo.
echo Done. Now double-click "Start Atlas Viewer.bat".
pause
