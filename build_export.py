"""Build a named, scoped DowFlow one-file executable from the source checkout."""
from __future__ import annotations

import argparse
from collections import deque
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from config import SUBPROCESS_CREATION_FLAGS

EXPORT_SCOPES = {"all", "video", "music", "film", "anime", "image"}
_INVALID_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


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
    if "completed successfully" in message:
        return max(current_percent, 99), "Finalizing executable", analysis_events
    return current_percent, "Building executable", analysis_events


def sanitize_exe_name(value: str) -> str:
    name = Path(value).stem.strip()
    name = _INVALID_NAME.sub("_", name).strip(" .")
    if not name or name.upper() in _WINDOWS_RESERVED:
        raise ValueError("Choose a valid Windows executable name.")
    return name[:100]


def build_executable(
    scope: str,
    requested_name: str,
    project_root: Path | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> Path:
    if scope not in EXPORT_SCOPES:
        raise ValueError("Unsupported export scope.")

    root = (project_root or Path(__file__).resolve().parent).resolve()
    name = sanitize_exe_name(requested_name)
    dist_dir = root / "dist"
    work_dir = root / "build-work" / f"{scope}-{name}"
    profile_path = root / "build" / "app_scope.json"
    history_path = root / "build" / ".export_history.json"
    dist_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(json.dumps({"scope": scope}), encoding="utf-8")

    environment = os.environ.copy()
    environment["DOWFLOW_BUILD_SCOPE"] = scope
    environment["DOWFLOW_BUILD_NAME"] = name
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(work_dir),
        str(root / "build.spec"),
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
                if next_percent > percent:
                    report_progress(next_percent, next_stage)
        return_code = process.wait()
        if return_code:
            detail = "\n".join(recent_output)[-5000:]
            raise RuntimeError(detail or "PyInstaller failed.")
    finally:
        profile_path.unlink(missing_ok=True)

    executable = dist_dir / f"{name}.exe"
    if not executable.is_file():
        raise RuntimeError("PyInstaller completed without creating the requested EXE.")
    duration = max(1.0, time.time() - started_at)
    if previous_duration is not None:
        duration = previous_duration * 0.7 + duration * 0.3
    history[scope] = duration
    history_path.write_text(json.dumps(history, indent=2), encoding="utf-8")
    report_progress(100, "Complete")
    return executable


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scope", choices=sorted(EXPORT_SCOPES))
    parser.add_argument("name")
    parser.add_argument("--json-progress", action="store_true")
    args = parser.parse_args()
    try:
        callback = None
        if args.json_progress:
            callback = lambda event: print(
                json.dumps({"type": "progress", **event}),
                flush=True,
            )
        executable = build_executable(
            args.scope,
            args.name,
            progress_callback=callback,
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.json_progress:
        print(json.dumps({"type": "complete", "path": str(executable)}), flush=True)
    else:
        print(executable)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
