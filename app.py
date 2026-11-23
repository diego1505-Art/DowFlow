import gzip
import importlib
import hmac
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import quote

from flask import Flask, abort, jsonify, redirect, render_template, request, send_file, send_from_directory, url_for
from werkzeug.utils import secure_filename
from folder_picker import select_cookie_file, select_download_folder
import download_manager

from config import (
    APP_SCOPE,
    DownloadPathNotConfigured,
    IS_FROZEN,
    SOURCE_DIR,
    SUBPROCESS_CREATION_FLAGS,
    VIDEO_EXTENSIONS,
    get_download_path,
    get_runtime_build_id,
    has_configured_download_path,
    set_download_path,
    LOCAL_MEDIA_TTL_SECONDS,
    LOCAL_MEDIA_MAX_ENTRIES,
    ALLOWED_LOCAL_EXTENSIONS,
    PREVIEWABLE_EXTENSIONS,
    AUDIO_OUTPUT_FORMATS,
    DOWFLOW_COOKIES_DIR,
)
from utils import has_ffmpeg, is_http_url
from playlist import download_media, get_frontend_config
from logger import get_logger
from jobs import start_download_job, get_job, list_jobs
from database import (
    download_list,
    download_count_by_status,
    download_stats,
    favorite_list,
    favorite_add,
    favorite_remove,
)
if not IS_FROZEN or APP_SCOPE in {"all", "music"}:
    music = importlib.import_module("music")

log = get_logger("app")
_APP_BUILD_ID = get_runtime_build_id()


def _ensure_music_download_folder() -> None:
    """Give a Music-only install a working download folder out of the box.

    The Music edition ships the DowFlow Music (Liner) app, which has no setup
    page asking for a folder, so a fresh install downloads into ~/Downloads
    until the user picks another one in Liner's settings.
    """
    if not IS_FROZEN or APP_SCOPE != "music" or has_configured_download_path():
        return
    for candidate in (Path.home() / "Downloads", Path.home()):
        try:
            set_download_path(candidate)
            return
        except (OSError, ValueError):
            continue
    log.warning("No default download folder could be set for DowFlow Music")


_ensure_music_download_folder()

app = Flask(__name__)
if not IS_FROZEN or APP_SCOPE in {"all", "music"}:
    from music_stream_api import music_stream_api

    app.register_blueprint(music_stream_api)
# Track in-flight music downloads so repeated clicks reuse the same job.
_MUSIC_DOWNLOAD_JOBS: dict[str, tuple[str, float]] = {}
_MUSIC_DOWNLOAD_LOCK = threading.Lock()
_MUSIC_DOWNLOAD_TTL_SECONDS = 1800.0


# ── Response performance ────────────────────────────────────────────────
_COMPRESSIBLE_MIMETYPES = frozenset({
    "text/html",
    "text/css",
    "text/plain",
    "text/javascript",
    "application/javascript",
    "application/json",
    "application/xml",
    "image/svg+xml",
})
_GZIP_MIN_BYTES = 1024


@app.after_request
def compress_text_responses(response):
    """Gzip text assets and JSON so pages and API payloads transfer faster.

    Media responses are streamed through ``direct_passthrough`` and are left
    untouched so audio/video seeking keeps working.
    """
    if (
        response.direct_passthrough
        or response.status_code < 200
        or response.status_code >= 300
        or request.method == "HEAD"
        or "Content-Encoding" in response.headers
        or request.headers.get("Range")
        or response.mimetype not in _COMPRESSIBLE_MIMETYPES
        or "gzip" not in request.accept_encodings
    ):
        return response
    payload = response.get_data()
    if len(payload) < _GZIP_MIN_BYTES:
        return response
    compressed = gzip.compress(payload, compresslevel=6, mtime=0)
    if len(compressed) >= len(payload):
        return response
    response.set_data(compressed)
    response.headers["Content-Encoding"] = "gzip"
    response.headers.add("Vary", "Accept-Encoding")
    return response


@app.after_request
def cache_static_assets(response):
    """Let the browser reuse static files instead of refetching them."""
    if request.method != "GET" or response.status_code != 200:
        return response
    path = request.path
    if not path.startswith("/static/"):
        return response
    response.headers["Cache-Control"] = "public, max-age=3600"
    return response


@app.before_request
def require_electron_desktop_token():
    """Require the per-launch secret only when Electron starts this backend."""
    expected = os.environ.get("DOWFLOW_DESKTOP_TOKEN")
    if not expected:
        return None
    supplied = request.headers.get("X-DowFlow-Desktop", "")
    if not hmac.compare_digest(expected, supplied):
        abort(403)
    return None


def _download_folder(*, create: bool = True) -> Path:
    folder = get_download_path()
    if create:
        folder.mkdir(parents=True, exist_ok=True)
    return folder


