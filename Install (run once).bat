@echo off
rem Installs the Python packages the app needs (Python 3.11+ from python.org must be installed).
cd /d "%~dp0"
where py >nul 2>nul && (py -m pip install -r requirements.txt) || (python -m pip install -r requirements.txt)
rem A shortcut with the tablet icon (a .bat can't have its own icon); it stores this folder's full path, so it is
rem made here rather than shipped. Minimized: no console window flashes when it starts the app.
set "GP=%~dp0"
powershell -NoProfile -Command "$d=$env:GP; $s=(New-Object -ComObject WScript.Shell).CreateShortcut($d+'The Grand Project.lnk'); $s.TargetPath=$d+'Start The Grand Project.bat'; $s.WorkingDirectory=$d; $s.IconLocation=$d+'references\the_grand_project.ico'; $s.WindowStyle=7; $s.Description='Start The Grand Project'; $s.Save()" >nul 2>nul
echo.
if exist "The Grand Project.lnk" (
    echo Done. Now double-click "The Grand Project" ^(the shortcut with the tablet icon^), or "Start The Grand Project.bat".
    echo You can copy the shortcut to your desktop or pin it to Start.
) else (
    echo Done. Now double-click "Start The Grand Project.bat".
)
pause
