"""
DowFlow — Music service for the DowFlow Music (Liner) app.

Download audio (MP3/FLAC, etc.) from YouTube via yt-dlp, list the downloaded
tracks, and automatically fetch album artwork (public Deezer API, falling back
to the YouTube thumbnail).
"""
from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import requests

import download_manager
from config import AUDIO_EXTENSIONS, get_download_path
from logger import get_logger
from music_dataset import get_dataset

log = get_logger("music")

# Tests and the desktop player can override the folder; otherwise Music uses
# the single download root directly.
MUSIC_FOLDER: Path | None = None


def _music_folder() -> Path:
    return MUSIC_FOLDER or get_download_path()

COVER_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
DEEZER_SEARCH_URL = "https://api.deezer.com/search"
_LIBRARY_PROMO_SUFFIX = re.compile(
    r"[-_\s]*(?:official[-_\s]+(?:music[-_\s]+)?video|official[-_\s]+audio|"
    r"lyrics?(?:[-_\s]+video)?|lyric[-_\s]+video|music[-_\s]+video|audio)$",
    re.IGNORECASE,
)

# Queries used to build the "Popular music" list (without a dataset).
_POPULAR_QUERIES = (
    "Top hits 2026",
    "popular music 2026",
    "Top 50 France 2026",
    "best songs 2026",
)
_POPULAR_TTL_SECONDS = 1800.0
_popular_cache: tuple[float, list[dict[str, Any]]] | None = None


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _thumb_for(video_id: str) -> str:
    """Return the standard YouTube thumbnail for a video ID."""
    return f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"


def _video_id_from_url(url: str) -> str | None:
    """Extract a YouTube video ID from a watch, youtu.be, or Shorts URL."""
    try:
        parsed = urlparse(url)
    except Exception:
        return None
    host = (parsed.netloc or "").lower().replace("www.", "")
    if "youtu.be" in host:
        candidate = parsed.path.strip("/").split("/")[0]
        return candidate or None
    if "youtube.com" in host:
        if parsed.path.startswith("/watch"):
            from urllib.parse import parse_qs
            values = parse_qs(parsed.query).get("v")
            return values[0] if values else None
        for marker in ("/shorts/", "/embed/", "/v/"):
            if marker in parsed.path:
                return parsed.path.split(marker, 1)[1].split("/")[0] or None
    return None


def _music_track_payload(folder: Path, path: Path, artist: str, title: str) -> dict[str, Any]:
    """Describe an audio file served through /media/ with its optional cover."""
    cover_name = None
    for ext in COVER_EXTENSIONS:
        candidate = folder / f"{path.stem}{ext}"
        if candidate.is_file():
            cover_name = candidate.name
            break
    return {
        "filename": path.name,
        "title": title or path.stem,
        "artist": artist,
        "audio_url": f"/media/{quote(path.name)}",
        "cover_url": f"/media/{quote(cover_name)}" if cover_name else None,
    }


def _library_track_metadata(stem: str) -> tuple[str, str, str]:
    """Clean a YouTube filename and produce a stable artist/title key."""
    raw_artist = ""
    raw_title = stem.strip()
    if "---" in raw_title:
        raw_artist, raw_title = raw_title.split("---", 1)
        raw_artist = re.sub(r"[-_]+", " ", raw_artist).strip()

    raw_title = _LIBRARY_PROMO_SUFFIX.sub("", raw_title).strip(" -_[]()")
    title = re.sub(r"[-_]+", " ", raw_title).strip()
    normalized = unicodedata.normalize(
        "NFKD", f"{raw_artist} {title}"
    ).encode("ascii", "ignore").decode("ascii").lower()
    key = re.sub(r"[^a-z0-9]+", " ", normalized).strip()
    return raw_artist, title, key


# ─────────────────────────────────────────────────────────────────────────────
#  Search / popular tracks
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
#  Album artwork
# ─────────────────────────────────────────────────────────────────────────────

def fetch_cover_url(artist: str | None, title: str | None) -> str | None:
    """Get the cover URL from the Deezer API (no key required), or return None."""
    dataset = get_dataset()
    if dataset is not None and dataset.available():
        try:
            url = dataset.cover_url(artist or "", title or "")
            if url:
                return url
        except Exception:
            pass

    title = (title or "").strip()
    if not title:
        return None

    artist = (artist or "").strip()
    query = " ".join(part for part in (title, artist) if part)
    try:
        response = requests.get(
            DEEZER_SEARCH_URL, params={"q": query, "limit": 1}, timeout=10
        )
        response.raise_for_status()
        items = response.json().get("data") or []
        if items:
            album = items[0].get("album") or {}
            return (
                album.get("cover_xl")
                or album.get("cover_big")
                or album.get("cover_medium")
            )
    except Exception as exc:
        log.debug("[music] Deezer unavailable for '%s': %s", title, exc)
    return None