def _scope_allows_path(scope: str, path: str) -> bool:
    common_paths = {
        "/",
        "/service-worker.js",
        "/api/status",
        "/api/dependencies/progress",
        "/api/dependencies/retry",
        "/check-ffmpeg",
        "/api/download-folder",
        "/api/download-folder/select",
        "/api/stats",
        "/stats",
        "/open-folder",
        "/api/update/check",
        "/api/update/install",
    }
    if path in common_paths or path.startswith(("/static/", "/media/", "/media-local/")):
        return True
    if scope == "all":
        return True
    if scope == "video":
        return path in {
            "/video", "/config", "/history", "/jobs", "/download", "/download-async",
            "/upload-local", "/url-options", "/expand-url", "/fetch-episodes", "/api/local-videos", "/stats",
        } or path.startswith("/jobs/")
    if scope == "music":
        # The Music edition ships the DowFlow Music (Liner) app, so a scoped
        # backend only needs to expose its API.
        return path.startswith(("/api/music/", "/jobs/"))
    return path == f"/{scope}"


@app.before_request
def enforce_export_scope():
    if IS_FROZEN and not _scope_allows_path(APP_SCOPE, request.path):
        abort(404)


# Categories not available yet in the main menu
COMING_SOON_CATEGORIES: dict[str, tuple[str, str]] = {
    "film": (
        "Movies / Series",
        "Download movies and series with multiple seasons, audio tracks and subtitles.",
    ),
    "anime": (
        "Anime / Animation",
        "Anime, animated shows and streaming catalogs.",
    ),
}

