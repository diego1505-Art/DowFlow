"""Build a scoped DowFlow onedir application and its Windows installer.

Each scope produces ``build/out/<Edition>/`` (the PyInstaller one-directory
output) and, with ``installer=True``, ``%USERPROFILE%/Downloads/<Edition>-Setup.exe``,
the Windows Downloads folder unless another output directory is given.

No one-file executable is produced anymore: the installer copies the folder
once into ``%LOCALAPPDATA%\\DowFlow``, so launching DowFlow never extracts
hundreds of megabytes into ``%TEMP%``.
"""
from __future__ import annotations

import argparse
from collections import deque
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from config import SUBPROCESS_CREATION_FLAGS

EXPORT_SCOPES = {"all", "video", "music", "film", "anime"}


def default_output_dir() -> Path:
    """Drop the finished installer straight into the Windows Downloads folder."""
    profile = Path(os.environ.get("USERPROFILE") or Path.home())
    downloads = profile / "Downloads"
    return downloads if downloads.is_dir() else profile


# One entry per build.bat choice. ``dest`` is relative to
# %LOCALAPPDATA%\DowFlow and keeps every edition in its own folder while the
# data/ folder stays shared.
EDITIONS: dict[str, dict[str, Any]] = {
    "all": {
        "name": "DowFlow",
        "dest": "menu",
        "setup": "DowFlow-Setup",
        "app_name": "DowFlow",
        "app_id": "DowFlow.Menu",
        # Downloading the whole menu has to bring everything: the setup also
        # installs the DowFlow Music (Liner) app in submenus\music, which is
        # what the Music card opens.
        "bundles_music": True,
    },
    "video": {
        "name": "DowFlow-Video",
        "dest": r"submenus\video",
        "setup": "DowFlow-Video-Setup",
        "app_name": "DowFlow Video",
        "app_id": "DowFlow.Video",
    },
    "music": {
        "name": "DowFlow-Music",
        "dest": r"submenus\music",
        "setup": "DowFlow-Music-Setup",
        "app_name": "DowFlow Music",
        "app_id": "DowFlow.Music",
        # The Music edition is the Liner desktop application: it plays, searches
        # and downloads music on its own, so this edition ships neither the
        # Python backend nor the media tools.
        "liner": True,
        "app_exe": "dowflow-music.exe",
    },
    "film": {
        "name": "DowFlow-Films",
        "dest": r"submenus\films",
        "setup": "DowFlow-Films-Setup",
        "app_name": "DowFlow Films",
        "app_id": "DowFlow.Films",
    },
    "anime": {
        "name": "DowFlow-Anime",
        "dest": r"submenus\anime",
        "setup": "DowFlow-Anime-Setup",
        "app_name": "DowFlow Anime",
        "app_id": "DowFlow.Anime",
    },
}

# A setup must never carry this machine's runtime state: the database, the
# configuration, exported cookies, logs, downloaded tools and browser profiles
# belong in %LOCALAPPDATA%\DowFlow\data, never in a packaged app folder.
_USER_DATA_ENTRIES = (
    "dowflow.db",
    "dowflow.db-wal",
    "dowflow.db-shm",
    "config.json",
    "youtube_cookies.txt",
    "youtube.com_cookies.txt",
    "cookies.txt",
    "logs",
    "bin",
    "browser_profile",
    "portable_data",
)


def strip_user_data(folder: Path) -> list[str]:
    """Delete the runtime files a local run left inside an app folder.

    Running a built edition from its output folder makes it create its database,
    configuration and logs beside the executable, and Inno Setup copies the
    whole folder: without this the next setup would carry them.
    """
    removed: list[str] = []
    if not folder.is_dir():
        return removed
    for name in _USER_DATA_ENTRIES:
        target = folder / name
        try:
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
            else:
                continue
        except OSError:
            continue
        removed.append(name)
    return removed


def music_backend_is_reusable(root: Path, blank: bool) -> bool:
    """True when the Music backend of an earlier build can be packaged as is.

    A blank build never reuses one: that folder may hold data left by a manual
    run, and a release must not ship it.
    """
    if blank:
        return False
    backend = root / "build" / "out" / "DowFlow-Music" / "DowFlow-Music.exe"
    return backend.is_file()


WEBVIEW2_BOOTSTRAPPER_URL = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
WEBVIEW2_BOOTSTRAPPER_NAME = "MicrosoftEdgeWebview2Setup.exe"
_INVALID_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


