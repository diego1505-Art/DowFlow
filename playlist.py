import logging
import os
import re
import shutil
import time
from typing import Any, Callable
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

import yt_dlp

from config import (
    VIDEO_EXTENSIONS,
    AUDIO_EXTENSIONS,
    VIDEO_OUTPUT_FORMATS,
    AUDIO_OUTPUT_FORMATS,
    VIDEO_QUALITIES,
    LANGUAGES,
    YOUTUBE_COOKIES_FILE,
    CONNECTIONS_OVERRIDE,
    get_download_path,
    normalize_language,
    detect_language_from_url,
)
from utils import _resolve_ffmpeg_dir, pick_connection_tier, pick_proxy, yt_dlp_runtime_options
from logger import get_logger
from database import download_start, download_finish
from downloader.strategy_selector import MediaInfo, StrategySelector

log = get_logger("playlist")

IGNORED_EXTENSIONS = {".part", ".ytdl", ".jpg", ".jpeg", ".png", ".webp", ".description"}
VALID_DOWNLOAD_TYPES = {"audio", "video"}
CONTAINER_SEGMENTS = {"anime", "watch", "video", "videos", "embed", "episode", "show"}

# ── Backward compatibility: map legacy quality keys to VIDEO_QUALITIES ───────
_LEGACY_QUALITY_MAP = {
    "best": "best",
    "ultra": "2160p",
    "qhd": "1440p",
    "high": "1080p",
    "medium": "720p",
    "low": "480p",
    "360": "360p",
    "240": "240p",
}

_ADAPTIVE_QUALITY_ORDER = ["4320p", "2160p", "1440p", "1080p", "720p", "480p", "360p", "240p"]
_ADAPTIVE_TIME_THRESHOLDS = {
    "4320p": 180,  # 3 min
    "2160p": 300,  # 5 min
    "1440p": 600,  # 10 min
    "1080p": 900,  # 15 min
    "720p": 1200,  # 20 min
    "480p": 1500,  # 25 min
    "360p": 1800,  # 30 min
    "240p": 2100,  # 35 min
}

# Real-time monitoring: observation period before deciding to lower quality.
_ADAPTIVE_GRACE_SECONDS = 10.0


class _AdaptiveDowngrade(BaseException):
    """Interrupt a download so it can restart at a lower quality.

    Inherit from BaseException instead of Exception so yt-dlp's internal
    `except Exception` handlers do not catch it; only `_ydlp_download` should.
    """

    def __init__(self, quality: str, note: str) -> None:
        super().__init__(note)
        self.quality = quality
        self.note = note


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "media"


def _friendly_cookie_error(error: Exception) -> str | None:
    message = str(error).lower()
    if "could not copy chrome cookie database" in message or ("permission denied" in message and "cookies" in message):
        return (
            "yt-dlp cannot read Chrome's cookie database because Chrome or Windows has locked it "
            "(yt-dlp issue #7271). Close all Chrome processes and retry, or launch Chrome with "
            "--disable-features=LockProfileCookieDatabase. Alternatively, export cookies in "
            "Netscape format to the matching site cookie file or cookies.txt in the project root. "
            "This file grants access to your account; do not share or publish it."
        )
    if any(t in message for t in ("sign in to confirm", "not a bot", "login", "log in", "inaccessible")):
        return (
            "The site requires a signed-in session or is blocking access. Sign in to the site in "
            "Chrome, or provide a valid site-specific Netscape cookie file."
        )
    return None


def _resolve_cookie_file(url: str | None = None) -> str | None:
    """Find a Netscape cookie export for the requested site, without mixing sessions."""
    host = (urlparse(url).hostname or "").lower() if url else "youtube.com"
    if host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com"):
        site_names = ("youtube_cookies.txt", "youtube.com_cookies.txt")
        env_name = "DOWFLOW_YOUTUBE_COOKIES"
    elif host == "instagram.com" or host.endswith(".instagram.com"):
        site_names = ("instagram_cookies.txt", "instagram.com_cookies.txt")
        env_name = "DOWFLOW_INSTAGRAM_COOKIES"
    elif host == "tiktok.com" or host.endswith(".tiktok.com"):
        site_names = ("tiktok_cookies.txt", "tiktok.com_cookies.txt")
        env_name = "DOWFLOW_TIKTOK_COOKIES"
    else:
        domain = host.removeprefix("www.")
        site_names = (f"{domain}_cookies.txt",) if domain else ()
        env_name = None

    configured_path = os.environ.get(env_name) if env_name else None
    if configured_path:
        cookie_path = Path(configured_path).expanduser()
        return str(cookie_path) if cookie_path.is_file() else None

    candidates = [YOUTUBE_COOKIES_FILE.with_name(name) for name in site_names]
    for cookie_path in candidates:
        if cookie_path.is_file():
            return str(cookie_path)

    configured_path = os.environ.get("DOWFLOW_COOKIES")
    if configured_path:
        cookie_path = Path(configured_path).expanduser()
        return str(cookie_path) if cookie_path.is_file() else None

    generic_cookie_path = YOUTUBE_COOKIES_FILE.with_name("cookies.txt")
    if generic_cookie_path.is_file():
        return str(generic_cookie_path)
    return None


def _needs_session(error: Exception) -> bool:
    """Check whether the site requires a signed-in session or blocks access."""
    message = str(error).lower()
    return any(
        token in message
        for token in (
            "sign in to confirm",
            "not a bot",
            "could not copy chrome cookie database",
            "cookie",
            "login",
            "log in",
            "inaccessible",
            "inaccessibles",
            "forbidden",
            "403",
        )
    )


def _cookie_retry_options(ydl_opts: dict[str, Any], cookie_file: str | None) -> dict[str, Any]:
    """Build retry options using a Netscape cookie file or the Chrome profile."""
    retry_opts = dict(ydl_opts)
    retry_opts.pop("cookiesfrombrowser", None)
    if cookie_file:
        retry_opts["cookiefile"] = cookie_file
    else:
        retry_opts.update(yt_dlp_runtime_options(include_browser_cookies=True))
    return retry_opts


