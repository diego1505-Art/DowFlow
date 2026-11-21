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

:menu
cls
echo.
echo   ==============================================
echo    DOWFLOW - BUILD
echo   ==============================================
echo.
echo    1  Whole menu          dist\DowFlow.exe
echo    2  Video               dist\DowFlow-Video.exe
echo    3  Music               dist\DowFlow-Music.exe
echo    4  Movies / Series     dist\DowFlow-Films.exe
echo    5  Anime               dist\DowFlow-Anime.exe
echo    0  Quit
echo.
set "CHOICE="
set /p "CHOICE=Choice [0-5]: "
if not defined CHOICE goto :menu

set "SCOPE="
set "DEFAULT_NAME="
if "%CHOICE%"=="1" set "SCOPE=all" & set "DEFAULT_NAME=DowFlow"
if "%CHOICE%"=="2" set "SCOPE=video" & set "DEFAULT_NAME=DowFlow-Video"
if "%CHOICE%"=="3" set "SCOPE=music" & set "DEFAULT_NAME=DowFlow-Music"
if "%CHOICE%"=="4" set "SCOPE=film" & set "DEFAULT_NAME=DowFlow-Films"
if "%CHOICE%"=="5" set "SCOPE=anime" & set "DEFAULT_NAME=DowFlow-Anime"
if "%CHOICE%"=="0" goto :done
if not defined SCOPE goto :menu

:build_scope
echo.
echo Building the "%SCOPE%" edition.
echo Close DowFlow first: the executable embeds the current database.
echo.
set "NAME="
set /p "NAME=Executable name [%DEFAULT_NAME%]: "
if not defined NAME set "NAME=%DEFAULT_NAME%"

"%PYTHON%" -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installing the build requirements...
    "%PYTHON%" -m pip install --disable-pip-version-check -q -r requirements-build.txt
    if errorlevel 1 goto :failed
)

"%PYTHON%" build_export.py %SCOPE% "%NAME%"
if errorlevel 1 goto :failed

echo.
if exist "dist\%NAME%.exe" (
    echo [OK] "%CD%\dist\%NAME%.exe"
) else (
    echo [OK] dist\%NAME%.exe
)
echo.
pause
goto :menu

:failed
echo.
echo [ERROR] The build failed. Check the messages above.
echo.
pause
goto :menu

:done
endlocal
exit /b 0
