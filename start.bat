@echo off
chcp 65001 >nul 2>&1
title DowFlow - Media Downloader
cd /d "%~dp0"
setlocal EnableExtensions

REM DowFlow Music keeps its own entry point (start.bat music).
if /i "%~1"=="music" goto :open_liner

REM The launcher creates the virtual environment, updates the project, starts
REM the server and keeps its logs in this same console window.
set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"
"%PYTHON%" "%~dp0launcher.py" %*
if errorlevel 1 (
    echo.
    echo [ERROR] DowFlow stopped with an error. Review the messages above.
    echo.
    pause
)
endlocal
exit /b

REM -- Music: open the Liner desktop app --------------------------------------
:open_liner
setlocal EnableExtensions
set "LINER_DIR=%~dp0desktop\liner"
echo [DowFlow] Opening DowFlow Music (Liner)...
if not exist "%LINER_DIR%\package.json" (
    echo [ERROR] Liner folder not found: "%LINER_DIR%"
    pause
    exit /b 1
)
set "LINER_EXE=%LINER_DIR%\release\win-unpacked\dowflow-music.exe"
if exist "%LINER_EXE%" (
    start "" "%LINER_EXE%"
    exit /b 0
)
where pnpm >nul 2>&1
if errorlevel 1 (
    echo [ERROR] pnpm is required to start DowFlow Music from source.
    pause
    exit /b 1
)
if not exist "%LINER_DIR%\node_modules" (
    echo [INFO] Installing DowFlow Music dependencies...
    call pnpm --dir "%LINER_DIR%" install --frozen-lockfile
    if errorlevel 1 goto :liner_failed
)
if not exist "%LINER_DIR%\dist-electron\main.js" (
    echo [INFO] Building DowFlow Music...
    call pnpm --dir "%LINER_DIR%" build
    if errorlevel 1 goto :liner_failed
)
start "" /d "%LINER_DIR%" cmd /c "pnpm exec electron ."
exit /b 0

:liner_failed
echo [ERROR] DowFlow Music could not be prepared. Run it once by hand to see the details.
pause
exit /b 1
