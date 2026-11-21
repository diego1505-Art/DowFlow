"""DowFlow's single-console launcher.

``start.bat`` starts this file once. The launcher keeps everything in that one
console: the GitHub project update, the virtual-environment and dependency
checks, then the Flask server with its live logs. The window stays open while
the server runs and reports what happened when it stops.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

from config import SUBPROCESS_CREATION_FLAGS, get_data_root

APP_VERSION = "V15"
GITHUB_REPOSITORY = "https://github.com/diego1505-Art/DowFlow.git"
GITHUB_BRANCH = "main"
UPDATE_MARKER = ".dowflow-commit"
DEPS_FLAG = "deps_ok.flag"
DEPS_MAX_AGE_SECONDS = 24 * 60 * 60
PORT_ATTEMPTS = 20
PRESERVED_NAMES = frozenset(
    name.casefold()
    for name in (
        ".venv",
        "downloads",
        "logs",
        "build-work",
        "dist",
        "build",
        "__pycache__",
        ".pytest_cache",
        ".git",
        "config.json",
        "dowflow.db",
        "dowflow.db-wal",
        "dowflow.db-shm",
        UPDATE_MARKER,
    )
)

_LOG_ENTRY_RE = re.compile(
    r"^(?P<time>\d{2}:\d{2}:\d{2})\s*\|\s*(?P<level>[A-Z]+)\s*\|\s*"
    r"(?P<logger>[^|]+?)\s*\|\s*(?P<message>.*)$"
)
_FILE_LOG_ENTRY_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}\s+(?P<time>\d{2}:\d{2}:\d{2})\s*\|\s*"
    r"(?P<level>[A-Z]+)\s*\|\s*(?P<logger>[^|]+?)\s*\|\s*\d+\s*\|\s*\d+\s*\|\s*(?P<message>.*)$"
)
_HTTP_ACCESS_RE = re.compile(
    r'^(?P<ip>.+?)\s+-\s+-\s+\[(?P<date>[^\]]+)\]\s+"'
    r'(?P<method>[A-Z]+)\s+(?P<path>.*?)\s+HTTP/(?P<version>[\d.]+)"\s+'
    r"(?P<status>\d{3})\s+(?P<size>\S+)$"
)
_ANSI_ESCAPE_RE = re.compile(r"\033\[[0-9;]*m")

_update_log_path: Path | None = None


# ── Console output ───────────────────────────────────────────────────────────

def _write(text: str = "") -> None:
    """Print one line to the console that started DowFlow, if there is one."""
    stream = sys.stdout
    if stream is None:
        return
    try:
        stream.write(text + "\n")
        stream.flush()
    except (OSError, ValueError):
        pass


def _log(message: str = "") -> None:
    """Print a launcher line and keep it in the temporary update log."""
    _write(message)
    path = _update_log_path
    if path is None:
        return
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")
    except OSError:
        pass


def _start_update_log() -> None:
    global _update_log_path
    _update_log_path = Path(tempfile.gettempdir()) / f"dowflow-update-{os.getpid()}.log"


def _delete_update_log() -> None:
    """Remove the temporary update log once the server has started."""
    global _update_log_path
    path, _update_log_path = _update_log_path, None
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _confirm(prompt: str) -> bool:
    _write(prompt)
    try:
        answer = input("> ")
    except (EOFError, OSError):
        return False
    return answer.strip().lower().startswith("y")


# ── Project location ─────────────────────────────────────────────────────────

def project_root() -> Path:
    if getattr(sys, "frozen", False):
        executable_dir = Path(sys.executable).resolve().parent
        if (
            executable_dir.name.lower() == "dist"
            and (executable_dir.parent / "launcher.py").is_file()
        ):
            return executable_dir.parent
        return executable_dir
    return Path(__file__).resolve().parent


# ── GitHub project update ────────────────────────────────────────────────────

def _run(
    command: list[str], cwd: Path, timeout: float = 180
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return subprocess.CompletedProcess(command, 1, "", "")


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _run(["git", *args], root)


def _last_output_line(result: subprocess.CompletedProcess[str]) -> str:
    lines = [line.strip() for line in (result.stderr or result.stdout).splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _update_from_git(root: Path) -> bool:
    _log("[UPDATE] Checking GitHub for project updates...")
    if shutil.which("git") is None:
        _log("[UPDATE] Git is unavailable: project update skipped.")
        return False

    old_head = _git(root, "rev-parse", "HEAD").stdout.strip()
    fetch = _git(root, "fetch", GITHUB_REPOSITORY, GITHUB_BRANCH, "--quiet")
    if fetch.returncode != 0:
        _log("[UPDATE] Unable to contact GitHub: project update skipped.")
        detail = _last_output_line(fetch)
        if detail:
            _log(f"[WARNING] {detail}")
        return False

    remote_head = _git(root, "rev-parse", "FETCH_HEAD").stdout.strip()
    if not remote_head or remote_head == old_head:
        _log("[UPDATE] Project is up to date.")
        return False

    details = _git(root, "show", "-s", "--format=%an%n%s", "FETCH_HEAD").stdout.splitlines()
    author = details[0].strip() if details else "Unknown"
    subject = details[1].strip() if len(details) > 1 else "New project update"
    _log("")
    _log("A new project update is available on GitHub:")
    _log(f"  Commit:       {remote_head[:7]}")
    _log(f"  Published by: {author}")
    _log(f"  Changes:      {subject}")
    if not _confirm("Would you like to download and install this update? [y/N] "):
        _log("[UPDATE] Project update skipped. Dependencies will still be checked.")
        return False

    stashed = False
    if _git(root, "diff", "--quiet", "HEAD").returncode != 0:
        _log("[UPDATE] Local changes detected: temporarily saving tracked changes...")
        if _git(root, "stash", "push", "-m", "DowFlow auto-update").returncode != 0:
            _log("[UPDATE] Unable to save local changes: project update skipped.")
            return False
        stashed = True

    merge = _git(root, "merge", "--ff-only", "FETCH_HEAD")
    if merge.returncode != 0:
        _log("[UPDATE] GitHub update failed. Local files are preserved.")
        detail = _last_output_line(merge)
        if detail:
            _log(f"[WARNING] {detail}")
        if stashed:
            _git(root, "stash", "pop")
        return False

    if stashed and _git(root, "stash", "pop").returncode != 0:
        _log("[WARNING] Conflict while restoring local changes.")
        _log("[WARNING] The stash is still available with: git stash list")

    _log("[UPDATE] Project update applied.")
    return True


def _repository_parts() -> tuple[str, str]:
    clean = GITHUB_REPOSITORY.strip().removesuffix(".git").rstrip("/")
    parts = [part for part in clean.split("/") if part]
    if len(parts) < 2:
        raise ValueError(f"Unsupported GitHub repository URL: {GITHUB_REPOSITORY}")
    return parts[-2], parts[-1]


def _latest_commit() -> tuple[str, str]:
    owner, name = _repository_parts()
    request = Request(
        f"https://api.github.com/repos/{owner}/{name}/commits/{GITHUB_BRANCH}",
        headers={
            "User-Agent": "DowFlow-Updater",
            "Accept": "application/vnd.github+json",
        },
    )
    with urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    commit = str(payload["sha"]).strip()
    if not commit:
        raise ValueError("GitHub did not return the latest commit.")
    message = str(payload["commit"]["message"]).splitlines()
    return commit, (message[0].strip() if message else "New project update")


def _download_archive(root: Path, destination: Path) -> None:
    owner, name = _repository_parts()
    url = f"https://codeload.github.com/{owner}/{name}/zip/refs/heads/{GITHUB_BRANCH}"
    request = Request(url, headers={"User-Agent": "DowFlow-Updater"})
    with urlopen(request, timeout=120) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle)


def _safe_extract(bundle: zipfile.ZipFile, destination: Path) -> None:
    base = destination.resolve()
    for member in bundle.namelist():
        target = (destination / member).resolve()
        if base != target and base not in target.parents:
            raise ValueError(f"Unsafe path in the GitHub archive: {member}")
    bundle.extractall(destination)


def _is_preserved(relative: str) -> bool:
    return relative.split("/")[0].casefold() in PRESERVED_NAMES


def _file_map(root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    if not root.is_dir():
        return files
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if _is_preserved(relative):
            continue
        digest = hashlib.sha256()
        try:
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError:
            continue
        files[relative] = digest.hexdigest()
    return files


def _same_project_files(current: Path, archive: Path) -> bool:
    current_files = _file_map(current)
    archive_files = _file_map(archive)
    return current_files == archive_files


def _copy_project_files(source: Path, destination: Path) -> None:
    source_files = _file_map(source)

    for path in destination.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(destination).as_posix()
        if _is_preserved(relative) or relative in source_files:
            continue
        try:
            path.unlink()
        except OSError:
            pass

    for relative in source_files:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, target)


def _update_from_zip(root: Path) -> bool:
    _log("[UPDATE] Standalone ZIP detected; checking GitHub for project updates...")
    try:
        latest, subject = _latest_commit()
    except (OSError, ValueError, KeyError, TimeoutError) as error:
        _log(f"[UPDATE] Unable to contact GitHub: {error}")
        _log("[UPDATE] Project update skipped.")
        return False

    marker = root / UPDATE_MARKER
    local_marker = ""
    if marker.is_file():
        try:
            local_marker = marker.read_text(encoding="ascii", errors="ignore").strip()
        except OSError:
            local_marker = ""

    if local_marker == latest:
        _log(f"[UPDATE] Project is up to date ({latest[:7]}).")
        return False

    temporary = Path(tempfile.mkdtemp(prefix="dowflow-zip-update-"))
    try:
        archive = temporary / "latest.zip"
        extracted = temporary / "extracted"
        extracted.mkdir()
        _download_archive(root, archive)
        with zipfile.ZipFile(archive) as bundle:
            _safe_extract(bundle, extracted)
        roots = [path for path in extracted.iterdir() if path.is_dir()]
        if not roots:
            _log("[UPDATE] The GitHub ZIP did not contain a project folder.")
            return False
        archive_root = roots[0]

        if not local_marker and _same_project_files(root, archive_root):
            marker.write_text(latest, encoding="ascii")
            _log(f"[UPDATE] Project is up to date ({latest[:7]}).")
            return False

        _log("")
        _log("A new DowFlow ZIP update is available:")
        _log(f"  Commit:  {latest[:7]}")
        _log(f"  Changes: {subject}")
        if not _confirm("Would you like to download and install this update? [y/N] "):
            _log("[UPDATE] Project update skipped. Local files are preserved.")
            return False

        _copy_project_files(archive_root, root)
        marker.write_text(latest, encoding="ascii")
        _log("[UPDATE] Project ZIP update installed.")
        return True
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def _run_project_update(root: Path) -> bool:
    # Never let Git walk into a parent directory for a ZIP install.
    if (root / ".git").exists():
        return _update_from_git(root)
    return _update_from_zip(root)


# ── Virtual environment and dependencies ─────────────────────────────────────

def _venv_python(root: Path) -> Path | None:
    for candidate in (
        root / ".venv" / "Scripts" / "python.exe",
        root / ".venv" / "bin" / "python",
    ):
        if candidate.is_file():
            return candidate
    return None


def _restart_inside_venv(root: Path) -> int | None:
    """Re-run this launcher with the project interpreter so imports resolve."""
    if os.environ.get("DOWFLOW_LAUNCHER_VENV") == "1":
        return None

    python = _venv_python(root)
    if python is None:
        _log("[SETUP] Creating the virtual environment (first launch)...")
        created = subprocess.run(
            [sys.executable, "-m", "venv", str(root / ".venv")],
            cwd=str(root),
            check=False,
        )
        if created.returncode != 0:
            _log("[ERROR] Could not create .venv. Install Python 3.10+ in PATH and retry.")
            return 1
        python = _venv_python(root)

    if python is None:
        _log("[ERROR] The virtual environment is incomplete (.venv\\Scripts\\python.exe missing).")
        return 1

    if Path(sys.executable).resolve() == python.resolve():
        return None

    environment = os.environ.copy()
    environment["DOWFLOW_LAUNCHER_VENV"] = "1"
    try:
        os.execve(
            str(python),
            [str(python), str(Path(__file__).resolve()), *sys.argv[1:]],
            environment,
        )
    except OSError as error:
        _log(f"[ERROR] Could not restart inside the virtual environment: {error}")
        return 1
    return None


def _chromium_is_available() -> bool:
    script = (
        "from playwright.sync_api import sync_playwright as s; "
        "p = s().start(); b = p.chromium.launch(headless=True); b.close(); p.stop()"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _ensure_dependencies(root: Path) -> None:
    flag = root / ".venv" / DEPS_FLAG
    try:
        if time.time() - flag.stat().st_mtime < DEPS_MAX_AGE_SECONDS:
            return
    except OSError:
        pass

    _log("[SETUP] Checking dependencies...")
    failed = False
    for command in (
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-q",
            "-r",
            "requirements.txt",
        ],
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-q",
            "-U",
            "yt-dlp",
        ],
    ):
        if subprocess.run(command, cwd=str(root), check=False).returncode != 0:
            failed = True

    if not _chromium_is_available():
        _log("[SETUP] Installing Playwright Chromium...")
        if subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            cwd=str(root),
            check=False,
        ).returncode != 0:
            failed = True

    if failed:
        _log("[WARNING] Dependency verification failed; DowFlow will try to start anyway.")
        return
    try:
        flag.write_text("verification-ok", encoding="utf-8")
    except OSError:
        pass


def _augment_path_with_ffmpeg(environment: dict[str, str]) -> None:
    local_app_data = environment.get("LOCALAPPDATA")
    if not local_app_data:
        return
    packages = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
    try:
        candidates = sorted(packages.glob("Gyan.FFmpeg*"))
    except OSError:
        return
    for package in candidates:
        for folder in sorted(package.glob("ffmpeg-*")):
            binary = folder / "bin" / "ffmpeg.exe"
            if binary.is_file():
                environment["PATH"] = f"{binary.parent}{os.pathsep}{environment.get('PATH', '')}"
                return


# ── Server discovery and log tailing ─────────────────────────────────────────

def _port_is_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.15):
            return True
    except OSError:
        return False


def _is_dowflow_server(host: str, port: int) -> bool:
    """Return True only for a live DowFlow instance running the current build."""
    try:
        with urlopen(f"http://{host}:{port}/api/status", timeout=0.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not (
            response.status == 200
            and isinstance(payload, dict)
            and payload.get("ready") is True
            and payload.get("service") == "DowFlow"
        ):
            return False

        from config import get_runtime_build_id

        return payload.get("build_id") == get_runtime_build_id()
    except (OSError, ValueError, TimeoutError):
        return False


def _next_available_port(host: str, port: int, attempts: int = PORT_ATTEMPTS) -> int | None:
    final_port = min(65535, port + attempts)
    for candidate in range(port + 1, final_port + 1):
        if not _port_is_open(host, candidate):
            return candidate
    return None


def _plain(line: str) -> str:
    return _ANSI_ESCAPE_RE.sub("", line).strip()


def _is_redundant_server_line(line: str) -> bool:
    plain = _plain(line)
    if plain.startswith("* Running on http://"):
        return True
    match = _LOG_ENTRY_RE.match(plain)
    logger = match["logger"].strip() if match else "werkzeug"
    message = match["message"].strip() if match else plain
    if logger != "werkzeug":
        return False
    if message.lower().startswith(("* running on http://", "press ctrl+c to quit")):
        return True
    return _HTTP_ACCESS_RE.match(message) is not None


def _format_file_log_line(line: str) -> str | None:
    match = _FILE_LOG_ENTRY_RE.match(line.strip())
    if not match:
        return None
    return (
        f"{match['time']} | {match['level']} | {match['logger'].strip()} | "
        f"{match['message']}"
    )


def _is_startup_file_log(line: str) -> bool:
    plain = _plain(line)
    match = _LOG_ENTRY_RE.match(plain)
    if not match:
        return plain.startswith(("* Serving Flask app", "* Debug mode:"))
    logger = match["logger"].strip()
    message = match["message"]
    if logger == "app":
        return message.startswith(
            (
                "DowFlow — Multi-Site Media Downloader",
                "Measuring network speed",
                "Server started at ",
                "Press Ctrl+C to stop",
                "Network speed detected:",
                "Network speed unavailable",
            )
        )
    if logger == "playlist":
        return message.startswith("[perf] Connection tier:")
    return logger == "werkzeug" and message.startswith(
        (
            "WARNING: This is a development server",
            "* Serving Flask app",
            "* Debug mode:",
            "* Running on http://",
            "Press CTRL+C to quit",
        )
    )


def _read_existing_server_logs(log_path: Path) -> tuple[list[str], int]:
    try:
        with log_path.open("r", encoding="utf-8", errors="replace") as handle:
            file_size = handle.seek(0, os.SEEK_END)
            start_offset = max(0, file_size - 512 * 1024)
            handle.seek(start_offset)
            if start_offset:
                handle.readline()
            raw_lines = handle.readlines()
            offset = handle.tell()
    except OSError:
        return [], 0

    formatted = [
        _format_file_log_line(line) or line.rstrip("\r\n")
        for line in raw_lines
    ]
    start_index = next(
        (
            index
            for index in range(len(formatted) - 1, -1, -1)
            if (match := _LOG_ENTRY_RE.match(formatted[index]))
            and match["logger"].strip() == "app"
            and match["message"].startswith("DowFlow — Multi-Site Media Downloader")
        ),
        None,
    )
    if start_index is None:
        start_index = next(
            (
                index
                for index in range(len(formatted) - 1, -1, -1)
                if (match := _LOG_ENTRY_RE.match(formatted[index]))
                and match["logger"].strip() == "app"
                and match["message"].startswith("Server started at ")
            ),
            max(0, len(formatted) - 30),
        )
    lines = [
        line for line in formatted[start_index:]
        if _is_startup_file_log(line) and not _is_redundant_server_line(line)
    ]
    return lines, offset


def _read_appended_server_logs(log_path: Path, offset: int) -> tuple[list[str], int]:
    try:
        with log_path.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(offset)
            appended = handle.readlines()
            next_offset = handle.tell()
    except OSError:
        return [], offset
    lines = []
    for raw_line in appended:
        line = _format_file_log_line(raw_line) or raw_line.rstrip("\r\n")
        if _is_startup_file_log(line) and not _is_redundant_server_line(line):
            lines.append(line)
    return lines, next_offset


def _read_appended_runtime_logs(log_path: Path, offset: int) -> tuple[list[str], int]:
    try:
        with log_path.open("r", encoding="utf-8", errors="replace") as handle:
            if handle.seek(0, os.SEEK_END) < offset:
                offset = 0
            handle.seek(offset)
            appended = handle.readlines()
            next_offset = handle.tell()
    except OSError:
        return [], offset
    lines = []
    for raw_line in appended:
        line = _format_file_log_line(raw_line) or raw_line.rstrip("\r\n")
        if not _is_redundant_server_line(line):
            lines.append(line)
    return lines, next_offset


def _log_file_size(log_path: Path) -> int:
    try:
        return log_path.stat().st_size
    except OSError:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.touch(exist_ok=True)
            return log_path.stat().st_size
        except OSError:
            return 0


# ── Server and application window ────────────────────────────────────────────

def _stop_server(process: subprocess.Popen | None, timeout: float = 5.0) -> None:
    """Stop the Flask child together with the processes it spawned.

    On Windows the virtual-environment ``python.exe`` is a redirector that
    waits for the real interpreter: ``terminate()`` only kills the redirector
    and leaves the interpreter that owns the listening socket running as an
    orphan.
    """
    if process is None or process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                creationflags=SUBPROCESS_CREATION_FLAGS,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _ensure_portable_download_folder() -> bool:
    """Create the download folder silently; the UI changes it later."""
    if not getattr(sys, "frozen", False):
        return True

    from config import configure_runtime_paths, get_download_path

    folder = get_download_path(required=False)
    if folder is None:
        return True
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        _log(f"[ERROR] Could not create the download folder: {error}")
        return False
    configure_runtime_paths(folder)
    return True


def _apply_windows_window_icon(icon_path: str) -> None:
    """Set the native window/taskbar icon for pywebview on Windows."""
    if os.name != "nt" or not os.path.isfile(icon_path):
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32
        try:
            shell32.SetCurrentProcessExplicitAppUserModelID("DowFlow.DowFlow")
        except (AttributeError, OSError):
            pass

        hwnd = 0
        for _ in range(30):
            hwnd = user32.FindWindowW(None, "DowFlow")
            if hwnd:
                break
            time.sleep(0.1)
        if not hwnd:
            return
        image_icon = 1  # IMAGE_ICON
        load_from_file = 0x00000010
        default_size = 0x00000040
        handle = user32.LoadImageW(
            None, icon_path, image_icon, 0, 0, load_from_file | default_size
        )
        if not handle:
            return
        wm_seticon = 0x0080
        icon_small = 0
        icon_big = 1
        user32.SendMessageW(hwnd, wm_seticon, icon_small, handle)
        user32.SendMessageW(hwnd, wm_seticon, icon_big, handle)
        # Also replace the class icon used by the title bar/taskbar when the
        # backend cached the Python process icon before WM_SETICON arrived.
        set_class_long_ptr = getattr(user32, "SetClassLongPtrW", None)
        if set_class_long_ptr is not None:
            set_class_long_ptr(hwnd, -34, handle)  # GCLP_HICON
            set_class_long_ptr(hwnd, -14, handle)  # GCLP_HICONSM
    except (AttributeError, OSError):
        return


def _prepare_windows_app_identity() -> None:
    """Give the launch a DowFlow taskbar identity before GUI creation."""
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("DowFlow.DowFlow")
    except (AttributeError, OSError):
        return


def _show_native_error(message: str) -> None:
    """Report a launch failure when no console is attached."""
    if os.name != "nt" or sys.stdout is not None:
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "DowFlow", 0x10)
    except (AttributeError, OSError):
        return


def _run_console_session(root: Path, frozen: bool) -> int:
    host = os.environ.get("DOWFLOW_HOST", "127.0.0.1")
    port = int(os.environ.get("DOWFLOW_PORT", "5001"))
    probe_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    url = f"http://{probe_host}:{port}"

    process: subprocess.Popen | None = None
    existing_server = False
    notice: str | None = None
    requested_port = port

    if _port_is_open(probe_host, port):
        if _is_dowflow_server(probe_host, port):
            existing_server = True
            notice = "Connected to the running DowFlow server."
        else:
            available_port = _next_available_port(probe_host, port)
            if available_port is None:
                _log(
                    f"[ERROR] Ports {requested_port} through "
                    f"{min(65535, requested_port + PORT_ATTEMPTS)} are already in use."
                )
                return 1
            port = available_port
            url = f"http://{probe_host}:{port}"
            notice = (
                f"Port {requested_port} is busy or runs another DowFlow build; "
                f"starting on {url}"
            )
    if notice:
        _log(f"[INFO] {notice}")
    if existing_server:
        recent_lines, _ = _read_existing_server_logs(
            get_data_root() / "logs" / "dowflow.log"
        )
        for line in recent_lines[-30:]:
            _write(line)

    if not existing_server:
        command = (
            [sys.executable, "--server"]
            if frozen
            else [sys.executable, str(root / "app.py")]
        )
        environment = os.environ.copy()
        environment.update(
            {
                "DOWFLOW_PORT": str(port),
                "DOWFLOW_PARENT_PID": str(os.getpid()),
                "PYTHONIOENCODING": "utf-8",
            }
        )
        _augment_path_with_ffmpeg(environment)
        try:
            process = subprocess.Popen(
                command,
                cwd=str(root),
                env=environment,
                # Source mode inherits this console so the server logs are live.
                stdout=subprocess.DEVNULL if frozen else None,
                stderr=subprocess.STDOUT if frozen else None,
                creationflags=SUBPROCESS_CREATION_FLAGS if frozen else 0,
            )
        except OSError as error:
            _log(f"[ERROR] Could not start the Flask server: {error}")
            return 1

        timeout = 1800.0 if frozen else 60.0
        deadline = time.monotonic() + timeout
        while not _port_is_open(probe_host, port):
            if process.poll() is not None:
                _log(f"[ERROR] The server stopped during startup (code {process.returncode}).")
                _log("[ERROR] See logs\\dowflow.log for details.")
                return 1
            if time.monotonic() >= deadline:
                _log("[ERROR] The server did not respond in time.")
                _stop_server(process)
                return 1
            time.sleep(0.2)

    _log(f"[OK] DowFlow is running at {url}")
    _log("[INFO] Keep this window open: closing it stops the server.")
    _log("")
    # The server is up: the temporary update log is no longer needed.
    _delete_update_log()

    return _run_application_window(root, url, process, existing_server)


def _run_application_window(
    root: Path,
    url: str,
    process: subprocess.Popen | None,
    existing_server: bool,
) -> int:
    try:
        import webview
    except ImportError as error:
        _log(f"[ERROR] The native window is unavailable: {error}")
        _log(f"[INFO] Open {url} in your browser instead.")
        _stop_server(process)
        return 1

    exit_code = {"value": 0}
    closing = threading.Event()
    stop_tail = threading.Event()
    log_path = get_data_root() / "logs" / "dowflow.log"
    window = webview.create_window(
        "DowFlow",
        url,
        width=1280,
        height=860,
        min_size=(900, 600),
    )

    def watch_server() -> None:
        code = process.wait()
        if closing.is_set():
            return
        exit_code["value"] = code or 0
        _log("")
        if code:
            _log(f"[ERROR] The DowFlow server stopped unexpectedly (code {code}).")
            _log("[ERROR] See logs\\dowflow.log for details.")
        else:
            _log("[INFO] The DowFlow server stopped.")
        try:
            window.destroy()
        except Exception:
            pass

    def tail_runtime_logs(offset: int) -> None:
        while not stop_tail.wait(0.2):
            lines, offset = _read_appended_runtime_logs(log_path, offset)
            for line in lines:
                _write(line)

    if process is not None:
        threading.Thread(
            target=watch_server, name="dowflow-server-watch", daemon=True
        ).start()
    elif existing_server:
        threading.Thread(
            target=tail_runtime_logs,
            args=(_log_file_size(log_path),),
            name="dowflow-log-tail",
            daemon=True,
        ).start()

    bundle_root = Path(getattr(sys, "_MEIPASS", root))
    icon_path = bundle_root / "static" / "dowflow.ico"
    try:
        _prepare_windows_app_identity()
        webview.start(_apply_windows_window_icon, args=(str(icon_path),))
    except Exception as error:
        _log(f"[ERROR] The DowFlow window could not be opened: {error}")
        _show_native_error(
            "The DowFlow window could not be opened.\n\n"
            f"{error}\n\n"
            "See logs\\dowflow.log for details."
        )
        if exit_code["value"] == 0:
            exit_code["value"] = 1
    finally:
        closing.set()
        stop_tail.set()
        _stop_server(process)

    _log("")
    _log("[INFO] DowFlow stopped.")
    return exit_code["value"]


def main() -> int:
    root = project_root()
    frozen = getattr(sys, "frozen", False)

    _write("")
    _write(f" DOWFLOW {APP_VERSION}")
    _write("=" * 42)

    if frozen:
        if not _ensure_portable_download_folder():
            return 0
    else:
        environment_code = _restart_inside_venv(root)
        if environment_code is not None:
            return environment_code
        _ensure_dependencies(root)

    _start_update_log()
    try:
        if not frozen and _run_project_update(root):
            _log("[UPDATE] Starting the updated version...")
        try:
            return _run_console_session(root, frozen)
        except KeyboardInterrupt:
            _log("")
            _log("[INFO] DowFlow stopped.")
            return 0
    finally:
        _delete_update_log()


if __name__ == "__main__":
    if getattr(sys, "frozen", False) and "--choose-folder" in sys.argv:
        from folder_picker import main as folder_picker_main

        raise SystemExit(folder_picker_main(sys.argv[2:]))
    if getattr(sys, "frozen", False) and "--server" in sys.argv:
        from app import run_server

        run_server()
    else:
        raise SystemExit(main())