def _derive_series_slug(parsed_url) -> str:
    raw_segments = [segment for segment in parsed_url.path.split("/") if segment.strip()]
    segments = [_slugify(segment) for segment in raw_segments if _slugify(segment)]
    if not segments:
        return "remote"
    if len(segments) >= 2 and segments[0] in CONTAINER_SEGMENTS:
        return segments[1]
    return segments[-1]


def _build_output_folder(url: str, base_output_path: str) -> str:
    """Create an output folder based on the domain (YouTube, Instagram, Twitter, etc.)."""
    parsed = urlparse(url)
    domain = parsed.netloc.lower().replace("www.", "") or "remote"

    # Clean the domain name for the folder (e.g. youtube.com -> youtube).
    folder_name = domain.split(".")[0] if "." in domain else domain
    target_dir = os.path.join(base_output_path, folder_name)

    # Keep a deeper folder structure for complex sites such as anime catalogs.
    query = parse_qs(parsed.query)
    stable_id = None
    for key in ("anime_id", "series_id", "show_id", "id"):
        values = query.get(key)
        if values and values[0].strip():
            stable_id = _slugify(values[0])
            break

    if stable_id:
        return os.path.join(target_dir, f"id-{stable_id}")

    return target_dir


def _relative_download_path(filepath: str, base_output_path: str) -> str:
    return os.path.relpath(filepath, start=base_output_path).replace("\\", "/")


def _collect_created_files(output_path: str, before_files: set[str]) -> list[str]:
    created_files: list[str] = []
    for name in os.listdir(output_path):
        full_path = os.path.join(output_path, name)
        if os.path.isfile(full_path) and name not in before_files:
            created_files.append(full_path)
    created_files.sort(key=os.path.getmtime, reverse=True)
    return created_files


def _candidate_filepaths_from_info(info: dict[str, Any], output_path: str) -> list[str]:
    candidates: list[str] = []

    requested_downloads = info.get("requested_downloads")
    if isinstance(requested_downloads, list):
        for item in requested_downloads:
            if isinstance(item, dict):
                filepath = item.get("filepath")
                if isinstance(filepath, str) and filepath:
                    candidates.append(filepath)

    for key in ("filepath", "_filename"):
        value = info.get(key)
        if isinstance(value, str) and value:
            candidates.append(value)

    title = info.get("title")
    ext = info.get("ext")
    if isinstance(title, str) and title:
        if isinstance(ext, str) and ext:
            candidates.append(os.path.join(output_path, f"{title}.{ext}"))
        for known_ext in sorted(VIDEO_EXTENSIONS | AUDIO_EXTENSIONS):
            candidates.append(os.path.join(output_path, f"{title}{known_ext}"))

    unique_candidates: list[str] = []
    seen: set[str] = set()
    for path in candidates:
        normalized = os.path.normpath(path)
        if normalized not in seen:
            unique_candidates.append(normalized)
            seen.add(normalized)

    return unique_candidates


def _pick_media_file(created_files: list[str], download_type: str) -> str | None:
    allowed_exts = AUDIO_EXTENSIONS if download_type == "audio" else VIDEO_EXTENSIONS | AUDIO_EXTENSIONS

    for path in created_files:
        suffix = os.path.splitext(path)[1].lower()
        if suffix in IGNORED_EXTENSIONS:
            continue
        if suffix in allowed_exts:
            return path

    for path in created_files:
        suffix = os.path.splitext(path)[1].lower()
        if suffix not in IGNORED_EXTENSIONS:
            return path

    return None


def _resolve_downloaded_file(info: dict[str, Any], created_files: list[str], output_path: str, download_type: str) -> str | None:
    for candidate in _candidate_filepaths_from_info(info, output_path):
        if os.path.isfile(candidate):
            suffix = os.path.splitext(candidate)[1].lower()
            if suffix not in IGNORED_EXTENSIONS:
                return candidate

    return _pick_media_file(created_files, download_type)


# ──────────────────────────────────────────────────────────────────────────────
# NEW: Build the yt-dlp format from the new options.
# ──────────────────────────────────────────────────────────────────────────────

def _resolve_quality_key(raw_quality: str) -> str:
    """Convert a legacy or current quality key to its canonical VIDEO_QUALITIES key."""
    q = (raw_quality or "best").strip().lower()
    if q in VIDEO_QUALITIES:
        return q
    if q in _LEGACY_QUALITY_MAP:
        return _LEGACY_QUALITY_MAP[q]
    # Example: "1080" -> "1080p".
    if q.rstrip("p") in {str(k.rstrip("p")) for k in VIDEO_QUALITIES}:
        for k in VIDEO_QUALITIES:
            if k.rstrip("p") == q.rstrip("p"):
                return k
    return "best"


# Speed-test endpoints, tried in order. Some networks/ISPs block Cloudflare (403)
# or other hosts, so use the first usable measurement.
_SPEED_TEST_URLS = (
    "https://speed.cloudflare.com/__down?bytes=5000000",
    "https://proof.ovh.net/files/1Mb.dat",
    "https://github.com/git/git/archive/refs/tags/v2.43.0.tar.gz",
    "https://www.google.com/favicon.ico",
)


def _measure_network_speed_mbps(url: str | None = None, timeout_seconds: float = 8.0) -> float:
    """Measure real network speed (about 5 MB) to select an appropriate quality."""
    candidates = (url,) if url else _SPEED_TEST_URLS
    deadline = time.monotonic() + 10.0
    for candidate in candidates:
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            start = time.time()
            with urlopen(candidate, timeout=min(timeout_seconds, remaining)) as resp:
                # Read a representative sample (5 MB) to avoid misleading results
                # from small files such as favicons that do not reflect bandwidth.
                chunk = resp.read(5 * 1024 * 1024)
                elapsed = max(time.time() - start, 0.001)
            if chunk:
                return (len(chunk) * 8.0 / (elapsed * 1000000.0))
        except Exception:
            continue
    return 0.0


