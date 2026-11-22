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
EDITIONS: dict[str, dict[str, str]] = {
    "all": {
        "name": "DowFlow",
        "dest": "menu",
        "setup": "DowFlow-Setup",
        "app_name": "DowFlow",
        "app_id": "DowFlow.Menu",
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

WEBVIEW2_BOOTSTRAPPER_URL = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
WEBVIEW2_BOOTSTRAPPER_NAME = "MicrosoftEdgeWebview2Setup.exe"
_INVALID_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def progress_from_log_line(
    line: str,
    current_percent: int,
    analysis_events: int,
) -> tuple[int, str, int]:
    message = line.lower()
    if "checking analysis" in message:
        return max(current_percent, 5), "Scanning dependencies", analysis_events
    if "building analysis" in message:
        return max(current_percent, 10), "Analyzing application", analysis_events
    if "processing standard module hook" in message or message.startswith("info: analyzing "):
        analysis_events += 1
        percent = min(45, 10 + analysis_events // 2)
        return max(current_percent, percent), "Analyzing application", analysis_events
    if "looking for dynamic libraries" in message:
        return max(current_percent, 46), "Collecting runtime libraries", analysis_events
    if "building pyz" in message:
        return max(current_percent, 55), "Compressing Python modules", analysis_events
    if "building pkg" in message:
        return max(current_percent, 72), "Packing application files", analysis_events
    if "building exe" in message:
        return max(current_percent, 86), "Creating executable", analysis_events
    if "building collect" in message:
        return max(current_percent, 92), "Assembling application folder", analysis_events
    if "completed successfully" in message:
        return max(current_percent, 99), "Finalizing application folder", analysis_events
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


def build_installer(
    scope: str,
    project_root: Path | None = None,
    output_dir: Path | None = None,
) -> Path:
    """Compress an already-built edition folder with Inno Setup."""
    if scope not in EXPORT_SCOPES:
        raise ValueError("Unsupported export scope.")
    root = (project_root or Path(__file__).resolve().parent).resolve()
    edition = EDITIONS[scope]
    source_dir = root / "build" / "out" / edition["name"]
    executable = source_dir / f"{edition['name']}.exe"
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
    command = [
        iscc,
        f"/DAppName={edition['app_name']}",
        f"/DAppExe={edition['name']}.exe",
        f"/DSourceDir={source_dir}",
        f"/DDestDir={edition['dest']}",
        f"/DOutputBase={edition['setup']}",
        f"/DOutputDir={destination}",
        f"/DAppId={edition['app_id']}",
        f"/DToolsDir={tools_dir}",
        f"/DIconFile={root / 'static' / 'dowflow.ico'}",
        str(root / "build" / "installer.iss"),
    ]
    completed = subprocess.run(
        command,
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=SUBPROCESS_CREATION_FLAGS,
    )
    if completed.returncode:
        detail = (completed.stdout or "") + (completed.stderr or "")
        raise RuntimeError(detail[-5000:] or "Inno Setup failed.")
    setup = destination / f"{edition['setup']}.exe"
    if not setup.is_file():
        raise RuntimeError("Inno Setup completed without creating the installer.")
    return setup


def build_executable(
    scope: str,
    requested_name: str | None = None,
    project_root: Path | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    *,
    installer: bool = False,
    clean: bool = False,
    output_dir: Path | None = None,
) -> Path:
    """Build the scope's one-directory app and optionally its installer."""
    if scope not in EXPORT_SCOPES:
        raise ValueError("Unsupported export scope.")

    root = (project_root or Path(__file__).resolve().parent).resolve()
    name = sanitize_exe_name(requested_name or EDITIONS[scope]["name"])
    dist_dir = root / "build" / "out"
    work_dir = root / "build" / "work" / f"{scope}-{name}"
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

    def report_progress(next_percent: int, next_stage: str) -> None:
        nonlocal percent, stage
        limit = 100 if next_stage == "Complete" else 99
        percent = max(percent, min(limit, next_percent))
        stage = next_stage
        elapsed = max(0.0, time.time() - started_at)
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
        report_progress(90, "Preparing media tools")
        prepare_tools(root, progress_callback=report_progress)
        report_progress(97, "Compressing the installer")
        result = build_installer(scope, root, output_dir)
    report_progress(100, "Complete")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scope", choices=sorted(EXPORT_SCOPES))
    parser.add_argument("name", nargs="?")
    parser.add_argument("--json-progress", action="store_true")
    parser.add_argument("--installer", action="store_true", help="Also build the Inno Setup installer.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Where to write <Edition>-Setup.exe (defaults to %USERPROFILE%\\Downloads).",
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
