"""Download required native tools beside a frozen DowFlow executable."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import threading
import zipfile
from pathlib import Path, PurePosixPath
from urllib.request import Request, urlopen

from config import (
    IS_FROZEN,
    SUBPROCESS_CREATION_FLAGS,
    configure_runtime_paths,
    get_bin_folder,
    get_download_path,
)
from logger import get_logger

log = get_logger("bootstrap")

FFMPEG_ARCHIVE_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
FFMPEG_CHECKSUM_URL = FFMPEG_ARCHIVE_URL + ".sha256"
_PROGRESS_LOCK = threading.Lock()
_PROGRESS = {
    "status": "pending",
    "percent": 0,
    "stage": "Waiting for dependency check",
    "error": None,
}
_DEPENDENCY_THREAD: threading.Thread | None = None


def dependency_progress() -> dict[str, object]:
    with _PROGRESS_LOCK:
        return dict(_PROGRESS)


def _set_progress(
    percent: int,
    stage: str,
    status: str = "loading",
    error: str | None = None,
) -> None:
    with _PROGRESS_LOCK:
        _PROGRESS.update(
            status=status,
            percent=max(0, min(100, percent)),
            stage=stage,
            error=error,
        )


def _dependency_worker() -> None:
    try:
        ensure_external_dependencies(_set_progress)
    except Exception as error:
        log.error("External dependency setup failed: %s", error, exc_info=True)
        _set_progress(100, "Dependency setup failed", status="failed", error=str(error))
    else:
        from utils import clear_ffmpeg_cache

        clear_ffmpeg_cache()
        _set_progress(100, "Ready", status="ready")


def start_dependency_setup(force: bool = False) -> threading.Thread | None:
    """Start verification and installation without blocking the Flask server."""
    global _DEPENDENCY_THREAD
    if not IS_FROZEN:
        return None
    with _PROGRESS_LOCK:
        if _DEPENDENCY_THREAD is not None and _DEPENDENCY_THREAD.is_alive():
            return _DEPENDENCY_THREAD
        if _PROGRESS["status"] == "ready" and not force:
            return _DEPENDENCY_THREAD
        _PROGRESS.update(
            status="loading",
            percent=0,
            stage="Checking media tools",
            error=None,
        )
        _DEPENDENCY_THREAD = threading.Thread(
            target=_dependency_worker,
            name="dowflow-dependencies",
            daemon=True,
        )
        _DEPENDENCY_THREAD.start()
        return _DEPENDENCY_THREAD


def _read_url(
    url: str,
    destination: Path | None = None,
    progress_callback=None,
) -> bytes:
    request = Request(url, headers={"User-Agent": "DowFlow/1.0"})
    with urlopen(request, timeout=60) as response:
        if destination is None:
            return response.read()
        total = int(response.headers.get("Content-Length") or 0)
        downloaded = 0
        with destination.open("wb") as handle:
            while chunk := response.read(1024 * 1024):
                handle.write(chunk)
                downloaded += len(chunk)
                if progress_callback is not None and total:
                    progress_callback(min(100, downloaded * 100 // total))
        if progress_callback is not None:
            progress_callback(100)
    return b""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_zip_member(archive: zipfile.ZipFile, member: zipfile.ZipInfo, target: Path) -> None:
    temporary = target.with_suffix(target.suffix + ".tmp")
    with archive.open(member) as source, temporary.open("wb") as destination:
        shutil.copyfileobj(source, destination, length=1024 * 1024)
    temporary.replace(target)


def _install_ffmpeg(bin_folder: Path | None = None, progress_callback=None) -> str:
    bin_folder = bin_folder or get_bin_folder()
    log.info("Downloading FFmpeg into %s", bin_folder)
    with tempfile.TemporaryDirectory(prefix="dowflow-ffmpeg-") as temporary:
        archive_path = Path(temporary) / "ffmpeg.zip"
        expected = _read_url(FFMPEG_CHECKSUM_URL).decode("ascii", errors="ignore")
        expected_hash = next(
            (word.lower() for word in expected.split() if len(word) == 64 and all(c in "0123456789abcdefABCDEF" for c in word)),
            None,
        )
        if expected_hash is None:
            raise RuntimeError("The official FFmpeg checksum could not be read.")

        _read_url(
            FFMPEG_ARCHIVE_URL,
            archive_path,
            progress_callback=(
                lambda value: progress_callback(10 + value * 40 // 100)
                if progress_callback is not None else None
            ),
        )
        if _sha256(archive_path) != expected_hash:
            raise RuntimeError("FFmpeg checksum mismatch; the archive was not installed.")

        found: set[str] = set()
        with zipfile.ZipFile(archive_path) as archive:
            ffmpeg_member = next(
                (
                    member
                    for member in archive.infolist()
                    if PurePosixPath(member.filename).name.lower() == "ffmpeg.exe"
                ),
                None,
            )
            if ffmpeg_member is None:
                raise RuntimeError("The FFmpeg archive did not contain ffmpeg.exe.")
            source_bin = PurePosixPath(ffmpeg_member.filename).parent
            for member in archive.infolist():
                member_path = PurePosixPath(member.filename)
                name = member_path.name.lower()
                if (
                    member_path.parent == source_bin
                    and (name in {"ffmpeg.exe", "ffprobe.exe"} or member_path.suffix.lower() == ".dll")
                    and not member.is_dir()
                ):
                    _copy_zip_member(archive, member, bin_folder / name)
                    if name in {"ffmpeg.exe", "ffprobe.exe"}:
                        found.add(name)
        if found != {"ffmpeg.exe", "ffprobe.exe"}:
            raise RuntimeError("The FFmpeg archive did not contain ffmpeg.exe and ffprobe.exe.")
        (bin_folder / ".ffmpeg.sha256").write_text(expected_hash, encoding="ascii")
        return expected_hash


def _chromium_installed(browser_dir: Path) -> bool:
    return browser_dir.is_dir() and any(browser_dir.rglob("chrome.exe"))


def _install_chromium(browser_dir: Path, progress_callback=None) -> None:
    log.info("Downloading Playwright Chromium into %s", browser_dir)
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_dir)
    from playwright._impl._driver import compute_driver_executable

    driver, cli = compute_driver_executable()
    process = subprocess.Popen(
        [str(driver), str(cli), "install", "chromium"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=os.environ.copy(),
        creationflags=SUBPROCESS_CREATION_FLAGS,
    )
    if process.stdout is not None:
        for line in process.stdout:
            match = re.search(r"(\d{1,3})%", line)
            if match and progress_callback is not None:
                progress_callback(75 + int(match.group(1)) * 24 // 100)
    if process.wait() != 0:
        raise RuntimeError("Playwright could not install Chromium.")
    if not _chromium_installed(browser_dir):
        raise RuntimeError("Playwright completed without installing Chromium.")


def ensure_external_dependencies(progress_callback=None) -> None:
    """Verify or update FFmpeg and Chromium under the media root's bin/."""
    download_root = get_download_path()
    bin_folder = get_bin_folder()
    bin_folder.mkdir(parents=True, exist_ok=True)
    configure_runtime_paths(download_root)
    browser_dir = bin_folder / "ms-playwright"

    if progress_callback:
        progress_callback(5, "Checking FFmpeg")
    installed_ffmpeg_hash = ""
    try:
        installed_ffmpeg_hash = (bin_folder / ".ffmpeg.sha256").read_text(encoding="ascii").strip()
    except OSError:
        pass
    ffmpeg_ready = all((bin_folder / name).is_file() for name in ("ffmpeg.exe", "ffprobe.exe"))
    try:
        checksum_text = _read_url(FFMPEG_CHECKSUM_URL).decode("ascii", errors="ignore")
    except OSError:
        checksum_text = ""
    latest_ffmpeg_hash = next(
        (word.lower() for word in checksum_text.split() if len(word) == 64 and all(c in "0123456789abcdefABCDEF" for c in word)),
        None,
    )
    if latest_ffmpeg_hash is None:
        if ffmpeg_ready and installed_ffmpeg_hash:
            latest_ffmpeg_hash = installed_ffmpeg_hash
            log.warning("FFmpeg update check unavailable; keeping the verified local version.")
        else:
            raise RuntimeError("The official FFmpeg checksum could not be read.")
    if not ffmpeg_ready or installed_ffmpeg_hash != latest_ffmpeg_hash:
        _install_ffmpeg(bin_folder, (lambda value: progress_callback(value, "Updating FFmpeg")) if progress_callback else None)
    elif progress_callback:
        progress_callback(50, "FFmpeg is up to date")

    if progress_callback:
        progress_callback(74, "Checking Chromium")
    _install_chromium(
        browser_dir,
        (lambda value: progress_callback(value, "Updating Chromium")) if progress_callback else None,
    )
    if progress_callback:
        progress_callback(100, "Ready", status="ready")
    log.success("External dependencies are ready in %s", bin_folder)