# ── Parallel connection tier (refined at startup) ────────────────────────────
# Conservative default, used until capacity detection has run (tests or
# programmatic use).
_CONNECTION_TIER = 16
_CONNECTION_TIER_DETECTED = False


def get_connection_tier() -> int:
    """Return the current connection tier (8/16/32/64/128)."""
    return _CONNECTION_TIER


def detect_connection_tier(speed_mbps: float | None = None, force: bool = False) -> int:
    """Detect machine capacity and set the connection tier.

    Combine CPU capacity (logical cores) and network speed to choose a tier of
    8/16/32/64/128 without overwhelming the machine. Override with the
    DOWFLOW_CONNECTIONS environment variable.
    """
    global _CONNECTION_TIER, _CONNECTION_TIER_DETECTED
    if _CONNECTION_TIER_DETECTED and not force:
        return _CONNECTION_TIER

    override = 0
    if CONNECTIONS_OVERRIDE:
        try:
            override = int(CONNECTIONS_OVERRIDE)
        except ValueError:
            log.warning("[perf] Invalid DOWFLOW_CONNECTIONS value (%r); ignored.", CONNECTIONS_OVERRIDE)

    if override > 0:
        _CONNECTION_TIER = max(1, override)
        log.info("[perf] Forced connections: x%d (DOWFLOW_CONNECTIONS)", _CONNECTION_TIER)
    else:
        cores = os.cpu_count() or 2
        measured = speed_mbps if speed_mbps is not None else _measure_network_speed_mbps()
        _CONNECTION_TIER = pick_connection_tier(cores, measured)
        log.info(
            "[perf] Connection tier: x%d (%d cores, speed %s)",
            _CONNECTION_TIER,
            cores,
            f"{measured:.1f} Mbps" if measured > 0 else "not detected",
        )

    _CONNECTION_TIER_DETECTED = True
    return _CONNECTION_TIER


def _tier_for_resolution(resolution: int) -> str | None:
    """Return the quality tier (240p to 8K) for an actual video resolution."""
    if not resolution or resolution <= 0:
        return None
    for key in reversed(_ADAPTIVE_QUALITY_ORDER):  # From lowest to highest.
        max_height = VIDEO_QUALITIES.get(key, {}).get("max_height")
        if max_height and resolution <= max_height:
            return key
    return None


def _next_lower_quality(quality_key: str) -> str | None:
    """Return the next lower tier, or None if already at the lowest tier."""
    try:
        index = _ADAPTIVE_QUALITY_ORDER.index(quality_key)
    except ValueError:
        return None
    if index + 1 >= len(_ADAPTIVE_QUALITY_ORDER):
        return None
    return _ADAPTIVE_QUALITY_ORDER[index + 1]


def _progress_resolution(progress: dict[str, Any]) -> int:
    """Return the resolution (min(width, height)) of the stream being downloaded."""
    info = progress.get("info_dict") or {}
    values = [
        value
        for value in (
            info.get("width"),
            info.get("height"),
            progress.get("width"),
            progress.get("height"),
        )
        if isinstance(value, int) and value > 0
    ]
    return min(values) if values else 0


def _make_adaptive_watch_hook(user_hook: Callable[[dict[str, Any]], None] | None = None) -> Callable[[dict[str, Any]], None]:
    """Measure real throughput and stop if the estimated time is too long.

    Observe the video stream's real throughput during the first
    `_ADAPTIVE_GRACE_SECONDS` seconds. If the projected ETA then exceeds the
    current tier's threshold, raise `_AdaptiveDowngrade` to retry at lower quality.
    """
    state: dict[str, Any] = {
        "filename": None,
        "started_at": None,
        "start_bytes": 0,
        "decided": False,
    }

    def hook(progress: dict[str, Any]) -> None:
        if user_hook is not None:
            user_hook(progress)
        if progress.get("status") != "downloading":
            return

        tier = _tier_for_resolution(_progress_resolution(progress))
        if tier is None:
            return  # Audio stream or unknown resolution; no decision to make.

        now = time.time()
        filename = progress.get("filename")
        if state["filename"] != filename:
            # Start a new observation window for this stream.
            state["filename"] = filename
            state["started_at"] = now
            state["start_bytes"] = progress.get("downloaded_bytes") or 0
            state["decided"] = False
            return

        if state["decided"]:
            return

        next_quality = _next_lower_quality(tier)
        if next_quality is None:
            state["decided"] = True  # Already at the lowest tier.
            return

        elapsed = now - (state["started_at"] or now)
        if elapsed < _ADAPTIVE_GRACE_SECONDS:
            return

        total = progress.get("total_bytes") or progress.get("total_bytes_estimate") or 0
        done = progress.get("downloaded_bytes") or 0
        transferred = done - state["start_bytes"]
        if total <= 0 or transferred <= 0:
            return

        speed = transferred / elapsed
        eta = max(total - done, 0) / speed
        threshold = _ADAPTIVE_TIME_THRESHOLDS.get(tier)

        # Keep the download within the tier's time threshold.
        # If the ETA is too long, lower quality immediately regardless of throughput.
        if threshold and eta > threshold:
            state["decided"] = True
            note = (
                f"{tier} -> {next_quality}; ETA {int(eta)} s > {threshold} s; "
                "retry at 0%."
            )
            if user_hook is not None:
                user_hook({
                    "status": "adaptive_quality",
                    "quality_from": tier,
                    "quality_to": next_quality,
                    "quality_changed": True,
                    "quality_used": next_quality,
                    "adaptive_note": note,
                    "adaptive_eta_seconds": int(eta),
                    "adaptive_threshold_seconds": threshold,
                })
            raise _AdaptiveDowngrade(
                next_quality,
                note,
            )

    return hook


def _cleanup_partial_files(output_path: str, before_files: set[str]) -> None:
    """Remove partial files from an abandoned attempt (quality downgrade)."""
    try:
        names = os.listdir(output_path)
    except OSError:
        return
    for name in names:
        if name in before_files:
            continue
        if name.lower().endswith((".part", ".ytdl", ".frag")):
            try:
                os.remove(os.path.join(output_path, name))
            except OSError:
                pass


