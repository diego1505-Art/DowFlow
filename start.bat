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

REM -- Dependances Python : verifier et mettre a jour a chaque lancement --
echo Verification des dependances Python...
set "DOWFLOW_DEPS_FAILED=0"
"%VENV_DIR%\Scripts\python.exe" -m pip install -q -r requirements.txt
if errorlevel 1 (
    set "DOWFLOW_DEPS_FAILED=1"
)
"%VENV_DIR%\Scripts\python.exe" -m pip install -q -U yt-dlp
if errorlevel 1 (
    set "DOWFLOW_DEPS_FAILED=1"
)
if "!DOWFLOW_DEPS_FAILED!"=="1" (
    echo [ATTENTION] La verification des dependances Python a echoue.
)

REM -- Playwright / Chromium : verifier a chaque lancement ----------------
python -c "from playwright.sync_api import sync_playwright as s; p=s().start(); b=p.chromium.launch(headless=True); b.close(); p.stop()" 1>nul 2>nul
if errorlevel 1 (
    echo [INFO] Playwright Chromium manquant ou corrompu.
    echo [INFO] Tentative d'installation rapide...
    echo [INFO] Si cela prend trop de temps, vous pouvez fermer cette fenetre.
    python -m playwright install chromium
    if errorlevel 1 (
        echo [ATTENTION] L'installation de Playwright a echoue. 
        echo [ATTENTION] Les telechargements Franime pourraient ne pas fonctionner.
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

color 0C
echo.
echo [DOWFLOW] Initialisation...
for %%A in (1 2 3) do (
    <nul set /p "=."
    >nul ping 127.0.0.1 -n 2
)
echo.
python startup.py
pause
