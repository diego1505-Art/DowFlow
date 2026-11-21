"""DowFlow — download root, Music index and cookie imports.

Every download is written directly into the configured root. The Music index
(``dowflow_music_index.json``) lives in DowFlow's own data folder and records
where each track came from and whether it is still on disk, so a track deleted
by hand is never silently restored. Imported Netscape cookie exports are
copied to ``%APPDATA%\\DowFlow\\cookies``.
"""

from __future__ import annotations

import json
import re
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path

from config import DOWNLOAD_FOLDER, DOWFLOW_COOKIES_DIR, get_data_root, get_download_path

INDEX_FILENAME = "dowflow_music_index.json"
STATUS_PRESENT = "present"
STATUS_DELETED = "deleted"

_LOCK = threading.RLock()
_UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


# ── Download root ────────────────────────────────────────────────────────────

def download_root() -> Path:
    """Return the single folder every download is written into."""
    folder = get_download_path(required=False)
    return folder if folder is not None else DOWNLOAD_FOLDER


# ── Music index ──────────────────────────────────────────────────────────────

def index_path(root: Path | None = None) -> Path:
    """Return the Music index path inside DowFlow's data folder.

    ``root`` is an explicit override used by tests/tools; the application keeps
    the index beside its own config, never inside the download folder.
    """
    return Path(root or get_data_root()) / INDEX_FILENAME


def _migrate_legacy_index(target: Path) -> None:
    """Move an index left in the download folder to DowFlow's data folder."""
    if target.exists():
        return
    legacy = download_root() / INDEX_FILENAME
    if legacy == target or not legacy.is_file():
        return
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(legacy), str(target))
    except OSError:
        pass


def _index_file(index_root: Path | None = None) -> Path:
    target = index_path(index_root)
    if index_root is None:
        _migrate_legacy_index(target)
    return target


def _normalize_entry(item: dict) -> dict | None:
    url = str(item.get("url") or "").strip()
    if not url:
        return None
    return {
        "url": url,
        "title": str(item.get("title") or ""),
        "artist": str(item.get("artist") or ""),
        "path": str(item.get("path") or ""),
        "downloaded_at": str(item.get("downloaded_at") or ""),
        "status": STATUS_DELETED if item.get("status") == STATUS_DELETED else STATUS_PRESENT,
    }


def _read_index(path: Path) -> list[dict]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if isinstance(payload, dict):
        payload = payload.get("tracks") or []
    if not isinstance(payload, list):
        return []
    entries = []
    for item in payload:
        if isinstance(item, dict):
            entry = _normalize_entry(item)
            if entry is not None:
                entries.append(entry)
    return entries