def _build_video_format_string(
    quality_key: str,
    video_format_key: str,
    has_ffmpeg: bool,
    prefer_http: bool = False,
) -> str:
    """Build the yt-dlp video format from the requested quality and container.

    Do not filter the target resolution here: `height<=` fails for portrait videos
    (256/426/1024 instead of 144/240/480). Apply it through
    `_build_video_format_sort` (`res:240` = min(width, height)).
    """
    f_meta = VIDEO_OUTPUT_FORMATS.get(video_format_key, VIDEO_OUTPUT_FORMATS["best"])
    v_ext = f_meta.get("vext") or f_meta.get("vcodec")
    a_ext = f_meta.get("aext") or f_meta.get("acodec")
    container = f_meta["container"]
    protocol_filter = "[protocol^=http]" if prefer_http else ""

    if not has_ffmpeg:
        # Without merging, prefer a single-file format with an MP4 container.
        ext_filter = f"[ext={container}]" if container else ""
        return (
            f"best{ext_filter}{protocol_filter}[acodec!=none]/"
            f"best{protocol_filter}[acodec!=none]/"
            f"best[acodec!=none]/best"
        )

    # With FFmpeg: bestvideo + bestaudio.
    v_ext_f = (f"[ext={v_ext}]" if v_ext else "") + protocol_filter
    a_ext_f = (f"[ext={a_ext}]" if a_ext else "") + protocol_filter

    best_split = f"bestvideo{v_ext_f}+bestaudio{a_ext_f}"
    # Use a less restrictive fallback if the extension or codec is unavailable.
    fallback_split = f"bestvideo{protocol_filter}+bestaudio{protocol_filter}"
    # Last resort: a single file.
    ext_fallback = f"[ext={container}]" if container else ""
    fallback_single = (
        f"best{ext_fallback}{protocol_filter}[acodec!=none]/"
        f"best{protocol_filter}[acodec!=none]/best[acodec!=none]/best"
    )
    # Universal yt-dlp fallback for videos without a muxed format or usable
    # separate streams (for example, some Shorts).
    universal_fallback = "bestvideo*+bestaudio/best"

    return f"{best_split}/{fallback_split}/{fallback_single}/{universal_fallback}"


def _build_video_format_sort(quality_key: str) -> list[str] | None:
    """Sort resolutions for the requested quality.

    `res` is min(width, height), so sorting works for portrait videos (Shorts),
    where a `height` filter would not find any streams.
    """
    q_key = _resolve_quality_key(quality_key)
    max_height = VIDEO_QUALITIES.get(q_key, VIDEO_QUALITIES["best"])["max_height"]
    return [f"res:{max_height}"] if max_height else None


def _build_audio_format_string(audio_format_key: str) -> str:
    """Return the yt-dlp format string for audio extraction."""
    f_meta = AUDIO_OUTPUT_FORMATS.get(audio_format_key, AUDIO_OUTPUT_FORMATS["best"])
    codec = f_meta["codec"]
    if codec is None:
        return "bestaudio/best"
    # Prefer a compatible source format, then convert it with the FFmpeg postprocessor.
    return f"bestaudio[ext={codec}]/bestaudio/best"


def _build_audio_postprocessor(audio_format_key: str, has_ffmpeg: bool) -> dict[str, Any] | None:
    """Build an FFmpegExtractAudio postprocessor, or return None if unavailable or set to 'best'."""
    if not has_ffmpeg:
        return None
    f_meta = AUDIO_OUTPUT_FORMATS.get(audio_format_key, AUDIO_OUTPUT_FORMATS["best"])
    codec = f_meta["codec"]
    if codec is None:
        return None
    quality = f_meta["quality"]
    pp: dict[str, Any] = {
        "key": "FFmpegExtractAudio",
        "preferredcodec": codec,
    }
    if quality and quality > 0:
        pp["preferredquality"] = str(quality)
    return pp


def _build_subtitle_lang_options(lang_code: str | None) -> dict[str, Any]:
    """Build yt-dlp subtitle/audio options for the selected language."""
    opts: dict[str, Any] = {
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitlesformat": "vtt/best",
    }
    if not lang_code:
        opts["subtitleslangs"] = ["fr"]
        return opts

    if lang_code == "multi":
        opts["subtitleslangs"] = ["all"]
        return opts

    codes = {lang_code, *LANGUAGES.get(lang_code, {}).get("aliases", set())}
    # YouTube uses short codes and regional variants (zh-Hans, pt-BR, etc.).
    ytdlp_codes = sorted(
        {
            c
            for c in codes
            if c not in {"vf", "vo", "multi"} and 2 <= len(c) <= 10
        }
    )
    if lang_code == "zh":
        ytdlp_codes = sorted(set(ytdlp_codes) | {"zh", "zh-Hans", "zh-Hant", "zh-CN", "zh-TW"})
    if not ytdlp_codes:
        opts["subtitleslangs"] = ["all"]
        return opts

    opts["subtitleslangs"] = ytdlp_codes
    return opts


