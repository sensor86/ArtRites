@echo off
rem ===========================================================================
rem  Last Rites - Live Automap  —  MAP ONLY
rem  Use this when Last Rites is ALREADY running (started without the launcher).
rem  Prefers the self-contained .exe, falls back to Python if you run from source.
rem ===========================================================================
setlocal
cd /d "%~dp0"

if exist "%~dp0LastRitesAutomap.exe" (
    start "" "%~dp0LastRitesAutomap.exe"
    goto :eof
)

set "PY="
where pythonw >nul 2>&1 && set "PY=pythonw"
if not defined PY ( where python >nul 2>&1 && set "PY=python" )
if not defined PY ( where py >nul 2>&1 && set "PY=py" )
if not defined PY (
    echo Python 3 required - https://www.python.org/downloads/  (tick "Add to PATH")
    echo or use the standalone .exe release of this mod instead.
    pause & exit /b 1
)
start "" %PY% "%~dp0automap.py"
endlocal
