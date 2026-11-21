@echo off
chcp 65001 >nul 2>&1
title DowFlow - Build
cd /d "%~dp0"
setlocal EnableExtensions EnableDelayedExpansion

set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

"%PYTHON%" --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Run start.bat once to create the .venv folder.
    pause
    exit /b 1
)

"%PYTHON%" build_ui.py
if errorlevel 1 (
    echo.
    echo [ERROR] The build launcher stopped unexpectedly.
    pause
)

endlocal
exit /b 0