def _collect_subtitle_sidecars(
    media_filepath: str | None,
    created_files: list[str],
    output_path: str,
) -> list[str]:
    """Find downloaded .srt/.vtt/.ass sidecars and align their names with the video."""
    if not media_filepath or not os.path.isfile(media_filepath):
        return []

    sub_exts = {".srt", ".vtt", ".ass"}
    media_dir = os.path.dirname(media_filepath)
    media_stem = os.path.splitext(os.path.basename(media_filepath))[0]
    candidates: list[str] = []

    for path in created_files:
        ext = os.path.splitext(path)[1].lower()
        if ext in sub_exts and os.path.isfile(path):
            candidates.append(path)

    # Also scan the folder; yt-dlp may write files after the snapshot.
    try:
        for name in os.listdir(media_dir):
            full = os.path.join(media_dir, name)
            if not os.path.isfile(full):
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext in sub_exts and full not in candidates:
                # Keep files whose base name resembles the media name, before or after slugifying.
                base = os.path.splitext(name)[0]
                if media_stem[:20] in base or base[:20] in media_stem or _slugify_filename(base).startswith(media_stem[:16]):
                    candidates.append(full)
    except OSError:
        pass

    aligned: list[str] = []
    seen: set[str] = set()
    for path in candidates:
        ext = os.path.splitext(path)[1].lower()
        # Example: video.zh-Hans.srt keeps its language code in the final name.
        raw_stem = os.path.splitext(os.path.basename(path))[0]
        lang_suffix = ""
        parts = raw_stem.rsplit(".", 1)
        if len(parts) == 2 and 2 <= len(parts[1]) <= 10 and parts[1].replace("-", "").isalnum():
            lang_suffix = f".{parts[1]}"
        target = os.path.join(media_dir, f"{media_stem}{lang_suffix}{ext}")
        try:
            if os.path.normpath(path) != os.path.normpath(target):
                if os.path.exists(target):
                    # Preserve existing files by adding a unique suffix on collision.
                    n = 2
                    while os.path.exists(os.path.join(media_dir, f"{media_stem}{lang_suffix}-{n}{ext}")):
                        n += 1
                    target = os.path.join(media_dir, f"{media_stem}{lang_suffix}-{n}{ext}")
                os.rename(path, target)
            if target not in seen:
                aligned.append(target)
                seen.add(target)
        except OSError:
            if path not in seen and os.path.isfile(path):
                aligned.append(path)
                seen.add(path)
    return aligned


# ──────────────────────────────────────────────────────────────────────────────
# Main entry point (extended signature, backward compatible).
# ──────────────────────────────────────────────────────────────────────────────

def download_media(
    url,
    output_path: str | None = None,
    download_type="video",
    quality="best",
    video_format="mp4",
    audio_format="mp3",
    language: str | None = None,
    write_subtitles: bool = False,
    progress_hook=None,
    adaptive_quality: bool = True,
    force_folder: str | None = None,
) -> dict[str, Any]:
    """
        Single entry point:
            1. franime.fr sites → dedicated extractor
            2. yt-dlp sites     → direct yt-dlp download
            3. Other sites      → generic browser extractor

        New parameters (backward compatibility is preserved):
            video_format   : key in VIDEO_OUTPUT_FORMATS (best/mp4/mkv/webm/mov/avi)
            audio_format   : key in AUDIO_OUTPUT_FORMATS (best/mp3/mp3_320/flac/wav/...)
            language       : ISO language code (vf/vo/fr/en/es/...) or None for automatic detection
            write_subtitles: bool; download subtitles when available
            force_folder   : required output subfolder (e.g. "music") instead of
                                             automatic organization by domain
    """
    import re as _re

    download_type = str(download_type).lower().strip()
    quality = str(quality).lower().strip()

    if download_type not in VALID_DOWNLOAD_TYPES:
        download_type = "video"

    # Detect the language from the URL if none was provided.
    resolved_lang = normalize_language(language) if language else detect_language_from_url(url)

    base_output_path = output_path or str(get_download_path())
    if force_folder:
        target_output_path = os.path.join(base_output_path, force_folder)
    else:
        target_output_path = _build_output_folder(url, base_output_path)
    os.makedirs(target_output_path, exist_ok=True)

    # ── Start database tracking ───────────────────────────────────────────────
    parsed_global = urlparse(url)
    domain_global = parsed_global.netloc.lower().replace("www.", "") or "remote"
    dl_id = download_start(url, domain=domain_global, download_type=download_type, quality=quality)
    log.info("New download #%d — %s", dl_id, url[:100])

    # ── Check for an existing download ────────────────────────────────────────
    if _re.match(r"https?://(?:www\.)?franime\.fr/", url, _re.I):
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        slug = parsed.path.split('/')[-1] or "video"
        s = params.get('s', ['1'])[0]
        ep = params.get('ep', ['1'])[0]
        lang_tag = resolved_lang or params.get('lang', ['vo'])[0]
        filename_base = f"{slug}-s{s}-ep{ep}-{lang_tag}"

        for ext in VIDEO_EXTENSIONS | {".mp4", ".mkv", ".webm"}:
            potential_file = os.path.join(target_output_path, f"{filename_base}{ext}")
            if os.path.isfile(potential_file):
                log.warning("[skip] Already downloaded: %s", os.path.basename(potential_file))
                fsize = os.path.getsize(potential_file)
                download_finish(
                    dl_id, "skipped",
                    error_message="already_exists",
                    file_path=potential_file,
                    file_size_bytes=fsize,
                    metadata={"reason": "already_exists"},
                )
                return {
                    "success": True,
                    "skipped": True,
                    "reason": "already_exists",
                    "filename": os.path.basename(potential_file),
                    "filepath": potential_file,
                }

    extractor_used: str | None = None
    player_used: str | None = None

    # ── 1. Franime ───────────────────────────────────────────────────────────
    if _re.match(r"https?://(?:www\.)?franime\.fr/", url, _re.I):
        extractor_used = "franime"
        try:
            from franime_extractor import download_franime
            result = download_franime(
                url,
                output_path=target_output_path,
                download_type=download_type,
                quality=quality,
                video_format=video_format,
                audio_format=audio_format,
                language=resolved_lang,
            )
            player_used = result.get("player_name") or result.get("lecteur") or None
        except ImportError as e:
            log.error("franime_extractor.py not found: %s", e)
            error = RuntimeError("franime_extractor.py not found.")
            download_finish(dl_id, "failed", extractor_type=extractor_used, error_message=str(error))
            raise error from e
        except Exception as e:
            download_finish(
                dl_id,
                "failed",
                extractor_type=extractor_used,
                player_name=player_used,
                error_message=str(e) or type(e).__name__,
            )
            raise
    else:
        # ── 2. yt-dlp standard ───────────────────────────────────────────────────
        try:
            extractor_used = "yt-dlp"
            result = _ydlp_download(
                url,
                output_path=target_output_path,
                download_type=download_type,
                quality=quality,
                video_format=video_format,
                audio_format=audio_format,
                language=resolved_lang,
                write_subtitles=write_subtitles,
                progress_hook=progress_hook,
                adaptive_quality=adaptive_quality,
                download_id=dl_id,
            )
        except Exception as e:
            try:
                from yt_dlp.utils import UnsupportedError, ExtractorError
                is_unsupported = isinstance(e, (UnsupportedError, ExtractorError))
            except ImportError:
                is_unsupported = False

            if not is_unsupported:
                msg = str(e).lower()
                is_unsupported = any(k in msg for k in ("unsupported url", "no video formats", "unable to extract"))

            if is_unsupported:
                log.warning("[yt-dlp] Unsupported URL; falling back to the generic browser extractor.")
                try:
                    from browser_extractor import download_with_browser
                    extractor_used = "browser"
                    result = download_with_browser(
                        url,
                        output_path=target_output_path,
                        download_type=download_type,
                        quality=quality,
                    )
                    player_used = result.get("stream_url") and "browser_stream" or None
                except ImportError as e2:
                    log.error("browser_extractor.py not found: %s", e2)
                    error = RuntimeError("browser_extractor.py not found.")
                    download_finish(dl_id, "failed", extractor_type=extractor_used, error_message=str(error))
                    raise error from e2
                except Exception as e2:
                    download_finish(
                        dl_id,
                        "failed",
                        extractor_type=extractor_used,
                        player_name=player_used,
                        error_message=str(e2) or type(e2).__name__,
                    )
                    raise
            else:
                download_finish(
                    dl_id,
                    "failed",
                    extractor_type=extractor_used,
                    player_name=player_used,
                    error_message=str(e) or type(e).__name__,
                )
                raise

    filepath = result.get("filepath")
    if not filepath and result.get("reason") in {"not_found_or_blocked", "page_blocked"}:
        result["skipped"] = True
    if filepath:
        result["relative_path"] = _relative_download_path(filepath, base_output_path)
        result["filename"] = os.path.basename(filepath)
    # Convert subtitle sidecar paths to relative paths served through /media/.
    raw_subs = result.get("subtitle_files") or []
    relative_subs: list[str] = []
    for sub_path in raw_subs:
        if isinstance(sub_path, str) and os.path.isfile(sub_path):
            relative_subs.append(_relative_download_path(sub_path, base_output_path))
    if relative_subs:
        result["subtitle_files"] = relative_subs
        log.info("Subtitle files attached: %s", ", ".join(os.path.basename(s) for s in relative_subs))
    result["folder"] = os.path.relpath(target_output_path, start=base_output_path).replace("\\", "/")
    if resolved_lang:
        result["language"] = resolved_lang

    # ── Finish database tracking ─────────────────────────────────────────────
    final_status = "success" if filepath else ("skipped" if result.get("skipped") else "failed")
    fsize = None
    dur_ms = None
    metadata: dict[str, Any] = {}
    if filepath and os.path.isfile(filepath):
        try:
            fsize = os.path.getsize(filepath)
        except OSError:
            fsize = None
    # duration was previously taken from info dict — optional now
    if result.get("skipped"):
        metadata["reason"] = result.get("reason")
    if relative_subs:
        metadata["subtitle_files"] = relative_subs
    download_finish(
        dl_id,
        final_status,
        extractor_type=extractor_used,
        player_name=player_used,
        error_message=result.get("error") if final_status != "success" else None,
        file_path=filepath,
        file_size_bytes=fsize,
        duration_ms=dur_ms,
        metadata=metadata,
    )
    if final_status == "success":
        renamed = " (renamed to avoid collision)" if result.get("collision_renamed") else ""
        log.success(
            "Download #%d succeeded%s — %s",
            dl_id,
            renamed,
            result.get("filename") or filepath or "",
        )
    elif final_status == "skipped":
        log.warning("Download #%d skipped: %s", dl_id, result.get("reason"))
    else:
        log.error("Download #%d failed: %s", dl_id, result.get("error"))
    return result


