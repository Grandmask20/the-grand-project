@echo off
rem Runs the tests with pytest (several minutes; the viewer test opens a window).
cd /d "%~dp0.."
py -m pytest -m "not slow"
pause
