"""Small, deterministic strategy selector for yt-dlp downloads.

Phase 1 deliberately contains no aria2c, database, UI, or network probing. The
selector only decides how many native yt-dlp fragment connections to use. When
media metadata is unavailable, the safe default is the existing fragmented
strategy so manifests and adaptive streams keep their current behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Mapping, Protocol
from urllib.parse import urlparse


DIRECT_MEDIA_EXTENSIONS = frozenset(
    {
        ".aac", ".avi", ".flac", ".m4a", ".mka", ".mkv", ".mov", ".mp3",
        ".mp4", ".mpeg", ".mpg", ".ogg", ".opus", ".wav", ".webm", ".wmv",
    }
)


@dataclass(frozen=True)
class MediaInfo:
    """Metadata available to the selector, without forcing an extra request."""

    url: str
    is_fragmented: bool | None = None
    estimated_size: int | None = None
    cdn: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_ytdlp_info(cls, url: str, info: Mapping[str, Any]) -> "MediaInfo":
        """Build metadata when a caller already has yt-dlp's info dictionary."""
        formats = info.get("formats")
        is_fragmented: bool | None = None
        if isinstance(formats, list) and formats:
            protocols = {
                str(item.get("protocol", "")).lower()
                for item in formats
                if isinstance(item, Mapping)
            }
            is_fragmented = bool(protocols & {"m3u8", "m3u8_native", "http_dash_segments", "dash"})
        size = info.get("filesize") or info.get("filesize_approx")
        try:
            estimated_size = int(size) if size is not None else None
        except (TypeError, ValueError):
            estimated_size = None
        return cls(
            url=url,
            is_fragmented=is_fragmented,
            estimated_size=estimated_size,
            cdn=str(info.get("protocol")) if info.get("protocol") else None,
            raw=info,
        )

    @classmethod
    def infer_from_url(cls, url: str) -> "MediaInfo":
        """Infer only facts that are safe to know without a network request."""
        path = PurePosixPath(urlparse(url).path.lower())
        suffix = path.suffix
        if suffix in DIRECT_MEDIA_EXTENSIONS:
            return cls(url=url, is_fragmented=False)
        return cls(url=url, is_fragmented=None)


class DownloadStrategy(Protocol):
    name: str

    def yt_dlp_options(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class YtdlpFragmentsStrategy:
    """Native yt-dlp fragment downloader for manifests and unknown sources."""

    connections: int = 16
    name: str = "yt-dlp-fragments"

    def yt_dlp_options(self) -> dict[str, Any]:
        return {"concurrent_fragment_downloads": max(1, int(self.connections))}


@dataclass(frozen=True)
class YtdlpMonoStrategy:
    """Single native yt-dlp connection for a clearly direct media file."""

    name: str = "yt-dlp-mono"

    def yt_dlp_options(self) -> dict[str, Any]:
        return {"concurrent_fragment_downloads": 1}


class StrategySelector:
    """Choose exactly one native yt-dlp strategy for a download."""

    def __init__(self, fragment_connections: int = 16) -> None:
        self.fragment_connections = max(1, int(fragment_connections))

    def choose(self, media_info: MediaInfo) -> DownloadStrategy:
        if media_info.is_fragmented is False:
            return YtdlpMonoStrategy()
        # Unknown is intentionally conservative: a manifest may be hidden
        # behind a URL without an extension, so preserve native fragments.
        return YtdlpFragmentsStrategy(self.fragment_connections)

    def choose_from_ytdlp_info(
        self, url: str, info: Mapping[str, Any]
    ) -> DownloadStrategy:
        return self.choose(MediaInfo.from_ytdlp_info(url, info))