def _slugify_filename(value: str) -> str:
    import unicodedata
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')
    name = re.sub(r"[^a-zA-Z0-9\._\- ]+", " ", value).strip()
    name = re.sub(r"\s+", "-", name)
    return name or "media"


def _extract_info_with_cookie_retry(url: str, ydl_opts: dict[str, Any]) -> dict[str, Any]:
    """Call extract_info and retry with cookies (file or Chrome) if access is blocked."""
    ydl_class = yt_dlp.YoutubeDL
    if ydl_opts.get("writesubtitles") or ydl_opts.get("writeautomaticsub"):
        class OptionalSubtitleErrorsYoutubeDL(yt_dlp.YoutubeDL):
            def _write_subtitles(self, info_dict, filename):
                try:
                    return super()._write_subtitles(info_dict, filename)
                except yt_dlp.utils.DownloadError as exc:
                    log.warning(
                        "[subtitles] Subtitles unavailable (%s); keeping the video.",
                        exc,
                    )
                    return []

        ydl_class = OptionalSubtitleErrorsYoutubeDL

    try:
        with ydl_class(ydl_opts) as ydl:  # pyright: ignore[reportArgumentType]
            return ydl.extract_info(url, download=True)
    except Exception as e:
        if not _needs_session(e):
            raise
        cookie_file = _resolve_cookie_file(url)
        cookie_source = Path(cookie_file).name if cookie_file else "Chrome browser cookies"
        log.warning(
            "[cookies] Access restricted or session required; retrying with %s",
            cookie_source,
        )
        retry_opts = _cookie_retry_options(ydl_opts, cookie_file)
        with ydl_class(retry_opts) as ydl:  # pyright: ignore[reportArgumentType]
            return ydl.extract_info(url, download=True)


def _flush_download_logs() -> None:
    root = logging.getLogger()
    for handler in root.handlers:
        try:
            handler.flush()
        except Exception:
            pass


