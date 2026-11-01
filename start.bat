@echo off
chcp 65001 >nul 2>&1
title DowFlow - Media Downloader
cd /d "%~dp0"
setlocal EnableExtensions EnableDelayedExpansion

REM Relance apres mise a jour : on saute directement a la suite.
if /i "%~1"=="--updated" goto :after_update

set "DOWFLOW_GITHUB_REPO=https://github.com/diego1505-Art/DowFlow-V13.git"
where git >nul 2>&1
if errorlevel 1 (
    echo [ATTENTION] Git est indisponible : mise a jour du projet ignoree.
    goto :after_update
) else (
    echo Verification des mises a jour GitHub...
    for /f %%H in ('git rev-parse HEAD') do set "DOWFLOW_OLD_HEAD=%%H"
    git fetch "%DOWFLOW_GITHUB_REPO%" main --quiet
    if errorlevel 1 (
        echo [ATTENTION] Impossible de contacter GitHub : mise a jour ignoree.
        goto :after_update
    ) else (
        set "DOWFLOW_STASHED=0"
        git diff --quiet HEAD
        if errorlevel 1 (
            echo Modifications locales detectees : sauvegarde temporaire avant mise a jour...
            git stash push -m "DowFlow auto-update"
            if errorlevel 1 (
                echo [ATTENTION] Sauvegarde locale impossible : mise a jour ignoree.
                goto :after_update
            ) else (
                set "DOWFLOW_STASHED=1"
            )
        )

        git merge --ff-only FETCH_HEAD
        if errorlevel 1 (
            echo [ATTENTION] Mise a jour GitHub impossible. Les fichiers locaux sont conserves.
            if "!DOWFLOW_STASHED!"=="1" git stash pop
            goto :after_update
        )

        if "!DOWFLOW_STASHED!"=="1" (
            git stash pop
            if errorlevel 1 (
                echo [ATTENTION] Conflit pendant la restauration des changements locaux.
                echo [ATTENTION] Le stash reste disponible avec : git stash list
            )
        )
        echo Projet a jour.
    )
)

for /f %%H in ('git rev-parse HEAD') do set "DOWFLOW_NEW_HEAD=%%H"
if "!DOWFLOW_OLD_HEAD!"=="!DOWFLOW_NEW_HEAD!" goto :after_update

REM Relance le script : sa version a pu changer pendant la mise a jour.
del /q "%~dp0.venv\deps_ok.flag" >nul 2>&1
endlocal & call "%~f0" --updated & exit /b

:after_update

REM -- Venv ---------------------------------------------------------------
REM Chemin absolu recalcule a chaque lancement : le venv reste valide meme si
REM le dossier du projet est renomme/deplace (sinon activation cassee -> Python
REM systeme + yt-dlp trop ancien -> erreurs HTTP 403 sur YouTube).
set "VENV_DIR=%~dp0.venv"
if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo Creation du venv...
    python -m venv "%VENV_DIR%"
)
set "VIRTUAL_ENV=%VENV_DIR%"
set "PATH=%VENV_DIR%\Scripts;%PATH%"
set "DOWFLOW_WARN=0"

REM -- Dependances et Playwright : verification une fois par jour ---------
set "DOWFLOW_DEPS_FLAG=%VENV_DIR%\deps_ok.flag"
set "DOWFLOW_DEPS_FRESH=0"
if exist "%DOWFLOW_DEPS_FLAG%" (
    forfiles /p "%VENV_DIR%" /m deps_ok.flag /d 0 /c "cmd /c exit 0" >nul 2>&1
    if not errorlevel 1 set "DOWFLOW_DEPS_FRESH=1"
)

if "!DOWFLOW_DEPS_FRESH!"=="0" (
    echo Verification quotidienne des dependances...
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
        echo [INFO] Playwright Chromium manquant ou corrompu.
        python -m playwright install chromium
        if errorlevel 1 set "DOWFLOW_DEPS_FAILED=1"
    )

    if "!DOWFLOW_DEPS_FAILED!"=="0" (
        >"%DOWFLOW_DEPS_FLAG%" echo verification-ok
    ) else (
        set "DOWFLOW_WARN=1"
        echo [ATTENTION] La verification des dependances a echoue.
    )
)

REM -- aria2c : verifier a chaque lancement, pas seulement a la creation --
aria2c --version >nul 2>&1
if errorlevel 1 (
    echo Installation de aria2c...
    winget install aria2.aria2 --silent --accept-package-agreements --accept-source-agreements
    REM Ajouter le chemin winget au PATH pour cette session
    for /d %%D in ("%LOCALAPPDATA%\Microsoft\WinGet\Packages\aria2.aria2*") do (
        for /d %%S in ("%%D\aria2*") do set "PATH=%%S;%PATH%"
    )
)

REM -- FFmpeg -------------------------------------------------------------
for /d %%D in ("%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*") do (
    for /d %%S in ("%%D\ffmpeg-*") do (
        if exist "%%S\bin\ffmpeg.exe" set "PATH=%%S\bin;%PATH%"
    )
)

cls
if "!DOWFLOW_WARN!"=="1" (
    echo [ATTENTION] Le demarrage a rencontre un probleme de dependances.
    echo Consulte logs\dowflow.log ou lance debug.bat.
    echo.
)
python startup.py
if "!DOWFLOW_WARN!"=="1" pause
pause