LOCAL_MEDIA_REGISTRY: dict[str, tuple[Path, float]] = {}
# Reentrant lock: the registry is shared across Flask threads.
_LOCAL_MEDIA_LOCK = threading.RLock()
DEBUG_MODE = os.environ.get("DOWFLOW_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}
if DEBUG_MODE:
    log.info("DOWFLOW_DEBUG mode active (DEBUG console logging)")


def is_allowed_local_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in ALLOWED_LOCAL_EXTENSIONS


def cleanup_local_media_registry() -> None:
    # Safe to call directly or from register/serve while already locked.
    with _LOCAL_MEDIA_LOCK:
        now = time.time()
        expired_tokens = [
            token
            for token, (_, created_at) in list(LOCAL_MEDIA_REGISTRY.items())
            if now - created_at > LOCAL_MEDIA_TTL_SECONDS
        ]
        for token in expired_tokens:
            LOCAL_MEDIA_REGISTRY.pop(token, None)

        if len(LOCAL_MEDIA_REGISTRY) <= LOCAL_MEDIA_MAX_ENTRIES:
            return

        tokens_by_age = sorted(
            LOCAL_MEDIA_REGISTRY.items(),
            key=lambda item: item[1][1],
        )
        overflow = len(LOCAL_MEDIA_REGISTRY) - LOCAL_MEDIA_MAX_ENTRIES
        for token, _ in tokens_by_age[:overflow]:
            LOCAL_MEDIA_REGISTRY.pop(token, None)


def register_local_media(source_path: Path) -> dict[str, str]:
    cleanup_local_media_registry()
    token = uuid.uuid4().hex
    with _LOCAL_MEDIA_LOCK:
        LOCAL_MEDIA_REGISTRY[token] = (source_path.resolve(), time.time())
    return {
        "filename": source_path.name,
        "filepath": str(source_path),
        "file_url": f"/media-local/{token}",
    }


@app.route("/")
def index():
    """Main menu, or the direct entry point for a scoped executable."""
    if IS_FROZEN and APP_SCOPE != "all":
        target = {
            "video": "/video",
            "film": "/film",
            "anime": "/anime",
        }.get(APP_SCOPE)
        if target is None:
            # The Music edition is the Liner desktop app and its bundled
            # backend only exposes the API, so there is no page at "/".
            # Redirecting to "/" itself used to answer 302 forever.
            abort(404)
        return redirect(target)
    return render_template(
        "menu.html",
        has_ffmpeg=has_ffmpeg(),
        app_scope=APP_SCOPE,
        is_frozen=IS_FROZEN,
    )


@app.get("/service-worker.js")
def service_worker():
    return "", 204


@app.get("/api/status")
def application_status():
    """Health check for clients waiting for the server to start."""
    return jsonify({
        "ready": True,
        "service": "DowFlow",
        "build_id": _APP_BUILD_ID,
        "ffmpeg": has_ffmpeg(),
    })


@app.get("/api/dependencies/progress")
def dependency_progress():
    if not IS_FROZEN:
        return jsonify({"status": "ready", "percent": 100, "stage": "Ready", "error": None})
    from bootstrap import dependency_progress as get_progress

    return jsonify(get_progress())


@app.post("/api/dependencies/retry")
def retry_dependency_setup():
    if not IS_FROZEN:
        return jsonify({"success": False, "error": "Dependency setup is only used by the portable app."}), 409
    from bootstrap import start_dependency_setup

    start_dependency_setup(force=True)
    return jsonify({"success": True})


@app.route("/video")
def video_page():
    """Generic video and audio downloader (legacy template)."""
    return render_template("download.html", has_ffmpeg=has_ffmpeg(), app_scope=APP_SCOPE)


@app.route("/film")
@app.route("/anime")
def coming_soon_page():
    """Menu categories that are not available yet."""
    category = request.path.strip("/")
    label, description = COMING_SOON_CATEGORIES.get(
        category, ("Coming soon", "This category will be available in a future update.")
    )
    return render_template(
        "coming_soon.html",
        category=category,
        label=label,
        description=description,
        has_ffmpeg=has_ffmpeg(),
        app_scope=APP_SCOPE,
    )


def _liner_launcher_spec() -> tuple[list[str], Path] | None:
    """Return the command that opens the DowFlow Music (Liner) desktop app."""
    if IS_FROZEN:
        # The Music edition installs Liner next to the other editions, inside
        # the same %LOCALAPPDATA%\DowFlow folder.
        executable = Path(sys.executable).resolve()
        for candidate in (
            executable.parent / "dowflow-music.exe",
            executable.parent / "submenus" / "music" / "dowflow-music.exe",
        ):
            if candidate.is_file():
                return [str(candidate)], candidate.parent
        return None
    app_dir = SOURCE_DIR / "desktop" / "liner"
    if not (app_dir / "package.json").is_file():
        return None
    packaged = app_dir / "release" / "win-unpacked" / "dowflow-music.exe"
    if packaged.is_file():
        return [str(packaged)], app_dir
    if not (app_dir / "dist-electron" / "main.js").is_file():
        return None
    if not (app_dir / "dist" / "index.html").is_file():
        return None
    electron_name = "electron.exe" if os.name == "nt" else "electron"
    electron_binary = app_dir / "node_modules" / "electron" / "dist" / electron_name
    if not electron_binary.is_file():
        return None
    return [str(electron_binary), str(app_dir)], app_dir


@app.post("/api/music/open")
def open_music_desktop_app():
    """Open the DowFlow Music desktop app when no Electron bridge exists."""
    spec = _liner_launcher_spec()
    if spec is None:
        return jsonify({
            "success": False,
            "error": "DowFlow Music (Liner) is not ready. Run start.bat music once to build it.",
        }), 409
    command, working_dir = spec
    creation_flags = 0
    if os.name == "nt":
        creation_flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    try:
        subprocess.Popen(
            command,
            cwd=str(working_dir),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
            close_fds=True,
        )
    except OSError as exc:
        log.warning("Unable to open DowFlow Music: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500
    return jsonify({"success": True})


# ─────────────────────────────  Music API  ────────────────────────────────────

@app.route("/api/music/search", methods=["POST"])
def music_search():
    data = request.get_json(silent=True) or {}
    query = str(data.get("query") or "").strip()
    if not query:
        return jsonify({"success": False, "error": "Empty query."}), 400
    try:
        limit = int(data.get("limit") or 20)
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(limit, 50))
    tracks = music.search_music(query, limit)
    return jsonify({"success": True, "query": query, "tracks": tracks})


@app.route("/api/music/popular")
def music_popular():
    try:
        limit = int(request.args.get("limit") or 24)
    except (TypeError, ValueError):
        limit = 24
    limit = max(1, min(limit, 50))
    return jsonify({"success": True, "tracks": music.popular_music(limit)})


@app.route("/api/music/download", methods=["POST"])
def music_download():
    data = request.get_json(silent=True) or {}
    url = str(data.get("url") or "").strip()
    if not url:
        return jsonify({"success": False, "error": "No track selected."}), 400

    audio_format = str(data.get("audio_format") or "mp3")
    if audio_format not in AUDIO_OUTPUT_FORMATS:
        audio_format = "mp3"

    try:
        output_folder = _download_folder()
    except DownloadPathNotConfigured:
        return jsonify({"success": False, "error": "Choose a download folder first."}), 409

    # The track is already in the Music folder: never download a second copy.
    existing = music.find_library_track(data.get("title"), data.get("artist"))
    if existing is not None:
        return jsonify(
            {"success": True, "async": False, "existing": True, "track": existing}
        )

    # A click on a track that is still downloading reuses the running job.
    title_key = None
    if data.get("title"):
        title_key = f"title:{music._normalize_text(str(data.get('title')))}"
    now = time.time()
    with _MUSIC_DOWNLOAD_LOCK:
        expired = [
            key
            for key, (_, started_at) in _MUSIC_DOWNLOAD_JOBS.items()
            if now - started_at > _MUSIC_DOWNLOAD_TTL_SECONDS
        ]
        for key in expired:
            _MUSIC_DOWNLOAD_JOBS.pop(key, None)
        for key in (url, title_key):
            if not key:
                continue
            running = _MUSIC_DOWNLOAD_JOBS.get(key)
            if running is None:
                continue
            running_job = get_job(running[0])
            if running_job and running_job.get("status") in {"queued", "running"}:
                return jsonify(
                    {"success": True, "async": True, "job_id": running[0]}
                )

    job_id = start_download_job(
        music.download_music_track,
        url,
        output_path=str(output_folder),
        audio_format=audio_format,
        with_cover=bool(data.get("with_cover", True)),
        title=data.get("title"),
        artist=data.get("artist"),
    )
    with _MUSIC_DOWNLOAD_LOCK:
        _MUSIC_DOWNLOAD_JOBS[url] = (job_id, now)
        if title_key:
            _MUSIC_DOWNLOAD_JOBS[title_key] = (job_id, now)
    return jsonify({"success": True, "async": True, "job_id": job_id})


@app.route("/api/music/library")
def music_library():
    try:
        limit = int(request.args.get("limit") or 200)
    except (TypeError, ValueError):
        limit = 200
    try:
        items = music.list_library(max(1, min(limit, 500)))
    except DownloadPathNotConfigured:
        return jsonify({"success": False, "error": "Choose a download folder first."}), 409
    return jsonify({"success": True, "items": items})


@app.get("/api/music/folder")
def music_folder_location():
    """Expose the absolute Music folder so the desktop player can sync it."""
    if music is None:
        abort(404)
    try:
        folder = music._music_folder()
        folder.mkdir(parents=True, exist_ok=True)
    except DownloadPathNotConfigured:
        return jsonify({"success": False, "error": "Choose a download folder first."}), 409
    return jsonify({"success": True, "path": str(folder)})


@app.get("/api/music/settings")
def music_settings():
    """Return the single download root and the imported cookie exports."""
    folder = get_download_path(required=False)
    return jsonify(
        {
            "success": True,
            "download_root": str(folder) if folder else None,
            "cookies_dir": str(DOWFLOW_COOKIES_DIR),
            "cookies": download_manager.list_imported_cookies(DOWFLOW_COOKIES_DIR),
        }
    )


@app.post("/api/music/cookies/import")
def music_cookies_import():
    """Pick a Netscape cookie export and copy it into DowFlow's cookie folder."""
    initial = (
        DOWFLOW_COOKIES_DIR
        if DOWFLOW_COOKIES_DIR.is_dir()
        else Path.home() / "Downloads"
    )
    try:
        selected = select_cookie_file(str(initial))
    except Exception as exc:
        log.error("[music] Cookie picker failed: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": str(exc)}), 500
    if not selected:
        return jsonify({"success": False, "cancelled": True}), 200
    try:
        imported = download_manager.import_cookie_file(selected, DOWFLOW_COOKIES_DIR)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    log.success("[music] Cookies imported for %s", ", ".join(imported["domains"]))
    return jsonify({"success": True, **imported})


