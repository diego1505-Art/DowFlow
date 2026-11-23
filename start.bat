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
set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"
echo [DowFlow] Opening DowFlow Music (Liner)...
"%PYTHON%" "%~dp0launcher.py" --music
if errorlevel 1 (
    echo.
    echo [ERROR] DowFlow Music could not be started. Read the messages above.
    echo.
    pause
)
endlocal
exit /b 0
