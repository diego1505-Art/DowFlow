@echo off
chcp 65001 >nul 2>&1
title DowFlow Debug Center
cd /d "%~dp0"
setlocal EnableExtensions EnableDelayedExpansion
color 0C

set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"
"%PYTHON%" --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo [ERREUR] Python introuvable dans le PATH.
    echo Installe Python et coche "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

echo.
echo [DOWFLOW] Lancement du centre de diagnostic...
for %%A in (1 2 3) do (
    <nul set /p "=."
    >nul ping 127.0.0.1 -n 2
)
echo.

REM FFmpeg / aria2 au PATH (meme logique que start.bat)
for /d %%D in ("%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*") do (
    for /d %%S in ("%%D\ffmpeg-*") do (
        if exist "%%S\bin\ffmpeg.exe" set "PATH=%%S\bin;%PATH%"
    )
)
for /d %%D in ("%LOCALAPPDATA%\Microsoft\WinGet\Packages\aria2.aria2*") do (
    for /d %%S in ("%%D\aria2*") do (
        if exist "%%S\aria2c.exe" set "PATH=%%S;%PATH%"
    )
)

"%PYTHON%" "%~dp0tools\debug_center.py"
set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" (
    echo.
    echo [ERREUR] tools\debug_center.py a quitte avec le code %ERR%.
    pause
)
exit /b %ERR%
