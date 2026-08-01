@echo off
rem ===========================================================================
rem  Last Rites - Live Automap  (community add-on)
rem  Put this LastRitesAutomap folder inside your Last Rites game folder
rem  (the folder that contains dosbox.exe), then double-click this file.
rem  It starts the game AND the live map. The map finds the game by itself.
rem ===========================================================================
setlocal
cd /d "%~dp0"

rem --- locate the game's DOSBox (one level up, the usual GOG/Steam layout) ---
set "DOSBOX="
if exist "%~dp0..\dosbox.exe"     set "DOSBOX=%~dp0..\dosbox.exe"
if exist "%~dp0..\DOSBox.exe"     set "DOSBOX=%~dp0..\DOSBox.exe"
if exist "%~dp0..\dosbox-x.exe"   set "DOSBOX=%~dp0..\dosbox-x.exe"

rem  IMPORTANT: DOSBox must start with the GAME folder as its working directory,
rem  otherwise it does not pick up dosbox.conf (whose [autoexec] mounts and
rem  starts Last Rites) and you get an empty DOS prompt.
rem  automap_window.conf (loaded last, so it wins) forces a desktop-sized WINDOW:
rem  in exclusive fullscreen no overlay can appear above the game at all.
if defined DOSBOX (
    if exist "%~dp0..\dosbox.conf" (
        if exist "%~dp0automap_window.conf" (
            start "" /d "%~dp0.." "%DOSBOX%" -conf dosbox.conf -conf "%~dp0automap_window.conf"
        ) else (
            start "" /d "%~dp0.." "%DOSBOX%" -conf dosbox.conf
        )
    ) else (
        start "" /d "%~dp0.." "%DOSBOX%"
    )
) else (
    echo [note] dosbox.exe not found next to this folder.
    echo        Start Last Rites yourself, the map will still attach.
)

rem --- launch the map (prefer standalone exe, fall back to Python script) ---
if exist "%~dp0LastRitesAutomap.exe" (
    start "" "%~dp0LastRitesAutomap.exe"
    goto :eof
)

rem --- no exe found: try Python ---
set "PY="
where pythonw >nul 2>&1 && set "PY=pythonw"
if not defined PY ( where python >nul 2>&1 && set "PY=python" )
if not defined PY ( where py >nul 2>&1 && set "PY=py" )

if not defined PY (
    echo.
    echo  Python 3 is required for the map and was not found.
    echo  Install it from https://www.python.org/downloads/  (tick "Add to PATH"),
    echo  then run this file again.  The game will keep running regardless.
    echo.
    pause
    exit /b
)

start "" %PY% "%~dp0automap.py"
endlocal