def _make_download_progress_log_hook() -> Callable[[dict[str, Any]], None]:
    last_logged_at = 0.0
    last_percent = -1.0

    def hook(data: dict[str, Any]) -> None:
        nonlocal last_logged_at, last_percent
        status = data.get("status")
        if status == "finished":
            filename = Path(str(data.get("filename") or "")).name
            if filename:
                log.info("[download] 100%% — fragment ready: %s", filename)
            else:
                log.info("[download] 100%% — fragment ready")
            _flush_download_logs()
            return
        if status != "downloading":
            return

        percent_text = str(data.get("_percent_str") or "").strip()
        try:
            percent = float(percent_text.replace("%", "").strip())
        except ValueError:
            percent = last_percent
        now = time.monotonic()
        if now - last_logged_at < 0.35 and percent >= last_percent and percent < 100:
            return

        total = str(data.get("_total_bytes_str") or "").strip()
        if not total:
            total_bytes = data.get("total_bytes") or data.get("total_bytes_estimate")
            if total_bytes:
                total = f"{total_bytes / (1024 ** 3):.2f}GiB"
        speed = str(data.get("_speed_str") or "").strip()
        eta = str(data.get("_eta_str") or "").strip()
        parts = ["[download]", percent_text or "progressing"]
        if total:
            parts.extend(("of", total))
        if speed:
            parts.extend(("at", speed))
        if eta:
            parts.extend(("ETA", eta))
        log.info("%s", " ".join(parts))
        _flush_download_logs()
        last_logged_at = now
        last_percent = percent

    return hook


