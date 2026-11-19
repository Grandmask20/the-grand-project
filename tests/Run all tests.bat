@echo off
rem Runs the tests with pytest (a few minutes).
cd /d "%~dp0.."
py -m pytest -m "not slow"
pause