@app.post("/api/music/cookies/import-path")
def music_cookies_import_path():
    """Import a cookie export picked by the desktop app's native file dialog."""
    data = request.get_json(silent=True) or {}
    source = str(data.get("path") or "").strip()
    if not source:
        return jsonify({"success": False, "error": "Cookie file path is required."}), 400
    try:
        imported = download_manager.import_cookie_file(source, DOWFLOW_COOKIES_DIR)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    log.success("[music] Cookies imported for %s", ", ".join(imported["domains"]))
    return jsonify({"success": True, **imported})


@app.get("/api/music/cookies")
def music_cookies_list():
    """List the cookie exports already imported into DowFlow."""
    return jsonify(
        {
            "success": True,
            "dir": str(DOWFLOW_COOKIES_DIR),
            "items": download_manager.list_imported_cookies(DOWFLOW_COOKIES_DIR),
        }
    )


@app.post("/api/music/covers")
def music_covers_backfill():
    """Write the cover art missing for tracks already in the Music folder."""
    if music is None:
        abort(404)
    try:
        created = music.ensure_covers()
    except DownloadPathNotConfigured:
        return jsonify({"success": False, "error": "Choose a download folder first."}), 409
    return jsonify({"success": True, "created": created})


@app.get("/api/music/favorites")
def music_favorites():
    return jsonify({"success": True, "items": favorite_list()})


@app.post("/api/music/favorites")
def music_favorite_add():
    data = request.get_json(silent=True) or {}
    filename = str(data.get("filename") or "").strip()
    if not filename:
        return jsonify({"success": False, "error": "Filename is required."}), 400
    favorite_add(filename)
    return jsonify({"success": True, "filename": filename})


@app.delete("/api/music/favorites/<path:filename>")
def music_favorite_remove(filename: str):
    removed = favorite_remove(filename)
    return jsonify({"success": True, "removed": removed, "filename": filename})


@app.route("/api/music/delete", methods=["POST"])
def music_delete():
    data = request.get_json(silent=True) or {}
    filename = data.get("filename")
    if not filename:
        return jsonify({"success": False, "error": "Filename is required."}), 400
    
    success = music.delete_track(filename)
    if success:
        return jsonify({"success": True, "message": "Track deleted."})
    return jsonify({"success": False, "error": "Track not found."}), 404


