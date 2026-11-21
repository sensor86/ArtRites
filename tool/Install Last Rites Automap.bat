@echo off
rem ===========================================================================
rem  Last Rites - Live Automap  —  INSTALLER
rem
rem  Run this ONCE from wherever you unzipped the release. It finds your Last
rem  Rites game folder, copies the "LastRitesAutomap" folder into it (next to
rem  dosbox.exe), and can put a "Last Rites (with map)" shortcut on your Desktop.
rem
rem  You can also drag your game folder onto this file to skip the search.
rem ===========================================================================
setlocal enabledelayedexpansion
title Last Rites Automap - Installer
cd /d "%~dp0"

echo ============================================================
echo   Last Rites (1997)  -  Live Automap  -  Installer
echo ============================================================
echo.
echo This copies the "LastRitesAutomap" folder into your game folder
echo (the one that contains dosbox.exe) and optionally adds a Desktop
echo shortcut. Your existing game and saves are never touched.
echo.

rem --- 1) drag-and-drop the game folder onto this window --------------------
set "GAME="
if not "%~1"=="" (
    if exist "%~1\dosbox.exe"    set "GAME=%~1"
    if exist "%~1\DOSBox.exe"    set "GAME=%~1"
    if exist "%~1\dosbox-x.exe"  set "GAME=%~1"
    if defined GAME echo Using the folder you provided: !GAME!
)

rem --- 2) common GOG / Steam locations ---------------------------------------
if not defined GAME for %%D in (
    "%ProgramFiles(x86)%\GOG Galaxy\Games\Last Rites"
    "%ProgramFiles(x86)%\GOG Games\Last Rites"
    "%ProgramFiles%\GOG Galaxy\Games\Last Rites"
    "%ProgramFiles%\GOG Games\Last Rites"
    "C:\GOG Games\Last Rites"
    "D:\GOG Games\Last Rites"
    "D:\Games\Last Rites"
    "E:\GOG Games\Last Rites"
    "E:\Games\Last Rites"
    "%ProgramFiles(x86)%\Steam\steamapps\common\Last Rites"
    "%ProgramFiles%\Steam\steamapps\common\Last Rites"
) do (
    if not defined GAME (
        if exist "%%~D\dosbox.exe"    set "GAME=%%~D"
        if exist "%%~D\DOSBox.exe"    set "GAME=%%~D"
        if exist "%%~D\dosbox-x.exe"  set "GAME=%%~D"
    )
)

rem --- 3) ask -----------------------------------------------------------------
if not defined GAME (
    echo I could not find the game automatically.
    echo Drag your Last Rites folder onto this window, or type/paste its full
    echo path below ^(the folder that contains dosbox.exe^):
    echo.
    set /p "GAME=Path: "
)
if not defined GAME (
    echo Nothing entered - aborting.
    pause
    exit /b 1
)
if not exist "!GAME!\dosbox.exe" (
    if not exist "!GAME!\DOSBox.exe" (
        if not exist "!GAME!\dosbox-x.exe" (
            echo.
            echo That folder does not contain dosbox.exe - aborting.
            pause
            exit /b 1
        )
    )
)

echo.
echo Game folder: !GAME!
echo.

rem --- source must be present --------------------------------------------------
set "SRC=%~dp0LastRitesAutomap"
if not exist "!SRC!" (
    echo The "LastRitesAutomap" folder was not found next to this installer.
    echo Unzip the WHOLE release first ^(keep this file and that folder together^).
    pause
    exit /b 1
)

rem --- copy --------------------------------------------------------------------
if exist "!GAME!\LastRitesAutomap" (
    echo A "LastRitesAutomap" folder already exists there.
    set /p "OW=Overwrite it? ^(your map notes/pins are NOT touched^) [y/N]: "
    if /i not "!OW!"=="y" (
        echo Keeping the existing copy.
        goto :shortcut
    )
)

echo Copying files...
xcopy "!SRC!" "!GAME!\LastRitesAutomap\" /E /I /Y /Q >nul
if errorlevel 1 (
    echo.
    echo Copy FAILED. Is the game folder writable?
    pause
    exit /b 1
)
echo Copied.

rem --- desktop shortcut ----------------------------------------------------------
:shortcut
set /p "SC=Create a Desktop shortcut 'Last Rites (with map)'? [Y/n]: "
if /i "!SC!"=="n" goto :done

set "LR_TARGET=!GAME!\LastRitesAutomap\Play Last Rites with Automap.bat"
set "LR_WORKDIR=!GAME!\LastRitesAutomap"
powershell -NoProfile -Command "$ErrorActionPreference='SilentlyContinue'; $d=[Environment]::GetFolderPath('Desktop'); $ws=New-Object -ComObject WScript.Shell; $s=$ws.CreateShortcut((Join-Path $d 'Last Rites (with map).lnk')); $s.TargetPath=$env:LR_TARGET; $s.WorkingDirectory=$env:LR_WORKDIR; $s.Description='Play Last Rites with the live automap'; $s.Save()"

:done
echo.
echo ============================================================
echo   Done! To play with the map, run
echo     "Play Last Rites with Automap.bat"
echo   inside  !GAME!\LastRitesAutomap
echo   (or use the Desktop shortcut, if you made one).
echo.
echo   First time: the map window opens first and says
echo   "Waiting for a running level" - then start a mission and
echo   it attaches by itself. Press O to toggle map panel/window.
echo ============================================================
echo.
pause
endlocal
