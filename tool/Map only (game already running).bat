@echo off
rem Starts ONLY the live map (use if Last Rites is already running).
setlocal
cd /d "%~dp0"
set "PY="
where pythonw >nul 2>&1 && set "PY=pythonw"
if not defined PY ( where python >nul 2>&1 && set "PY=python" )
if not defined PY ( where py >nul 2>&1 && set "PY=py" )
if not defined PY (
    echo Python 3 required - https://www.python.org/downloads/  (tick "Add to PATH")
    pause & exit /b
)
start "" %PY% "%~dp0automap.py"
endlocal