@app.route("/check-ffmpeg")
def check_ffmpeg():
    return jsonify({"has_ffmpeg": has_ffmpeg()})


@app.get("/api/update/check")
def update_check():
    """Report whether the GitHub release holds a newer Setup for this edition."""
    from updater import check_for_update

    return jsonify({"success": True, **check_for_update(APP_SCOPE)})


@app.post("/api/update/install")
def update_install():
    """Download the newest Setup, start it and let it replace this install."""
    from updater import install_latest

    try:
        result = install_latest(APP_SCOPE)
    except RuntimeError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    except Exception as exc:  # network, disk or a corrupted download
        log.error("[update] %s", exc, exc_info=True)
        return jsonify({"success": False, "error": str(exc)}), 502
    log.success("[update] Installing %s", result["version"] or result["name"])
    # Inno Setup replaces the program folder: this process has to go, and the
    # launcher's watchdog follows it instead of holding the port.
    threading.Timer(1.5, lambda: os._exit(0)).start()
    return jsonify({"success": True, **result})


@app.get("/api/download-folder")
def download_folder_status():
    folder = get_download_path(required=False)
    return jsonify(
        {
            "configured": has_configured_download_path(),
            "path": str(folder) if folder else None,
            "required": IS_FROZEN and folder is None,
        }
    )


@app.post("/api/download-folder/select")
def choose_download_folder():
    try:
        current = get_download_path(required=False)
        initial_directory = str(current if current and current.is_dir() else Path.home())
        selected = select_download_folder(initial_directory)
        if not selected:
            return jsonify({"success": False, "cancelled": True}), 200

        folder = set_download_path(selected)
        if IS_FROZEN:
            from bootstrap import start_dependency_setup
            from utils import clear_ffmpeg_cache

            clear_ffmpeg_cache()
            start_dependency_setup(force=True)
        return jsonify({"success": True, "path": str(folder)})
    except Exception as exc:
        log.error("[download-folder] Could not select folder: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": str(exc)}), 500


@app.post("/api/music/download-root")
def music_download_root():
    """Set the single download root from the desktop music app."""
    data = request.get_json(silent=True) or {}
    selected = str(data.get("path") or "").strip()
    if not selected:
        return jsonify({"success": False, "error": "A folder path is required."}), 400
    try:
        folder = set_download_path(selected)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    return jsonify({"success": True, "path": str(folder)})


@app.get("/api/local-videos")
def local_videos():
    try:
        folder = _download_folder(create=False)
    except DownloadPathNotConfigured:
        return jsonify({"success": False, "error": "Choose a download folder first."}), 409

    items = []
    # Every file lives directly in the download root: there are no per-domain
    # or per-series subfolders to scan.
    try:
        files = list(folder.iterdir())
    except OSError:
        files = []

    for path in files:
        if not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        relative = path.name
        items.append(
                {
                    "filename": path.name,
                    "relative_path": relative,
                    "file_url": f"/media/{quote(relative, safe='/')}",
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                }
            )
    items.sort(key=lambda item: item["modified"], reverse=True)
    return jsonify({"success": True, "items": items})