def _write_index(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def load_index(index_root: Path | None = None) -> list[dict]:
    """Return every recorded Music entry (present and deleted)."""
    return _read_index(_index_file(index_root))


def find_entry(url: str, index_root: Path | None = None) -> dict | None:
    wanted = (url or "").strip()
    if not wanted:
        return None
    for entry in _read_index(_index_file(index_root)):
        if entry["url"] == wanted:
            return entry
    return None


def is_deleted(url: str, index_root: Path | None = None) -> bool:
    entry = find_entry(url, index_root)
    return bool(entry and entry["status"] == STATUS_DELETED)


def record_download(
    url: str,
    title: str | None,
    artist: str | None,
    path: str | Path,
    root: Path | None = None,
    index_root: Path | None = None,
) -> dict:
    """Record (or refresh) a Music download in the index."""
    wanted = (url or "").strip()
    if not wanted:
        raise ValueError("A download URL is required to update the Music index.")
    root_path = Path(root or download_root())
    target = Path(path)
    if not target.is_absolute():
        target = root_path / target
    entry = {
        "url": wanted,
        "title": (title or "").strip(),
        "artist": (artist or "").strip(),
        "path": str(target),
        "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": STATUS_PRESENT,
    }
    with _LOCK:
        index_file = _index_file(index_root)
        entries = _read_index(index_file)
        for existing in entries:
            if existing["url"] == wanted:
                existing.update(entry)
                entry = existing
                break
        else:
            entries.append(entry)
        _write_index(index_file, entries)
    return dict(entry)


def mark_deleted(
    url: str | None = None,
    filename: str | None = None,
    path: str | Path | None = None,
    root: Path | None = None,
    index_root: Path | None = None,
) -> bool:
    """Flag matching entries as deleted after a manual or in-app removal."""
    wanted_name = Path(filename).name.casefold() if filename else None
    wanted_path = str(path).casefold() if path else None
    with _LOCK:
        index_file = _index_file(index_root)
        entries = _read_index(index_file)
        changed = False
        for entry in entries:
            if entry["status"] != STATUS_PRESENT:
                continue
            entry_path = entry["path"]
            if url and entry["url"] == url.strip():
                pass
            elif wanted_path and entry_path.casefold() == wanted_path:
                pass
            elif wanted_name and Path(entry_path).name.casefold() == wanted_name:
                pass
            else:
                continue
            entry["status"] = STATUS_DELETED
            changed = True
        if changed:
            _write_index(index_file, entries)
        return changed


def mark_missing(
    root: Path | None = None, index_root: Path | None = None
) -> list[dict]:
    """Mark present entries whose file no longer exists on disk."""
    root_path = Path(root or download_root())
    with _LOCK:
        index_file = _index_file(index_root)
        entries = _read_index(index_file)
        changed = False
        for entry in entries:
            if entry["status"] != STATUS_PRESENT or not entry["path"]:
                continue
            candidate = Path(entry["path"])
            if not candidate.is_absolute():
                candidate = root_path / candidate
            if not candidate.is_file():
                entry["status"] = STATUS_DELETED
                changed = True
        if changed:
            _write_index(index_file, entries)
        return entries


def present_entries(
    root: Path | None = None, index_root: Path | None = None
) -> list[dict]:
    """Return indexed entries whose file is still present."""
    return [
        entry
        for entry in mark_missing(root, index_root=index_root)
        if entry["status"] == STATUS_PRESENT
    ]


# ── Netscape cookie imports ──────────────────────────────────────────────────

def parse_netscape_cookies(text: str) -> list[str]:
    """Return the cookie domains of a Netscape export, or [] when invalid."""
    domains: list[str] = []
    valid_lines = 0
    for raw_line in (text or "").splitlines():
        line = raw_line.strip("\r\n")
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_"):]
        elif not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != 7:
            return []
        domain = fields[0].strip().lstrip(".").lower()
        name = fields[5].strip()
        secure = fields[3].strip().upper()
        if not domain or not name or secure not in {"TRUE", "FALSE"}:
            return []
        valid_lines += 1
        if domain not in domains:
            domains.append(domain)
    return domains if valid_lines else []


def import_cookie_file(source: str | Path, destination_dir: str | Path | None = None) -> dict:
    """Validate a Netscape cookie export and copy it into DowFlow's cookie folder."""
    source_path = Path(source).expanduser()
    try:
        text = source_path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        raise ValueError(f"The cookie file could not be read: {error}") from error

    domains = parse_netscape_cookies(text)
    if not domains:
        raise ValueError(
            "This file is not a Netscape cookie export (7 tab-separated fields per line)."
        )

    target_dir = Path(destination_dir or DOWFLOW_COOKIES_DIR)
    target_dir.mkdir(parents=True, exist_ok=True)
    name = _UNSAFE_FILENAME.sub("_", source_path.name).strip() or "cookies.txt"
    if not name.casefold().endswith(".txt"):
        name = f"{name}.txt"
    target = target_dir / name
    temporary = target.with_suffix(".tmp")
    shutil.copyfile(source_path, temporary)
    temporary.replace(target)
    return {"filename": name, "path": str(target), "domains": domains}


def list_imported_cookies(destination_dir: str | Path | None = None) -> list[str]:
    target_dir = Path(destination_dir or DOWFLOW_COOKIES_DIR)
    try:
        return sorted(
            path.name
            for path in target_dir.iterdir()
            if path.is_file() and path.suffix.lower() == ".txt"
        )
    except OSError:
        return []