def _ydlp_download(
    url,
    output_path="downloads",
    download_type="video",
    quality="best",
    video_format="mp4",
    audio_format="mp3",
    language: str | None = None,
    write_subtitles: bool = False,
    progress_hook=None,
    adaptive_quality: bool = True,
    download_id: int | None = None,
) -> dict[str, Any]:
    """Internal yt-dlp download implementation (extended version)."""
    os.makedirs(output_path, exist_ok=True)

    ffmpeg_dir = _resolve_ffmpeg_dir()
    has_ffmpeg = bool(ffmpeg_dir) or (bool(shutil.which("ffmpeg")) and bool(shutil.which("ffprobe")))
    host = (urlparse(url).hostname or "").lower()
    is_youtube = host in {"youtube.com", "youtu.be"} or host.endswith(".youtube.com")

    # ── Build yt-dlp options (single pass: video + subtitles) ─────────────────
    subtitle_lang_opts = _build_subtitle_lang_options(language) if write_subtitles else {}
    runtime_options = yt_dlp_runtime_options()
    proxy_url = pick_proxy()
    if proxy_url:
        log.info("[proxy] Trafic via %s", proxy_url.split("@")[-1])

    connection_tier = get_connection_tier()
    media_info = MediaInfo.infer_from_url(url)
    strategy = StrategySelector(fragment_connections=connection_tier).choose(media_info)
    strategy_options = strategy.yt_dlp_options()
    monitor_adaptive = bool(adaptive_quality and download_type == "video" and quality == "best")

    def build_ydl_opts(quality_key: str) -> dict[str, Any]:
        """Build yt-dlp options for a quality level, rebuilding them on each retry."""
        if download_type == "audio":
            format_str = _build_audio_format_string(audio_format)
            format_sort = None
            audio_pp = _build_audio_postprocessor(audio_format, has_ffmpeg)
            postprocessors: list[dict[str, Any]] = [audio_pp] if audio_pp else []
            merge_output_format = None
        else:  # video
            # Prefer HTTP protocols for stable native fragment downloads.
            format_str = _build_video_format_string(
                quality_key, video_format, has_ffmpeg, prefer_http=True
            )
            format_sort = _build_video_format_sort(quality_key)
            postprocessors = []
            f_meta = VIDEO_OUTPUT_FORMATS.get(video_format, VIDEO_OUTPUT_FORMATS["best"])
            container = f_meta["container"]
            merge_output_format = (
                container if (has_ffmpeg and container and f_meta["merge"]) else None
            )

        opts: dict[str, Any] = {
            "format": format_str,
            "outtmpl": os.path.join(output_path, "%(title).200s.%(ext)s").replace("\\", "/"),
            "quiet": True, # Keep output quiet for all sites.
            "noprogress": True,
            "no_warnings": False,
            "postprocessors": postprocessors,
            "prefer_ffmpeg": has_ffmpeg,
            "merge_output_format": merge_output_format,
            "noplaylist": True,
            "retries": 10, # Use 10 retries for all sites.
            "fragment_retries": 10,
            "file_access_retries": 5,
            "socket_timeout": 30,
            "http_chunk_size": 10485760,
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
        opts.update(strategy_options)
        if proxy_url:
            opts["proxy"] = proxy_url
        if format_sort:
            opts["format_sort"] = format_sort
        # Fetch subtitles in the same pass as the video.
        if subtitle_lang_opts:
            opts.update(subtitle_lang_opts)
            if has_ffmpeg:
                opts["postprocessors"].append({"key": "FFmpegSubtitlesConvertor", "format": "vtt"})
        
        # Runtime et cookies
        opts.update(runtime_options)
        if ffmpeg_dir:
            opts["ffmpeg_location"] = ffmpeg_dir

        return opts

    requested_quality = quality
    current_quality = quality
    quality_changed = False
    adaptive_note: str | None = None

    if strategy.name == "yt-dlp-fragments":
        log.info("[strategy] native yt-dlp fragments active (x%d)", connection_tier)
    else:
        log.info("[strategy] native yt-dlp mono-connection active for direct media")

    before_files = set(os.listdir(output_path))

    try:
        log.info("yt-dlp — URL: %s", url)
        extra_bits = [f"Type: {download_type.upper()}"]
        extra_bits.append(f"Format: {video_format if download_type == 'video' else audio_format}")
        if download_type == "video":
            extra_bits.append(
                f"Quality: {current_quality.upper()}" + (" (adaptive 10s)" if monitor_adaptive else "")
            )
        if language:
            extra_bits.append(f"Lang: {language}")
        if write_subtitles:
            extra_bits.append("Subtitles: yes")
        log.info("yt-dlp — %s", " | ".join(extra_bits))

        # Start at the highest quality. Adaptive mode monitors throughput for
        # 10 seconds and retries at a lower quality if the ETA is too long.
        while True:
            ydl_opts = build_ydl_opts(current_quality)
            hooks: list[Callable[[dict[str, Any]], None]] = [
                _make_download_progress_log_hook()
            ]
            if progress_hook is not None:
                hooks.append(progress_hook)
            if monitor_adaptive:
                hooks.append(_make_adaptive_watch_hook())
            if hooks:
                ydl_opts["progress_hooks"] = hooks

            try:
                info = _extract_info_with_cookie_retry(url, ydl_opts)
                break
            except _AdaptiveDowngrade as downgrade:
                log.info("[adaptive] %s", downgrade.note)
                adaptive_note = downgrade.note
                quality_changed = True
                _cleanup_partial_files(output_path, before_files)
                current_quality = downgrade.quality
            except Exception:
                raise

        raw_title = info.get('title') or "download"

        created_files = _collect_created_files(output_path, before_files)

        original_file = _resolve_downloaded_file(info, created_files, output_path, download_type)
        collision_renamed = False
        if original_file and os.path.isfile(original_file):
            dir_name = os.path.dirname(original_file)
            base_name = os.path.basename(original_file)
            name_part, extension = os.path.splitext(base_name)

            clean_name = _slugify_filename(name_part)
            new_file = os.path.join(dir_name, f"{clean_name}{extension}")

            if original_file != new_file:
                if os.path.exists(new_file):
                    # Avoid silently overwriting a file by adding a numeric suffix.
                    collision_counter = 2
                    while True:
                        alt = os.path.join(dir_name, f"{clean_name}-{collision_counter}{extension}")
                        if not os.path.exists(alt):
                            collision_renamed = True
                            new_file = alt
                            break
                        collision_counter += 1
                os.rename(original_file, new_file)
                selected_file = new_file
            else:
                selected_file = original_file
        else:
            selected_file = original_file

        subtitle_paths = _collect_subtitle_sidecars(selected_file, created_files, output_path)

        return {
            "title": info.get("title") if isinstance(info, dict) else "download",
            "filepath": selected_file,
            "filename": os.path.basename(selected_file) if selected_file else None,
            "collision_renamed": collision_renamed,
            "subtitle_files": subtitle_paths,
            "quality_requested": requested_quality,
            "quality_used": current_quality,
            "quality_changed": quality_changed,
            "adaptive_note": adaptive_note,
            "strategy": strategy.name,
            # Do not return yt-dlp info objects, which are not JSON serializable.
        }
    except Exception as e:
        cookie_error = _friendly_cookie_error(e)
        if cookie_error:
            log.error("[cookies] %s", cookie_error)
            raise RuntimeError(cookie_error) from None
        if "ffmpeg" in str(e).lower() or "ffprobe" in str(e).lower():
            log.critical("FFmpeg not found or failed — %s", e)
            log.error("FFmpeg is required for audio conversion and container merging.")
            log.error("Install : winget install Gyan.FFmpeg  OU  https://ffmpeg.org/download.html")
        else:
            log.error("yt-dlp failed: %s", e, exc_info=True)
        raise


# ─── The /config route exposes format and language lists to the frontend ─────

def get_frontend_config() -> dict[str, Any]:
    """Return static data for initializing frontend selectors."""
    return {
        "video_formats": [
            {"key": k, "label": v["label"], "ext": v["ext"]}
            for k, v in VIDEO_OUTPUT_FORMATS.items()
        ],
        "audio_formats": [
            {"key": k, "label": v["label"], "ext": v["ext"]}
            for k, v in AUDIO_OUTPUT_FORMATS.items()
        ],
        "video_qualities": [
            {"key": k, "label": v["label"], "max_height": v["max_height"]}
            for k, v in VIDEO_QUALITIES.items()
        ],
        "languages": [
            {"code": k, "label": v["label"]}
            for k, v in LANGUAGES.items()
        ],
    }


if __name__ == "__main__":
    print("=" * 50)
    print("DowFlow - Multi-Site Media Downloader")
    print("=" * 50)

    video_url = input("Enter URL: ").strip()

    print("\nDownload Options:")
    print("1. Audio (choose format)")
    print("2. Video (choose format + quality)")

    choice = input("\nSelect option (1-2): ").strip()

    if choice == "1":
        print("\nAvailable audio formats:")
        for i, (k, v) in enumerate(AUDIO_OUTPUT_FORMATS.items(), 1):
            print(f"{i}. {v['label']}")
        try:
            af_choice = int(input("\nChoose audio format: ").strip())
            keys = list(AUDIO_OUTPUT_FORMATS.keys())
            audio_format = keys[af_choice - 1] if 1 <= af_choice <= len(keys) else "mp3"
        except ValueError:
            audio_format = "mp3"
        lang = input("Language (ISO code or blank for auto): ").strip() or None
        download_media(video_url, download_type="audio", audio_format=audio_format, language=lang)
    else:
        print("\nAvailable video formats:")
        for i, (k, v) in enumerate(VIDEO_OUTPUT_FORMATS.items(), 1):
            print(f"{i}. {v['label']}")
        try:
            vf_choice = int(input("\nChoose video format: ").strip())
            vkeys = list(VIDEO_OUTPUT_FORMATS.keys())
            video_format = vkeys[vf_choice - 1] if 1 <= vf_choice <= len(vkeys) else "mp4"
        except ValueError:
            video_format = "mp4"

        print("\nAvailable qualities:")
        qkeys = list(VIDEO_QUALITIES.keys())
        for i, k in enumerate(qkeys, 1):
            print(f"{i}. {VIDEO_QUALITIES[k]['label']}")
        try:
            q_choice = int(input("\nChoose quality: ").strip())
            quality = qkeys[q_choice - 1] if 1 <= q_choice <= len(qkeys) else "best"
        except ValueError:
            quality = "best"
        lang = input("Language (ISO code or blank for auto): ").strip() or None
        download_media(video_url, download_type="video", quality=quality,
                       video_format=video_format, language=lang)
