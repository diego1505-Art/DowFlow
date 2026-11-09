@echo off
setlocal
cd /d "%~dp0"
set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

"%PYTHON%" -m PyInstaller --noconfirm --clean launcher.spec
if errorlevel 1 (
    echo [ERROR] Unable to build DowFlow-Launcher.exe
    exit /b 1
)

echo [OK] dist\DowFlow-Launcher.exe created.
endlocal