# The overlay of the app plus its media tools takes the build to 86 %, and the
# Inno Setup compression afterwards owns the last stretch of the bar: it runs for
# minutes while the setup file is written, so it must not already sit at 99 %.
_INSTALLER_PERCENT_START = 90
_INSTALLER_PERCENT_SPAN = 7
# Input bytes are roughly this many times the compressed setup size. Only used
# until a finished build of the same edition records the exact numbers.
_DEFAULT_INSTALLER_RATIO = 3.5
_AUTO_ETA = object()


def progress_from_log_line(
    line: str,
    current_percent: int,
    analysis_events: int,
) -> tuple[int, str, int]:
    message = line.lower()
    if "checking analysis" in message:
        return max(current_percent, 4), "Scanning dependencies", analysis_events
    if "building analysis" in message:
        return max(current_percent, 8), "Analyzing application", analysis_events
    if "processing standard module hook" in message or message.startswith("info: analyzing "):
        analysis_events += 1
        percent = min(38, 8 + analysis_events // 2)
        return max(current_percent, percent), "Analyzing application", analysis_events
    if "looking for dynamic libraries" in message:
        return max(current_percent, 40), "Collecting runtime libraries", analysis_events
    if "building pyz" in message:
        return max(current_percent, 46), "Compressing Python modules", analysis_events
    if "building pkg" in message:
        return max(current_percent, 62), "Packing application files", analysis_events
    if "building exe" in message:
        return max(current_percent, 74), "Creating executable", analysis_events
    if "building collect" in message:
        return max(current_percent, 82), "Assembling application folder", analysis_events
    if "completed successfully" in message:
        return max(current_percent, 86), "Finalizing application folder", analysis_events
    return current_percent, "Building executable", analysis_events


def sanitize_exe_name(value: str) -> str:
    name = Path(value).stem.strip()
    name = _INVALID_NAME.sub("_", name).strip(" .")
    if not name or name.upper() in _WINDOWS_RESERVED:
        raise ValueError("Choose a valid Windows executable name.")
    return name[:100]


def _find_iscc() -> str:
    candidates = [
        os.environ.get("ISCC"),
        shutil.which("iscc"),
        os.environ.get("LOCALAPPDATA", "") and str(
            Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Inno Setup 6" / "ISCC.exe"
        ),
        os.environ.get("ProgramFiles(x86)", "") and str(
            Path(os.environ["ProgramFiles(x86)"]) / "Inno Setup 6" / "ISCC.exe"
        ),
        os.environ.get("ProgramFiles", "") and str(
            Path(os.environ["ProgramFiles"]) / "Inno Setup 6" / "ISCC.exe"
        ),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    raise RuntimeError(
        "Inno Setup 6 (ISCC.exe) was not found. Install it from "
        "https://jrsoftware.org/isdl.php, then run the build again."
    )


def prepare_tools(
    project_root: Path | None = None,
    force: bool = False,
    progress_callback: Callable[[int, str], None] | None = None,
) -> Path:
    """Download and cache FFmpeg, Node, Chromium and WebView2 in build/tools."""
    root = (project_root or Path(__file__).resolve().parent).resolve()
    tools_dir = root / "build" / "tools"
    if force and tools_dir.exists():
        shutil.rmtree(tools_dir)
    ffmpeg_dir = tools_dir / "ffmpeg"
    node_dir = tools_dir / "node"
    chromium_dir = tools_dir / "chromium"
    webview2_dir = tools_dir / "webview2"
    for folder in (ffmpeg_dir, node_dir, chromium_dir, webview2_dir):
        folder.mkdir(parents=True, exist_ok=True)

    def report(percent: int, stage: str) -> None:
        if progress_callback is not None:
            progress_callback(percent, stage)

    from bootstrap import (
        _install_chromium,
        _install_ffmpeg,
        _install_playwright_node,
        _read_url,
    )

    ffmpeg_ready = all(
        (ffmpeg_dir / name).is_file() for name in ("ffmpeg.exe", "ffprobe.exe")
    )
    if not ffmpeg_ready:
        report(5, "Downloading FFmpeg")
        _install_ffmpeg(
            ffmpeg_dir,
            lambda value: report(5 + value * 30 // 100, "Downloading FFmpeg"),
        )

    node_ready = (node_dir / "node.exe").is_file()
    if not node_ready:
        report(38, "Downloading Node.js")
        _install_playwright_node(
            node_dir,
            lambda value: report(38 + value * 12 // 100, "Downloading Node.js"),
        )

    chromium_ready = any(chromium_dir.rglob("chrome.exe"))
    if not chromium_ready:
        report(52, "Downloading Playwright Chromium")
        _install_chromium(
            chromium_dir,
            lambda value: report(52 + value * 38 // 100, "Downloading Playwright Chromium"),
        )

    webview2_path = webview2_dir / WEBVIEW2_BOOTSTRAPPER_NAME
    if not webview2_path.is_file():
        report(92, "Downloading the WebView2 bootstrapper")
        try:
            _read_url(WEBVIEW2_BOOTSTRAPPER_URL, webview2_path)
        except OSError as error:
            print(f"[WARNING] WebView2 bootstrapper unavailable: {error}", file=sys.stderr)

    (tools_dir / ".tools.ready").write_text(
        json.dumps(
            {
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "ffmpeg": True,
                "node": node_ready or (node_dir / "node.exe").is_file(),
                "chromium": chromium_ready or any(chromium_dir.rglob("chrome.exe")),
                "webview2": webview2_path.is_file(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    report(100, "Media tools ready")
    return tools_dir


# Liner's own ``release/`` folder holds the copy people start with
# start.bat music, which may be running while the edition is built: package into
# a separate folder so the build never has to touch loaded files.
_LINER_BUILD_OUTPUT = "release-build"


def liner_app_dir(root: Path) -> Path:
    """Where Electron Builder writes the packaged DowFlow Music (Liner) app."""
    return root / "desktop" / "liner" / _LINER_BUILD_OUTPUT / "win-unpacked"


def liner_release_dir(root: Path) -> Path:
    """Electron Builder's output: the unpacked app and the updater files."""
    return root / "desktop" / "liner" / _LINER_BUILD_OUTPUT


def liner_build_version(liner_root: Path) -> str:
    """A fresh, increasing version for every packaged DowFlow Music build.

    electron-updater only offers an update when the released version is newer
    than the installed one, so the build stamps its date into the patch number
    (``0.2.202611232145`` for 23 November 2026 at 21:45) instead of rewriting
    ``package.json`` on every build.
    """
    try:
        manifest = json.loads(
            (liner_root / "package.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        manifest = {}
    parts = str(manifest.get("version") or "").split(".")
    major = parts[0] if parts and parts[0].isdigit() else "0"
    minor = parts[1] if len(parts) > 1 and parts[1].isdigit() else "0"
    return f"{major}.{minor}.{time.strftime('%Y%m%d%H%M')}"


def _write_liner_update_config(liner_root: Path, app_dir: Path) -> Path | None:
    """Make sure the packaged app knows where to fetch its updates.

    electron-updater reads ``resources/app-update.yml`` and refuses to check
    without it. Electron Builder writes that file from the ``publish`` block
    for installer targets, so this only fills the gap for a ``--dir`` build.
    """
    config = app_dir / "resources" / "app-update.yml"
    if config.is_file():
        return config
    try:
        manifest = json.loads(
            (liner_root / "package.json").read_text(encoding="utf-8")
        )
        publish = (manifest.get("build") or {}).get("publish") or []
        provider = publish[0] if publish else {}
    except (OSError, ValueError, TypeError, IndexError):
        provider = {}
    owner = str(provider.get("owner") or "").strip()
    repo = str(provider.get("repo") or "").strip()
    if str(provider.get("provider") or "") != "github" or not owner or not repo:
        return None
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        f"provider: github\nowner: {owner}\nrepo: {repo}\n", encoding="utf-8"
    )
    return config


def _node_executable(root: Path) -> str:
    bundled = root / "build" / "tools" / "node" / "node.exe"
    if bundled.is_file():
        return str(bundled)
    found = shutil.which("node")
    if found:
        return found
    raise RuntimeError("Node.js is required to package DowFlow Music.")


def newest_mtime(*paths: Path) -> float:
    """Newest modification time among the files and folders given."""
    newest = 0.0
    for path in paths:
        if path.is_file():
            try:
                newest = max(newest, path.stat().st_mtime)
            except OSError:
                continue
        elif path.is_dir():
            for base, _directories, files in os.walk(path):
                for name in files:
                    try:
                        newest = max(newest, (Path(base) / name).stat().st_mtime)
                    except OSError:
                        continue
    return newest


def _liner_toolchain(root: Path, liner_root: Path) -> None:
    """Build the DowFlow Music sources when their output is missing or stale."""
    outputs = (
        liner_root / "dist" / "index.html",
        liner_root / "dist-electron" / "main.js",
    )
    sources = (
        liner_root / "electron",
        liner_root / "src",
        liner_root / "package.json",
    )
    if all(path.is_file() for path in outputs) and newest_mtime(*sources) <= (
        newest_mtime(*outputs)
    ):
        return
    tsc = liner_root / "node_modules" / "typescript" / "bin" / "tsc"
    vite = liner_root / "node_modules" / "vite" / "bin" / "vite.js"
    if not tsc.is_file() or not vite.is_file():
        raise RuntimeError(
            "DowFlow Music is not built and its toolchain is missing; "
            "run pnpm --dir desktop/liner install first."
        )
    node = _node_executable(root)
    for command in ([node, str(tsc), "-b"], [node, str(vite), "build"]):
        completed = subprocess.run(
            command,
            cwd=liner_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=SUBPROCESS_CREATION_FLAGS,
        )
        if completed.returncode:
            detail = (completed.stdout or "") + (completed.stderr or "")
            raise RuntimeError(detail[-5000:] or "DowFlow Music could not be built.")


def build_liner_app(
    project_root: Path | None = None,
    progress_callback: Callable[[int, str], None] | None = None,
) -> Path:
    """Package the Liner desktop application that the Music edition installs."""
    root = (project_root or Path(__file__).resolve().parent).resolve()
    liner_root = root / "desktop" / "liner"
    edition = EDITIONS["music"]
    if not (liner_root / "package.json").is_file():
        raise RuntimeError("The DowFlow Music project is missing from desktop/liner.")
    builder = liner_root / "node_modules" / "electron-builder" / "cli.js"
    if not builder.is_file():
        raise RuntimeError(
            "DowFlow Music dependencies are missing; run "
            "pnpm --dir desktop/liner install first."
        )
    if progress_callback is not None:
        progress_callback(87, "Packaging DowFlow Music")
    _liner_toolchain(root, liner_root)
    # Liner embeds build/out/DowFlow-Music: never package the runtime data a
    # local run of that backend left beside its executable.
    strip_user_data(root / "build" / "out" / "DowFlow-Music")
    version = liner_build_version(liner_root)
    # The NSIS target leaves the unpacked app start.bat opens AND writes the
    # installer plus latest.yml the updater needs; --dir alone produces none of
    # those, so it is only the fallback when NSIS cannot be packaged.
    attempts = (("--win", "--x64"), ("--win", "--dir", "--x64"))
    detail = ""
    for arguments in attempts:
        shutil.rmtree(liner_app_dir(root), ignore_errors=True)
        completed = subprocess.run(
            [
                _node_executable(root),
                str(builder),
                *arguments,
                "--publish",
                "never",
                f"--config.directories.output={_LINER_BUILD_OUTPUT}",
                f"--config.extraMetadata.version={version}",
            ],
            cwd=liner_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=SUBPROCESS_CREATION_FLAGS,
        )
        if completed.returncode == 0:
            break
        detail = (completed.stdout or "") + (completed.stderr or "")
    else:
        raise RuntimeError(detail[-5000:] or "Electron Builder failed.")
    executable = liner_app_dir(root) / str(edition["app_exe"])
    if not executable.is_file():
        raise RuntimeError("Electron Builder completed without creating DowFlow Music.")
    _write_liner_update_config(liner_root, liner_app_dir(root))
    return executable


def _installer_source_dir(root: Path, edition: dict[str, Any]) -> Path:
    if edition.get("liner"):
        return liner_app_dir(root)
    return root / "build" / "out" / str(edition["name"])


def _tree_size(*paths: Path) -> int:
    total = 0
    for path in paths:
        if not path.exists():
            continue
        for base, _directories, files in os.walk(path):
            for name in files:
                try:
                    total += (Path(base) / name).stat().st_size
                except OSError:
                    continue
    return total


def _load_build_history(root: Path) -> dict[str, Any]:
    try:
        history = json.loads(
            (root / "build" / ".export_history.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return {}
    return history if isinstance(history, dict) else {}


def estimate_installer_size(root: Path, scope: str, input_bytes: int) -> int | None:
    """Guess the compressed setup size so the compression shows a percentage."""
    if input_bytes <= 0:
        return None
    measured = _load_build_history(root).get("installer")
    ratios: list[float] = []
    ratio: float | None = None
    if isinstance(measured, dict):
        for key, entry in measured.items():
            if not isinstance(entry, dict):
                continue
            try:
                size = int(entry.get("size") or 0)
                source = int(entry.get("input") or 0)
            except (TypeError, ValueError):
                continue
            if size <= 0 or source <= 0:
                continue
            ratios.append(source / size)
            if key == scope:
                ratio = source / size
    if ratio is None and ratios:
        ratio = sum(ratios) / len(ratios)
    return int(input_bytes / (ratio or _DEFAULT_INSTALLER_RATIO))


def _remember_installer_size(
    root: Path,
    scope: str,
    input_bytes: int,
    setup_size: int,
) -> None:
    history = _load_build_history(root)
    measured = history.get("installer")
    if not isinstance(measured, dict):
        measured = {}
    measured[scope] = {"input": input_bytes, "size": setup_size}
    history["installer"] = measured
    try:
        (root / "build" / ".export_history.json").write_text(
            json.dumps(history, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def _watch_installer(
    staging: Path,
    output_name: str,
    expected_bytes: int | None,
    report: Callable[[int, str, int | None], None] | None,
    stop: threading.Event,
) -> None:
    """Follow the setup Inno Setup writes so the compression shows live numbers."""
    written = 0
    previous_size = 0
    previous_at = time.monotonic()
    speed = 0.0
    while not stop.wait(0.5):
        try:
            size = (staging / output_name).stat().st_size
        except OSError:
            size = previous_size
        now = time.monotonic()
        elapsed = now - previous_at
        if elapsed > 0 and size >= previous_size:
            sample = (size - previous_size) / elapsed / (1024 * 1024)
            speed = sample if speed <= 0 else speed * 0.7 + sample * 0.3
        previous_size, previous_at = size, now
        written = max(written, size)
        if report is None:
            continue
        megabytes = written / (1024 * 1024)
        percent = _INSTALLER_PERCENT_START
        eta_seconds: int | None = None
        if written == 0:
            # Inno Setup inspects every file before it writes the first byte.
            report(percent, "Compression · préparation des fichiers", None)
            continue
        if expected_bytes:
            share = min(1.0, written / expected_bytes)
            percent = _INSTALLER_PERCENT_START + int(_INSTALLER_PERCENT_SPAN * share)
            if speed > 0.05:
                eta_seconds = max(
                    0, int((expected_bytes - written) / (speed * 1024 * 1024))
                )
            stage = (
                f"Compression · {megabytes:.0f}"
                f"/{expected_bytes / (1024 * 1024):.0f} MB · {speed:.1f} MB/s"
            )
        else:
            stage = f"Compression · {megabytes:.0f} MB · {speed:.1f} MB/s"
        report(percent, stage, eta_seconds)


def build_installer(
    scope: str,
    project_root: Path | None = None,
    output_dir: Path | None = None,
    progress_callback: Callable[[int, str, int | None], None] | None = None,
    liner_dir: Path | None = None,
) -> Path:
    """Compress an already-built edition folder with Inno Setup.

    ``liner_dir`` is the packaged DowFlow Music app; passing it makes the
    installer copy it into ``submenus\\music`` next to the edition.
    """
    if scope not in EXPORT_SCOPES:
        raise ValueError("Unsupported export scope.")
    root = (project_root or Path(__file__).resolve().parent).resolve()
    edition = EDITIONS[scope]
    source_dir = _installer_source_dir(root, edition)
    exe_name = str(edition.get("app_exe") or f"{edition['name']}.exe")
    executable = source_dir / exe_name
    if not executable.is_file():
        raise RuntimeError(
            f"The {edition['name']} folder is missing; build the edition first."
        )
    destination = (output_dir or default_output_dir()).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    tools_dir = root / "build" / "tools"
    if not (tools_dir / ".tools.ready").is_file():
        raise RuntimeError("Media tools are missing; run prepare_tools() first.")
    iscc = _find_iscc()
    input_bytes = _tree_size(
        source_dir,
        tools_dir / "ffmpeg",
        tools_dir / "node",
        tools_dir / "chromium",
        tools_dir / "webview2",
    )
    expected_bytes = estimate_installer_size(root, scope, input_bytes)
    # Compile into the build folder and move the finished Setup afterwards, so
    # Downloads never shows a half-written installer.
    staging = root / "build" / "work" / "installer"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    command = [
        iscc,
        f"/DAppName={edition['app_name']}",
        f"/DAppExe={exe_name}",
        f"/DSourceDir={source_dir}",
        f"/DDestDir={edition['dest']}",
        f"/DOutputBase={edition['setup']}",
        f"/DOutputDir={staging}",
        f"/DAppId={edition['app_id']}",
        f"/DToolsDir={tools_dir}",
        f"/DIconFile={root / 'static' / 'dowflow.ico'}",
        str(root / "build" / "installer.iss"),
    ]
    if liner_dir is not None:
        command.insert(-1, f"/DLinerDir={liner_dir}")
    stop = threading.Event()
    watcher: threading.Thread | None = None
    if progress_callback is not None:
        watcher = threading.Thread(
            target=_watch_installer,
            args=(
                staging,
                f"{edition['setup']}.exe",
                expected_bytes,
                progress_callback,
                stop,
            ),
            name="installer-size",
            daemon=True,
        )
        watcher.start()
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=SUBPROCESS_CREATION_FLAGS,
        )
    finally:
        stop.set()
        if watcher is not None:
            watcher.join(timeout=2)
    if completed.returncode:
        detail = (completed.stdout or "") + (completed.stderr or "")
        raise RuntimeError(detail[-5000:] or "Inno Setup failed.")
    staged = staging / f"{edition['setup']}.exe"
    if not staged.is_file():
        raise RuntimeError("Inno Setup completed without creating the installer.")
    setup = destination / f"{edition['setup']}.exe"
    os.replace(staged, setup)
    _remember_installer_size(root, scope, input_bytes, setup.stat().st_size)
    return setup


def build_executable(
    scope: str,
    requested_name: str | None = None,
    project_root: Path | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    *,
    installer: bool = False,
    clean: bool = False,
    blank: bool = False,
    output_dir: Path | None = None,
) -> Path:
    """Build the scope's one-directory app and optionally its installer.

    ``blank`` produces the setup published on the release: nothing from the
    developer's machine is copied (no database, no saved music, no configured
    download root, no cookies), the previous output folder is deleted first so
    no file from an earlier build survives, and PyInstaller starts with a clean
    cache. Every setup, blank or not, is written to the Windows Downloads folder.
    """
    if scope not in EXPORT_SCOPES:
        raise ValueError("Unsupported export scope.")

    root = (project_root or Path(__file__).resolve().parent).resolve()
    name = sanitize_exe_name(requested_name or EDITIONS[scope]["name"])
    dist_dir = root / "build" / "out"
    work_dir = root / "build" / "work" / f"{scope}-{name}"
    if blank:
        clean = True
        shutil.rmtree(dist_dir / name, ignore_errors=True)
    profile_path = root / "build" / "app_scope.json"
    history_path = root / "build" / ".export_history.json"
    dist_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(json.dumps({"scope": scope}), encoding="utf-8")

    environment = os.environ.copy()
    environment["DOWFLOW_BUILD_SCOPE"] = scope
    environment["DOWFLOW_BUILD_NAME"] = name
    # Never ship the developer's database, config or cookies in an installer.
    environment.pop("DOWFLOW_EMBED_PORTABLE_DATA", None)
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
    ]
    if clean:
        command.append("--clean")
    command += [
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(work_dir),
        str(root / "build" / "dowflow.spec"),
    ]
    started_at = time.time()
    try:
        history = json.loads(history_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        history = {}
    previous_duration = history.get(scope)
    if not isinstance(previous_duration, (int, float)) or previous_duration <= 0:
        previous_duration = None
    percent = 1
    stage = "Preparing build"
    analysis_events = 0
    recent_output: deque[str] = deque(maxlen=200)

    def report_progress(
        next_percent: int,
        next_stage: str,
        eta_seconds: int | None | object = _AUTO_ETA,
    ) -> None:
        nonlocal percent, stage
        limit = 100 if next_stage == "Complete" else 99
        percent = max(percent, min(limit, next_percent))
        stage = next_stage
        elapsed = max(0.0, time.time() - started_at)
        if eta_seconds is _AUTO_ETA:
            eta_seconds = None
            if percent >= 10 and elapsed >= 2:
                measured_total = elapsed * 100 / percent
                estimated_total = (
                    previous_duration * 0.7 + measured_total * 0.3
                    if previous_duration is not None
                    else measured_total
                )
                eta_seconds = max(0, int(estimated_total - elapsed))
        event = {
            "percent": percent,
            "stage": stage,
            "elapsed_seconds": int(elapsed),
            "eta_seconds": eta_seconds,
            "eta_updated_at": time.time(),
        }
        if progress_callback is not None:
            progress_callback(event)

    try:
        report_progress(percent, stage)
        process = subprocess.Popen(
            command,
            cwd=root,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=SUBPROCESS_CREATION_FLAGS,
        )
        if process.stdout is not None:
            for line in process.stdout:
                recent_output.append(line.rstrip())
                next_percent, next_stage, analysis_events = progress_from_log_line(
                    line,
                    percent,
                    analysis_events,
                )
                if next_percent > percent or next_stage != stage:
                    report_progress(next_percent, next_stage)
        return_code = process.wait()
        if return_code:
            detail = "\n".join(recent_output)[-5000:]
            raise RuntimeError(detail or "PyInstaller failed.")
    finally:
        profile_path.unlink(missing_ok=True)

    executable = dist_dir / name / f"{name}.exe"
    if not executable.is_file():
        raise RuntimeError("PyInstaller completed without creating the application folder.")
    duration = max(1.0, time.time() - started_at)
    if previous_duration is not None:
        duration = previous_duration * 0.7 + duration * 0.3
    history[scope] = duration
    history_path.write_text(json.dumps(history, indent=2), encoding="utf-8")

    result = executable
    if installer:
        # Anything started from these folders wrote its database, configuration
        # and logs into them; a setup must stay clean.
        strip_user_data(dist_dir / name)
        strip_user_data(root / "build" / "out" / "DowFlow-Music")
        liner_dir: Path | None = None
        if EDITIONS[scope].get("liner"):
            # Liner embeds the freshly built Music backend, so it has to be
            # packaged after PyInstaller and before the installer.
            build_liner_app(
                root,
                progress_callback=lambda value, stage: report_progress(value, stage),
            )
            liner_dir = liner_app_dir(root)
        elif EDITIONS[scope].get("bundles_music"):
            # The whole-menu setup ships the Music app too. Liner packages the
            # Music backend inside its resources, so that backend comes first.
            if not music_backend_is_reusable(root, blank):
                report_progress(85, "Building the Music backend")
                build_executable(
                    "music",
                    "DowFlow-Music",
                    root,
                    installer=False,
                    blank=blank,
                )
            report_progress(86, "Packaging DowFlow Music")
            build_liner_app(
                root,
                progress_callback=lambda value, stage: report_progress(value, stage),
            )
            liner_dir = liner_app_dir(root)
        report_progress(87, "Preparing media tools")
        prepare_tools(
            root,
            progress_callback=lambda value, stage: report_progress(
                88 + min(1, value // 100),
                stage,
            ),
        )
        report_progress(_INSTALLER_PERCENT_START, "Compressing the installer")
        result = build_installer(
            scope,
            root,
            output_dir,
            progress_callback=report_progress,
            liner_dir=liner_dir,
        )
    report_progress(100, "Complete")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scope", choices=sorted(EXPORT_SCOPES))
    parser.add_argument("name", nargs="?")
    parser.add_argument("--json-progress", action="store_true")
    parser.add_argument("--installer", action="store_true", help="Also build the Inno Setup installer.")
    parser.add_argument(
        "--blank",
        action="store_true",
        help="Build the clean setup for the release (no local data; written to Downloads like every other build).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Where to write <Edition>-Setup.exe (defaults to the Windows Downloads folder).",
    )
    args = parser.parse_args()
    try:
        callback = None
        if args.json_progress:
            callback = lambda event: print(
                json.dumps({"type": "progress", **event}),
                flush=True,
            )
        result = build_executable(
            args.scope,
            args.name,
            progress_callback=callback,
            installer=args.installer,
            blank=args.blank,
            output_dir=args.output_dir,
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.json_progress:
        print(json.dumps({"type": "complete", "path": str(result)}), flush=True)
    else:
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
