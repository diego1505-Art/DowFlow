@echo off
chcp 65001 >nul 2>&1
title DowFlow - Media Downloader
cd /d "%~dp0"
setlocal EnableExtensions EnableDelayedExpansion

REM Restart after update: skip directly to the setup phase.
if /i "%~1"=="--updated" goto :after_update

set "DOWFLOW_GITHUB_REPO=https://github.com/diego1505-Art/DowFlow.git"
where git >nul 2>&1
if errorlevel 1 (
    echo [WARNING] Git is unavailable: project update skipped.
    goto :after_update
) else (
    echo Checking GitHub updates...
    for /f %%H in ('git rev-parse HEAD') do set "DOWFLOW_OLD_HEAD=%%H"
    powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\git_fetch_animation.ps1" -Repository "%DOWFLOW_GITHUB_REPO%" -Branch main -ProjectRoot "%CD%"
    if errorlevel 1 (
        echo [WARNING] Unable to contact GitHub: project update skipped.
        goto :after_update
    ) else (
        set "DOWFLOW_REMOTE_HEAD="
        for /f %%H in ('git rev-parse FETCH_HEAD') do set "DOWFLOW_REMOTE_HEAD=%%H"
        if /i "!DOWFLOW_OLD_HEAD!"=="!DOWFLOW_REMOTE_HEAD!" (
            echo Project is up to date.
            goto :after_update
        )

        set "DOWFLOW_UPDATE_AUTHOR=Unknown"
        set "DOWFLOW_UPDATE_SUBJECT=New project update"
        for /f "tokens=1,*" %%A in ('git show -s --format^=fuller FETCH_HEAD') do (
            if "%%A"=="Author:" set "DOWFLOW_UPDATE_AUTHOR=%%B"
            if "%%A"=="Subject:" set "DOWFLOW_UPDATE_SUBJECT=%%B"
        )
        echo.
        echo A new project update is available on GitHub:
        echo Repository: %DOWFLOW_GITHUB_REPO%
        echo Commit: !DOWFLOW_REMOTE_HEAD:~0,7!
        echo Published by: !DOWFLOW_UPDATE_AUTHOR!
        echo Changes: !DOWFLOW_UPDATE_SUBJECT!
        choice /c YN /n /m "Would you like to download and install this update? [Y/N] "
        if errorlevel 2 (
            echo Project update skipped. Dependencies will still be checked.
            goto :after_update
        )

        set "DOWFLOW_STASHED=0"
        git diff --quiet HEAD
        if errorlevel 1 (
            echo Local changes detected: temporarily saving tracked changes...
            git stash push -m "DowFlow auto-update"
            if errorlevel 1 (
                echo [WARNING] Unable to save local changes: project update skipped.
                goto :after_update
            ) else (
                set "DOWFLOW_STASHED=1"
            )
        )

        git merge --ff-only FETCH_HEAD
        if errorlevel 1 (
            echo [WARNING] GitHub update failed. Local files are preserved.
            if "!DOWFLOW_STASHED!"=="1" git stash pop
            goto :after_update
        )

        if "!DOWFLOW_STASHED!"=="1" (
            git stash pop
            if errorlevel 1 (
                echo [WARNING] Conflict while restoring local changes.
                echo [WARNING] The stash is still available with: git stash list
            )
        )
        echo Project update applied.
    )
)

for /f %%H in ('git rev-parse HEAD') do set "DOWFLOW_NEW_HEAD=%%H"
if "!DOWFLOW_OLD_HEAD!"=="!DOWFLOW_NEW_HEAD!" goto :after_update

REM Restart the script: its version may have changed during the update.
del /q "%~dp0.venv\deps_ok.flag" >nul 2>&1
endlocal & call "%~f0" --updated & exit /b

:after_update

REM -- Venv ---------------------------------------------------------------
REM Recalculate the absolute path at each launch so the venv remains valid if
REM the project folder is renamed or moved (otherwise system Python and an older
REM yt-dlp may cause HTTP 403 errors on YouTube).
set "VENV_DIR=%~dp0.venv"
set "DOWFLOW_WARN=0"
if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv "%VENV_DIR%"
    if errorlevel 1 set "DOWFLOW_WARN=1"
)
set "VIRTUAL_ENV=%VENV_DIR%"
set "PATH=%VENV_DIR%\Scripts;%PATH%"

REM -- Dependencies and Playwright: check once per day -------------------
set "DOWFLOW_DEPS_FLAG=%VENV_DIR%\deps_ok.flag"
set "DOWFLOW_DEPS_FRESH=0"
if exist "%DOWFLOW_DEPS_FLAG%" (
    forfiles /p "%VENV_DIR%" /m deps_ok.flag /d 0 /c "cmd /c exit 0" >nul 2>&1
    if not errorlevel 1 set "DOWFLOW_DEPS_FRESH=1"
)

if "!DOWFLOW_DEPS_FRESH!"=="0" (
    echo Daily dependency check...
    set "DOWFLOW_DEPS_FAILED=0"
    "%VENV_DIR%\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
    if errorlevel 1 (
        set "DOWFLOW_DEPS_FAILED=1"
    )
    "%VENV_DIR%\Scripts\python.exe" -m pip install --disable-pip-version-check -q -U yt-dlp
    if errorlevel 1 (
        set "DOWFLOW_DEPS_FAILED=1"
    )

    python -c "from playwright.sync_api import sync_playwright as s; p=s().start(); b=p.chromium.launch(headless=True); b.close(); p.stop()" 1>nul 2>nul
    if errorlevel 1 (
        echo [INFO] Playwright Chromium is missing or corrupted.
        python -m playwright install chromium
        if errorlevel 1 set "DOWFLOW_DEPS_FAILED=1"
    )

    if "!DOWFLOW_DEPS_FAILED!"=="0" (
        >"%DOWFLOW_DEPS_FLAG%" echo verification-ok
    ) else (
        set "DOWFLOW_WARN=1"
        echo [WARNING] Dependency verification failed.
    )
)

REM -- aria2c: check every launch, not only after installation -------------
aria2c --version >nul 2>&1
if errorlevel 1 (
    echo Installing aria2c...
    winget install aria2.aria2 --silent --accept-package-agreements --accept-source-agreements
    REM Add the WinGet path to PATH for this session.
    for /d %%D in ("%LOCALAPPDATA%\Microsoft\WinGet\Packages\aria2.aria2*") do (
        for /d %%S in ("%%D\aria2*") do set "PATH=%%S;%PATH%"
    )
    aria2c --version >nul 2>&1
    if errorlevel 1 set "DOWFLOW_WARN=1"
)

REM -- FFmpeg -------------------------------------------------------------
for /d %%D in ("%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*") do (
    for /d %%S in ("%%D\ffmpeg-*") do (
        if exist "%%S\bin\ffmpeg.exe" set "PATH=%%S\bin;%PATH%"
    )
)

cls
if "!DOWFLOW_WARN!"=="1" (
    echo [WARNING] Startup encountered a dependency problem.
    echo Check logs\dowflow.log or run debug.bat.
    echo.
)
python startup.py
pause
