"""Install the newest DowFlow Setup published on the GitHub release.

An installed edition checks the ``latest`` release of the DowFlow repository,
downloads the Setup that matches the edition it is running from and starts it.
Inno Setup closes DowFlow, replaces the files under ``%LOCALAPPDATA%\\DowFlow``
and restarts the app, so the user never copies a Setup by hand. Nothing is
downloaded from anywhere else, and a source checkout never updates itself
through this path: ``launcher.py`` already owns the Git/ZIP update.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from config import IS_FROZEN, SUBPROCESS_CREATION_FLAGS

GITHUB_OWNER = "diego1505-Art"
GITHUB_REPO = "DowFlow"
RELEASES_API = (
    f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
)

# One Setup asset per edition, named exactly like build_export.EDITIONS writes
# them. test_update keeps both lists in sync.
RELEASE_ASSETS: dict[str, str] = {
    "all": "DowFlow-Setup.exe",
    "video": "DowFlow-Video-Setup.exe",
    "music": "DowFlow-Music-Setup.exe",
    "film": "DowFlow-Films-Setup.exe",
    "anime": "DowFlow-Anime-Setup.exe",
}

REQUEST_TIMEOUT = 15.0
# A Setup is tens of megabytes; anything this small is an error page, not an app.
_MIN_SETUP_BYTES = 1024 * 64


def setup_asset_name(scope: str) -> str:
    """Release asset that installs the edition named by ``scope``."""
    return RELEASE_ASSETS.get(scope, RELEASE_ASSETS["all"])


def installed_at() -> float | None:
    """When this executable was installed, or None outside an installed build."""
    if not IS_FROZEN:
        return None
    try:
        return Path(sys.executable).stat().st_mtime
    except OSError:
        return None


def find_setup_asset(release: dict[str, Any], scope: str) -> dict[str, Any] | None:
    wanted = setup_asset_name(scope)
    assets = release.get("assets")
    if not isinstance(assets, list):
        return None
    for asset in assets:
        if isinstance(asset, dict) and asset.get("name") == wanted:
            return asset
    return None


def release_timestamp(release: dict[str, Any]) -> float | None:
    """When GitHub published the release, in epoch seconds."""
    for key in ("published_at", "created_at"):
        raw = release.get(key)
        if not isinstance(raw, str) or not raw.strip():
            continue
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
    return None


def _empty(available: bool = False, error: str | None = None) -> dict[str, Any]:
    return {
        "available": available,
        "version": "",
        "name": "",
        "url": "",
        "size": 0,
        "notes": "",
        "error": error,
    }


def select_update(
    release: dict[str, Any],
    scope: str,
    installed_mtime: float | None,
) -> dict[str, Any]:
    """Decide whether the release holds a Setup newer than the installed app."""
    if not isinstance(release, dict):
        return _empty(error="GitHub did not return a release.")
    asset = find_setup_asset(release, scope)
    if asset is None:
        return _empty(
            error=(
                f"The release has no {setup_asset_name(scope)} asset yet; "
                "install the Setup published with the newest release."
            )
        )
    url = str(asset.get("browser_download_url") or "").strip()
    if not url:
        return _empty(error="The release asset has no download link.")
    published = release_timestamp(release)
    if installed_mtime is not None and published is not None:
        # The installed executable is written by Inno Setup, so its mtime is
        # the install date: an older or equal release needs no download.
        if published <= installed_mtime:
            return _empty()
    notes = release.get("body")
    result = _empty(available=True)
    result.update(
        {
            "version": str(release.get("tag_name") or release.get("name") or ""),
            "name": str(asset.get("name") or ""),
            "url": url,
            "size": int(asset.get("size") or 0),
            "notes": (notes if isinstance(notes, str) else "")[:2000],
        }
    )
    return result


def check_for_update(
    scope: str,
    *,
    session: Any | None = None,
    installed_mtime: float | None = None,
) -> dict[str, Any]:
    """Ask the GitHub release for a Setup newer than this install."""
    if installed_mtime is None:
        installed_mtime = installed_at()
    if installed_mtime is None:
        return _empty(error="Only an installed DowFlow can update itself.")
    http = session or requests
    try:
        response = http.get(
            RELEASES_API,
            timeout=REQUEST_TIMEOUT,
            headers={"Accept": "application/vnd.github+json"},
        )
        response.raise_for_status()
        release = response.json()
    except Exception as exc:  # requests errors and malformed JSON
        return _empty(error=f"GitHub is unreachable: {exc}")
    return select_update(release, scope, installed_mtime)


def _setup_destination(name: str) -> Path:
    safe = Path(name).name or "DowFlow-Setup.exe"
    return Path(tempfile.gettempdir()) / safe


def download_setup(
    url: str,
    destination: Path | None = None,
    *,
    session: Any | None = None,
) -> Path:
    """Stream the release Setup into the temporary folder."""
    http = session or requests
    target = destination or _setup_destination(urlparse(url).path)
    partial = target.with_suffix(target.suffix + ".part")
    written = 0
    try:
        response = http.get(url, stream=True, timeout=REQUEST_TIMEOUT)
        try:
            response.raise_for_status()
            with partial.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1 << 16):
                    if not chunk:
                        continue
                    handle.write(chunk)
                    written += len(chunk)
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        if written < _MIN_SETUP_BYTES:
            raise RuntimeError("The downloaded Setup is incomplete.")
        partial.replace(target)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    return target


def start_installer(setup: Path) -> None:
    """Run the Setup silently; Inno closes DowFlow and restarts it afterwards."""
    subprocess.Popen(
        [
            str(setup),
            "/SILENT",
            "/SUPPRESSMSGBOXES",
            "/CLOSEAPPLICATIONS",
            "/RESTARTAPPLICATIONS",
        ],
        close_fds=True,
        creationflags=SUBPROCESS_CREATION_FLAGS,
    )


def install_latest(
    scope: str,
    *,
    session: Any | None = None,
    installed_mtime: float | None = None,
) -> dict[str, Any]:
    """Download the newest Setup for this edition and start it."""
    update = check_for_update(
        scope, session=session, installed_mtime=installed_mtime
    )
    if not update["available"]:
        raise RuntimeError(update.get("error") or "DowFlow is already up to date.")
    setup = download_setup(
        update["url"],
        _setup_destination(update["name"]),
        session=session,
    )
    start_installer(setup)
    return {**update, "installer": str(setup)}