@app.route("/history")
def history():
    """SQLite download history and statistics."""
    try:
        limit = request.args.get("limit", default=50, type=int)
        limit = max(1, min(limit or 50, 200))
        status = (request.args.get("status") or "").strip() or None
        rows = download_list(limit=limit, status=status)
        return jsonify(
            {
                "success": True,
                "counts": download_count_by_status(),
                "items": rows,
            }
        )
    except Exception as e:
        log.error("[history] %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@app.get("/api/stats")
def stats_api():
    """Return aggregate download metrics and recent strategy usage."""
    try:
        return jsonify({"success": True, **download_stats()})
    except Exception as e:
        log.error("[stats] %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@app.get("/stats")
def stats_page():
    return render_template("stats.html", has_ffmpeg=has_ffmpeg())


@app.route("/jobs", methods=["GET"])
def jobs_list():
    return jsonify({"success": True, "jobs": list_jobs(limit=50)})


@app.route("/jobs/<job_id>", methods=["GET"])
def jobs_status(job_id: str):
    job = get_job(job_id)
    if job is None:
        return jsonify({"success": False, "error": "Job not found."}), 404
    return jsonify({"success": True, "job": job})


@app.route("/download-async", methods=["POST"])
def download_async():
    """Start a download in the background and return its job ID."""
    try:
        data = request.get_json() or {}
        source_value = (data.get("url") or "").strip().replace("\n", "").replace("\r", "")
        if not source_value:
            return jsonify({"success": False, "error": "URL is required."}), 400

        # Local paths are returned immediately without creating a job.
        local_path = Path(source_value).expanduser()
        if not is_http_url(source_value) and is_allowed_local_file(local_path):
            registered = register_local_media(local_path)
            return jsonify(
                {
                    "success": True,
                    "async": False,
                    "filename": registered["filename"],
                    "file_url": registered["file_url"],
                    "source_type": "local",
                    "source_label": str(local_path),
                    "previewable": local_path.suffix.lower() in PREVIEWABLE_EXTENSIONS,
                    "message": "Local file ready without copying.",
                }
            )

        if not is_http_url(source_value):
            return jsonify({"success": False, "error": "Invalid URL or local path not found."}), 400

        download_type = data.get("type", "video")
        quality = data.get("quality", "best")
        video_format = data.get("video_format", "mp4")
        audio_format = data.get("audio_format", "mp3")
        language = data.get("language") or None
        if isinstance(language, str):
            language = language.strip() or None
        write_subtitles = bool(data.get("write_subtitles", False))
        adaptive_quality = bool(data.get("adaptive_quality", True))

        job_id = start_download_job(
            download_media,
            source_value,
            output_path=str(_download_folder()),
            download_type=download_type,
            quality=quality,
            video_format=video_format,
            audio_format=audio_format,
            language=language,
            write_subtitles=write_subtitles,
            adaptive_quality=adaptive_quality,
        )
        log.info("[download-async] job=%s url=%s", job_id, source_value[:120])
        return jsonify({"success": True, "async": True, "job_id": job_id})
    except DownloadPathNotConfigured:
        return jsonify({"success": False, "error": "Choose a download folder first."}), 409
    except Exception as e:
        log.error("[download-async] %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/config")
def frontend_config():
    """Return the static list of formats, qualities, and languages for the frontend."""
    payload = get_frontend_config()
    payload["has_ffmpeg"] = has_ffmpeg()
    return jsonify(payload)


@app.route("/media/<path:filename>")
def serve_media(filename: str):
    try:
        folder = _download_folder()
    except DownloadPathNotConfigured:
        abort(409)
    return send_from_directory(folder, filename, as_attachment=False)


@app.route("/media/music/<path:filename>")
def serve_music_media(filename: str):
    """Serve Music files from the configured Music folder with HTTP ranges."""
    if music is None:
        abort(404)
    try:
        music_folder = music._music_folder()
    except DownloadPathNotConfigured:
        abort(409)
    return send_from_directory(
        music_folder,
        filename,
        as_attachment=False,
        conditional=True,
    )


@app.route("/media-local/<token>")
def serve_local_media(token: str):
    cleanup_local_media_registry()
    with _LOCAL_MEDIA_LOCK:
        entry = LOCAL_MEDIA_REGISTRY.get(token)
        if entry is None:
            abort(404)
        source_path, _ = entry
        if not source_path.is_file():
            LOCAL_MEDIA_REGISTRY.pop(token, None)
            abort(404)
        LOCAL_MEDIA_REGISTRY[token] = (source_path, time.time())
    return send_file(source_path, as_attachment=False)


@app.route("/open-folder")
def open_folder():
    try:
        os.startfile(str(_download_folder()))  # type: ignore[attr-defined]
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/upload-local", methods=["POST"])
def upload_local():
    try:
        file = request.files.get("file")
        if file is None or not file.filename:
            return jsonify({"success": False, "error": "No local file received."}), 400

        suffix = Path(file.filename).suffix.lower()
        if suffix not in ALLOWED_LOCAL_EXTENSIONS:
            return jsonify({"success": False, "error": "Unsupported file format."}), 400

        safe_name = secure_filename(file.filename) or f"local-{uuid.uuid4().hex}{suffix}"
        stored_name = f"{uuid.uuid4().hex[:8]}-{safe_name}"
        destination = _download_folder() / stored_name
        file.save(destination)

        return jsonify(
            {
                "success": True,
                "filename": stored_name,
                "file_url": f"/media/{stored_name}",
                "source_type": "local",
                "source_label": file.filename,
                "message": "Local file uploaded successfully.",
                "previewable": Path(stored_name).suffix.lower() in PREVIEWABLE_EXTENSIONS,
            }
        )
    except DownloadPathNotConfigured:
        return jsonify({"success": False, "error": "Choose a download folder first."}), 409
    except Exception as e:
        return jsonify({"success": False, "error": f"Local upload failed: {e}"}), 500


@app.route("/url-options", methods=["POST"])
def url_options():
    """Return the options profile for the first URL (multi-site support)."""
    try:
        data = request.get_json() or {}
        url = (data.get("url") or "").strip()
        log.info("[url-options] url=%s", url or "(vide)")
        if not url:
            return jsonify({"success": False, "error": "URL is required."}), 400
        from url_expanders import options_payload
        payload = options_payload(url)
        log.info(
            "[url-options] site=%s available=%s options=%d",
            payload.get("site_id"),
            payload.get("available"),
            len(payload.get("options") or []),
        )
        return jsonify(payload)
    except Exception as e:
        log.error("[url-options] ERROR: %s", e, exc_info=True)
        return jsonify({"success": False, "error": f"System error: {e}"}), 500


@app.route("/expand-url", methods=["POST"])
def expand_url_route():
    """Expand a source URL into a list of URLs using the site's options."""
    try:
        data = request.get_json() or {}
        url = (data.get("url") or "").strip()
        if not url:
            return jsonify({"success": False, "error": "URL is required."}), 400
        options = data.get("options") or {}
        # Backward compatibility with older clients.
        if "current_only" in data and "scope" not in options:
            options["scope"] = "season" if data.get("current_only") else "all"
            options["current_only"] = bool(data.get("current_only"))

        log.info("[expand-url] url=%s options=%s", url, options)
        from url_expanders import expand_url
        result = expand_url(url, options)
        status = 200 if result.success else 400
        log.info(
            "[expand-url] success=%s site=%s count=%s error=%s",
            result.success,
            result.site_id,
            result.count or len(result.urls),
            result.error,
        )
        return jsonify(result.to_dict()), status
    except Exception as e:
        log.error("[expand-url] ERROR: %s", e, exc_info=True)
        return jsonify({"success": False, "error": f"System error: {e}"}), 500


@app.route("/fetch-episodes", methods=["POST"])
def fetch_episodes():
    """Legacy alias for /expand-url (Franime)."""
    try:
        data = request.get_json() or {}
        url = (data.get("url") or "").strip()
        if not url:
            return jsonify({"success": False, "error": "URL is required."}), 400
        options = {
            "scope": "season" if data.get("current_only") else "all",
            "current_only": bool(data.get("current_only")),
        }
        log.info("[fetch-episodes] url=%s options=%s", url, options)
        from url_expanders import expand_url
        result = expand_url(url, options)
        status = 200 if result.success else 400
        log.info(
            "[fetch-episodes] success=%s count=%s error=%s",
            result.success,
            result.count or len(result.urls),
            result.error,
        )
        return jsonify(result.to_dict()), status
    except Exception as e:
        log.error("[fetch-episodes] ERROR: %s", e, exc_info=True)
        return jsonify({"success": False, "error": f"System error: {e}"}), 500


@app.route("/download", methods=["POST"])
def download():
    try:
        data = request.get_json() or {}
        # Remove accidental newlines from the URL.
        source_value = data.get("url", "").strip().replace("\n", "").replace("\r", "")
        download_type = data.get("type", "video")
        quality = data.get("quality", "best")
        video_format = data.get("video_format", "mp4")
        audio_format = data.get("audio_format", "mp3")
        language = data.get("language") or None
        if isinstance(language, str):
            language = language.strip() or None
        write_subtitles = bool(data.get("write_subtitles", False))
        adaptive_quality = bool(data.get("adaptive_quality", True))
        log.info(
            "[download] type=%s quality=%s vfmt=%s afmt=%s lang=%s adaptive=%s url=%s",
            download_type, quality, video_format, audio_format,
            language or "(auto)", adaptive_quality, source_value[:150] if source_value else "(empty)",
        )

        if not source_value:
            return jsonify({"success": False, "error": "Enter a URL or a local path."}), 400

        local_path = Path(source_value).expanduser()
        if not is_http_url(source_value) and is_allowed_local_file(local_path):
            registered = register_local_media(local_path)
            return jsonify(
                {
                    "success": True,
                    "message": "Local file ready without copying.",
                    "filename": registered["filename"],
                    "file_url": registered["file_url"],
                    "source_type": "local",
                    "source_label": str(local_path),
                    "previewable": local_path.suffix.lower() in PREVIEWABLE_EXTENSIONS,
                }
            )

        if not is_http_url(source_value):
            return jsonify({"success": False, "error": "Invalid URL or local path not found."}), 400

        result = download_media(
            source_value,
            output_path=str(_download_folder()),
            download_type=download_type,
            quality=quality,
            video_format=video_format,
            audio_format=audio_format,
            language=language,
            write_subtitles=write_subtitles,
            adaptive_quality=adaptive_quality,
        )

        filename = result.get("filename")
        relative_path = result.get("relative_path") or filename
        
        if result.get("skipped"):
            reason = result.get("reason")
            if reason == "already_exists":
                reason_msg = "Already downloaded."
            elif reason == "page_blocked":
                reason_msg = "Page blocked by the remote server."
            else:
                reason_msg = "Not found or unavailable."
            return jsonify({
                "success": True,
                "skipped": True,
                "reason": reason,
                "message": f"Episode skipped: {reason_msg}",
                "filename": filename,
                "source_label": source_value
            })

        if not filename:
            return jsonify({"success": False, "error": result.get("error", "Downloaded file could not be found.")}), 500

        from urllib.parse import urlparse

        domain = urlparse(source_value).netloc.replace("www.", "") or "remote"
        previewable = Path(filename).suffix.lower() in PREVIEWABLE_EXTENSIONS
        payload = {
            "success": True,
            "message": f"Downloaded from {domain}: {filename}",
            "filename": filename,
            "file_url": f"/media/{relative_path}",
            "source_type": domain,
            "source_label": source_value,
            "previewable": previewable,
            "storage_folder": result.get("folder"),
        }

        if download_type == "audio":
            payload["message"] = f"Audio downloaded: {filename}"
        elif not previewable:
            payload["message"] = f"Downloaded: {filename} (browser preview is not supported)"

        return jsonify(payload)

    except DownloadPathNotConfigured:
        return jsonify({"success": False, "error": "Choose a download folder first."}), 409
    except Exception as e:
        error_msg = str(e).strip() or type(e).__name__
        log.error("[download] Failed: %s", error_msg, exc_info=True)
        if "ffmpeg" in error_msg.lower() or "ffprobe" in error_msg.lower():
            return jsonify(
                {
                    "success": False,
                    "error": "FFmpeg is required but not installed. Install FFmpeg to continue.",
                    "is_ffmpeg_error": True,
                }
            ), 500
        return jsonify({"success": False, "error": f"Download failed: {error_msg}"}), 500


def _start_network_detection() -> None:
    """Measure network speed without blocking Flask startup."""
    def worker() -> None:
        try:
            from playlist import _measure_network_speed_mbps, detect_connection_tier

            log.info("Measuring network speed in background...")
            speed = _measure_network_speed_mbps()
            if speed > 0:
                log.success("Network speed detected: %.2f Mbps", speed)
            else:
                log.warning("Network speed unavailable (check your connection).")
            detect_connection_tier(speed)
        except Exception as exc:
            log.debug("Network detection skipped: %s", exc, exc_info=True)

    threading.Thread(target=worker, name="dowflow-network-detection", daemon=True).start()


# ── Parent watchdog ────────────────────────────────────────────────────
# ``launcher.py`` spawns this server from its console. If that console closes
# or the launcher crashes, the server would keep the port forever: without a
# watchdog every launch left one more Flask server on 5001, 5002, ... forever.
_WATCHDOG_POLL_SECONDS = 1.0
_SYNCHRONIZE = 0x00100000
_WAIT_TIMEOUT = 0x00000102


def _watchdog_parent_ids() -> list[int]:
    """Process ids whose death must stop this server."""
    parents: list[int] = []
    configured = os.environ.get("DOWFLOW_PARENT_PID", "").strip()
    if configured.isdigit():
        parents.append(int(configured))
    try:
        parents.append(os.getppid())
    except OSError:
        pass
    current = os.getpid()
    unique = dict.fromkeys(pid for pid in parents if pid > 0 and pid != current)
    return list(unique)


def _start_parent_watchdog() -> None:
    """Exit as soon as the process that launched DowFlow disappears."""
    parents = _watchdog_parent_ids()
    if not parents:
        return

    def stop(reason: str) -> None:
        log.info("Stopping the server: %s", reason)
        # Skip interpreter teardown so waitress threads cannot hold the port.
        os._exit(0)

    def watch_windows() -> None:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel32.WaitForSingleObject.restype = wintypes.DWORD

        handles = {}
        for pid in parents:
            handle = kernel32.OpenProcess(_SYNCHRONIZE, False, pid)
            if not handle:
                stop(f"process {pid} is already gone")
            handles[pid] = handle
        while True:
            time.sleep(_WATCHDOG_POLL_SECONDS)
            for pid, handle in handles.items():
                if kernel32.WaitForSingleObject(handle, 0) != _WAIT_TIMEOUT:
                    stop(f"process {pid} exited")

    def watch_posix() -> None:
        while True:
            time.sleep(_WATCHDOG_POLL_SECONDS)
            for pid in parents:
                try:
                    os.kill(pid, 0)
                except OSError:
                    stop(f"process {pid} exited")

    target = watch_windows if os.name == "nt" else watch_posix
    threading.Thread(
        target=target, name="dowflow-parent-watchdog", daemon=True
    ).start()


def run_server() -> None:
    from logger import banner
    banner(log, "DowFlow — Multi-Site Media Downloader")
    _start_parent_watchdog()

    if getattr(sys, "frozen", False):
        from bootstrap import start_dependency_setup

        start_dependency_setup()

    _start_network_detection()

    configured_host = os.environ.get("DOWFLOW_HOST", "127.0.0.1")
    configured_port = int(os.environ.get("DOWFLOW_PORT", "5001"))
    log.success("Server started at http://%s:%d", configured_host, configured_port)
    if DEBUG_MODE:
        log.info("DEBUG: historique=/history  jobs=/jobs  async=/download-async")
    log.info("Press Ctrl+C to stop")
    host = os.environ.get("DOWFLOW_HOST", "127.0.0.1")
    if getattr(sys, "frozen", False):
        from waitress import serve

        serve(app, host=host, port=configured_port, threads=8)
    else:
        app.run(
            debug=DEBUG_MODE,
            host=host,
            port=configured_port,
            use_reloader=False,
            threaded=True,
        )


if __name__ == "__main__":
    run_server()
