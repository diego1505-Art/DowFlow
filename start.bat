@echo off
chcp 65001 >nul 2>&1
title DowFlow - Media Downloader
cd /d "%~dp0"
setlocal EnableExtensions EnableDelayedExpansion

REM ── Mise a jour du projet depuis GitHub ──────────────────────────────────
set "DOWFLOW_GITHUB_REPO=https://github.com/diego1505-Art/DowFlow-V13.git"
where git >nul 2>&1
if errorlevel 1 (
    echo [ATTENTION] Git est indisponible : mise a jour du projet ignoree.
) else (
    echo Verification des mises a jour GitHub : %DOWFLOW_GITHUB_REPO%
    git fetch "%DOWFLOW_GITHUB_REPO%" main --quiet
    if errorlevel 1 (
        echo [ATTENTION] Impossible de contacter GitHub : mise a jour ignoree.
    ) else (
        set "DOWFLOW_STASHED=0"
        set "DOWFLOW_CAN_UPDATE=1"
        git status --porcelain | findstr /r /c:"." >nul
        if not errorlevel 1 (
            echo Modifications locales detectees : sauvegarde temporaire avant mise a jour...
            git stash push -m "DowFlow auto-update"
            if errorlevel 1 (
                set "DOWFLOW_CAN_UPDATE=0"
                echo [ATTENTION] Sauvegarde locale impossible : mise a jour ignoree.
            ) else (
                set "DOWFLOW_STASHED=1"
            )
        )
        if "!DOWFLOW_CAN_UPDATE!"=="1" (
            git merge --ff-only FETCH_HEAD
            if errorlevel 1 (
                echo [ATTENTION] Mise a jour GitHub impossible. Les fichiers locaux sont conserves.
                if "!DOWFLOW_STASHED!"=="1" git stash pop
            ) else (
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
    )
)

REM ── Venv ────────────────────────────────────────────────────────────────
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

REM ── Dependances Python : verifier et mettre a jour a chaque lancement ────
echo Verification des dependances Python...
"%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade -r requirements.txt
if errorlevel 1 (
    echo [ATTENTION] La mise a jour des dependances Python a echoue.
)

REM ── Playwright / Chromium : verifier a chaque lancement ──────────────────
python -c "from playwright.sync_api import sync_playwright as s; p=s().start(); b=p.chromium.launch(headless=True); b.close(); p.stop()" 1>nul 2>nul
if errorlevel 1 (
    echo [INFO] Playwright Chromium manquant ou corrompu.
    echo [INFO] Tentative d'installation rapide...
    echo [INFO] Si cela prend trop de temps, vous pouvez fermer cette fenêtre.
    python -m playwright install chromium
    if errorlevel 1 (
        echo [ATTENTION] L'installation de Playwright a echoue. 
        echo [ATTENTION] Les telechargements Franime pourraient ne pas fonctionner.
    )
)

REM ── aria2c : verifier a chaque lancement, pas seulement a la creation ──
aria2c --version >nul 2>&1
if errorlevel 1 (
    echo Installation de aria2c...
    winget install aria2.aria2 --silent --accept-package-agreements --accept-source-agreements
    REM Ajouter le chemin winget au PATH pour cette session
    for /d %%D in ("%LOCALAPPDATA%\Microsoft\WinGet\Packages\aria2.aria2*") do (
        for /d %%S in ("%%D\aria2*") do set "PATH=%%S;%PATH%"
    )
)

REM ── FFmpeg ───────────────────────────────────────────────────────────────
for /d %%D in ("%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*") do (
    for /d %%S in ("%%D\ffmpeg-*") do (
        if exist "%%S\bin\ffmpeg.exe" set "PATH=%%S\bin;%PATH%"
    )
)

python -c "import rich" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installation de Rich pour l'ecran de demarrage...
    python -m pip install "rich>=13.7.1,<16"
)
python startup.py
pause