_COVER_CACHE: dict[tuple[str, str], tuple[float, str | None]] = {}
_COVER_TTL_SECONDS = 600.0


def _normalize_text(value: str) -> str:
    """Fold a title so "poster boy" and "poster-boy" compare equal."""
    folded = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", folded.lower()).strip()


def _save_cover_image(media_path: str, cover_url: str | None, video_id: str | None) -> str | None:
    """Save the cover beside the audio file, falling back to a YouTube thumbnail."""
    candidates = [cover_url] if cover_url else []
    if video_id:
        candidates.append(f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg")
        candidates.append(f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg")
        candidates.append(_thumb_for(video_id))

    target = os.path.splitext(media_path)[0] + ".jpg"
    for url in candidates:
        if not url:
            continue
        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            if not response.content:
                continue
            with open(target, "wb") as handle:
                handle.write(response.content)
            return target
        except Exception as exc:
            log.debug("[music] Cover art unavailable (%s): %s", url[:60], exc)
    return None


# ─────────────────────────────────────────────────────────────────────────────
#  Download
# ─────────────────────────────────────────────────────────────────────────────

def download_music_track(
    url: str,
    output_path: str | None = None,
    audio_format: str = "mp3",
    with_cover: bool = True,
    title: str | None = None,
    artist: str | None = None,
    progress_hook=None,
) -> dict[str, Any]:
    """Download a track as audio (with optional cover) directly into the root."""
    from playlist import download_media

    base_output = output_path or str(get_download_path())
    result = download_media(
        url,
        output_path=base_output,
        download_type="audio",
        audio_format=audio_format,
        progress_hook=progress_hook,
    )

    filepath = result.get("filepath")
    video_id = _video_id_from_url(url)
    cover_source = None

    if filepath and os.path.isfile(filepath):
        download_manager.record_download(
            url,
            title or result.get("title"),
            artist,
            filepath,
        )
        if with_cover:
            # The YouTube thumbnail is immediate. Only fall back to Deezer for
            # non-YouTube URLs (or when the thumbnail is unavailable): waiting
            # on a 10-second Deezer request made finished downloads look stuck.
            cover_path = _save_cover_image(filepath, None, video_id)
            if not cover_path:
                cover_source = fetch_cover_url(artist, title or result.get("title"))
                if cover_source:
                    result["cover_url"] = cover_source
                    cover_path = _save_cover_image(filepath, cover_source, None)
            if cover_path:
                cover_relative = os.path.relpath(cover_path, base_output).replace("\\", "/")
                result["cover_path"] = cover_path
                result["cover_url"] = f"/media/{cover_relative}"
        elif not result.get("cover_path"):
            cover_source = fetch_cover_url(artist, title or result.get("title"))
            if cover_source:
                result["cover_path"] = cover_source

    return result


def find_library_track(title: str | None, artist: str | None = None) -> dict[str, Any] | None:
    """Return the track already stored in the Music folder, if there is one.

    Used to avoid downloading the same song twice when it is requested again.
    """
    wanted_title = _normalize_text(title or "")
    if not wanted_title:
        return None
    wanted_artist = _normalize_text(artist or "")
    folder = _music_folder()

    def artist_matches(candidate: str) -> bool:
        normalized = _normalize_text(candidate)
        if not wanted_artist or not normalized:
            return True
        return wanted_artist in normalized or normalized in wanted_artist

    # Indexed downloads first: they carry the original artist/title metadata.
    for entry in download_manager.present_entries(folder):
        path = Path(entry["path"])
        if not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS:
            continue
        if _normalize_text(entry["title"] or path.stem) != wanted_title:
            continue
        if not artist_matches(entry["artist"]):
            continue
        return _music_track_payload(folder, path, entry["artist"], entry["title"])

    # Files downloaded before the index existed, or copied by hand.
    try:
        entries = list(folder.iterdir())
    except OSError:
        return None
    for path in entries:
        if not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS:
            continue
        file_artist, file_title, _ = _library_track_metadata(path.stem)
        if _normalize_text(file_title or path.stem) != wanted_title:
            continue
        if not artist_matches(file_artist):
            continue
        return _music_track_payload(folder, path, file_artist, file_title)
    return None


def ensure_covers(limit: int = 60) -> int:
    """Write the missing cover art for tracks already in the Music folder."""
    folder = _music_folder()
    try:
        entries = sorted(folder.iterdir())
    except OSError:
        return 0
    created = 0
    for path in entries:
        if created >= limit:
            break
        if not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS:
            continue
        if any((folder / f"{path.stem}{ext}").is_file() for ext in COVER_EXTENSIONS):
            continue
        artist, title, _ = _library_track_metadata(path.stem)
        cover_url = fetch_cover_url(artist or None, title or path.stem)
        if _save_cover_image(str(path), cover_url, None):
            created += 1
    return created


# ─────────────────────────────────────────────────────────────────────────────
#  Local library (previously downloaded tracks)
# ─────────────────────────────────────────────────────────────────────────────

