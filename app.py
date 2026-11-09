import importlib
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

from flask import Flask, abort, jsonify, redirect, render_template, request, send_file, send_from_directory, url_for
from werkzeug.utils import secure_filename
from folder_picker import select_download_folder

from config import (
    APP_SCOPE,
    BASE_DIR,
    DownloadPathNotConfigured,
    IS_FROZEN,
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
)
from utils import has_ffmpeg, is_http_url
from playlist import download_media, get_frontend_config
from logger import get_logger
from jobs import start_download_job, get_job, list_jobs
from database import (
    download_list,
    download_count_by_status,
    favorite_list,
    favorite_add,
    favorite_remove,
)
if not IS_FROZEN or APP_SCOPE in {"all", "music"}:
    music = importlib.import_module("music")

log = get_logger("app")
_APP_BUILD_ID = get_runtime_build_id()

app = Flask(__name__)
_EXPORT_JOBS: dict[str, dict[str, Any]] = {}
_EXPORT_LOCK = threading.Lock()
_EXPORT_RUNNING = False


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
        "/open-folder",
    }
    if path in common_paths or path.startswith(("/static/", "/media/", "/media-local/")):
        return True
    if scope == "all":
        return True
    if scope == "video":
        return path in {
            "/video", "/config", "/history", "/jobs", "/download", "/download-async",
            "/upload-local", "/url-options", "/expand-url", "/fetch-episodes", "/api/local-videos",
        } or path.startswith("/jobs/")
    if scope == "music":
        return path in {"/music", "/music/explore", "/music/liked"} or path.startswith("/api/music/")
    return path == f"/{scope}"


@app.before_request
def enforce_export_scope():
    if IS_FROZEN and not _scope_allows_path(APP_SCOPE, request.path):
        abort(404)


@app.context_processor
def export_template_context():
    path = request.path
    if path == "/":
        export_scope = "all"
    elif path.startswith("/music"):
        export_scope = "music"
    elif path == "/video":
        export_scope = "video"
    elif path.strip("/") in COMING_SOON_CATEGORIES:
        export_scope = path.strip("/")
    else:
        export_scope = "all"
    return {
        "app_scope": APP_SCOPE,
        "can_export": not IS_FROZEN,
        "export_scope": export_scope,
    }

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
    "image": (
        "Manhwa / Manga / Comics / Images",
        "Chapters, pages and images.",
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
        return redirect({
            "video": "/video",
            "music": "/music",
            "film": "/film",
            "anime": "/anime",
            "image": "/image",
        }[APP_SCOPE])
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
    return render_template("download.html", has_ffmpeg=has_ffmpeg())


@app.route("/music")
def music_page():
    """Music home page (player, themes, and recent tracks)."""
    return render_template("music.html", has_ffmpeg=has_ffmpeg())


@app.route("/music/explore")
def music_explore_page():
    """Music explorer (local library and online downloads)."""
    return render_template("music_explore.html", has_ffmpeg=has_ffmpeg())


@app.route("/music/liked")
def music_liked_page():
    """Music favorites page."""
    return render_template("music_liked.html", has_ffmpeg=has_ffmpeg())


@app.route("/film")
@app.route("/anime")
@app.route("/image")
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
    )


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

    job_id = start_download_job(
        music.download_music_track,
        url,
        output_path=str(output_folder),
        audio_format=audio_format,
        with_cover=bool(data.get("with_cover", True)),
        title=data.get("title"),
        artist=data.get("artist"),
    )
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


@app.get("/api/download-folder")
def download_folder_status():
    folder = get_download_path(required=False)
    return jsonify(
        {
            "configured": has_configured_download_path(),
            "path": str(folder) if folder else None,
            "required": IS_FROZEN and (folder is None or not folder.is_dir()),
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


@app.get("/api/local-videos")
def local_videos():
    try:
        folder = _download_folder(create=False)
    except DownloadPathNotConfigured:
        return jsonify({"success": False, "error": "Choose a download folder first."}), 409

    items = []
    known_media_folders = {
        "youtube", "instagram", "snapchat", "tiktok", "twitter", "x",
        "facebook", "vimeo", "dailymotion", "reddit", "franime", "music",
    }
    try:
        media_roots = [
            child for child in folder.iterdir()
            if child.is_dir() and child.name.casefold() in known_media_folders
        ]
    except OSError:
        media_roots = []

    for media_root in media_roots:
        for path in media_root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            relative = path.relative_to(folder).as_posix()
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


def _run_export_job(job_id: str, scope: str, name: str, output_path: Path) -> None:
    global _EXPORT_RUNNING
    try:
        if importlib.util.find_spec("PyInstaller") is None:
            requirements_file = BASE_DIR / "requirements-build.txt"
            if not requirements_file.is_file():
                raise RuntimeError("requirements-build.txt was not found in the project folder.")
            with _EXPORT_LOCK:
                _EXPORT_JOBS[job_id].update(
                    stage="Installing build dependencies",
                    progress=1,
                    eta_seconds=None,
                    eta_updated_at=time.time(),
                )
            install = subprocess.Popen(
                [sys.executable, "-m", "pip", "install", "-r", str(requirements_file)],
                cwd=BASE_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=SUBPROCESS_CREATION_FLAGS,
            )
            install_output: list[str] = []
            if install.stdout is not None:
                for line in install.stdout:
                    install_output.append(line.rstrip())
                    install_output = install_output[-100:]
            if install.wait() != 0:
                detail = "\n".join(install_output)[-5000:]
                raise RuntimeError(detail or "Unable to install build dependencies.")
            if importlib.util.find_spec("PyInstaller") is None:
                raise RuntimeError("PyInstaller is still unavailable after installing build dependencies.")

        build_script = BASE_DIR / "build_export.py"
        process = subprocess.Popen(
            [sys.executable, str(build_script), scope, name, "--json-progress"],
            cwd=BASE_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=SUBPROCESS_CREATION_FLAGS,
        )
        recent_output: list[str] = []
        if process.stdout is not None:
            for line in process.stdout:
                try:
                    event = json.loads(line)
                except ValueError:
                    recent_output.append(line.rstrip())
                    recent_output = recent_output[-100:]
                    continue
                if event.get("type") != "progress":
                    continue
                with _EXPORT_LOCK:
                    job = _EXPORT_JOBS.get(job_id)
                    if job:
                        job.update(
                            progress=event.get("percent", job.get("progress", 0)),
                            stage=event.get("stage", job.get("stage")),
                            elapsed_seconds=event.get("elapsed_seconds", job.get("elapsed_seconds", 0)),
                            eta_seconds=event.get("eta_seconds"),
                            eta_updated_at=event.get("eta_updated_at", time.time()),
                        )
        return_code = process.wait()
        with _EXPORT_LOCK:
            job = _EXPORT_JOBS[job_id]
            if return_code == 0 and output_path.is_file():
                job.update(
                    status="success",
                    progress=100,
                    stage="Complete",
                    eta_seconds=0,
                    eta_updated_at=time.time(),
                    path=str(output_path),
                    error=None,
                )
            else:
                detail = "\n".join(recent_output)[-5000:]
                job.update(
                    status="failed",
                    stage="Build failed",
                    eta_seconds=None,
                    eta_updated_at=time.time(),
                    path=None,
                    error=detail.strip() or "PyInstaller failed.",
                )
    except Exception as exc:
        with _EXPORT_LOCK:
            _EXPORT_JOBS[job_id].update(status="failed", path=None, error=str(exc))
    finally:
        with _EXPORT_LOCK:
            _EXPORT_RUNNING = False


@app.post("/api/export")
def start_export():
    global _EXPORT_RUNNING
    if IS_FROZEN:
        return jsonify({"success": False, "error": "Export is available from the source project only."}), 409
    if request.remote_addr not in {"127.0.0.1", "::1"}:
        return jsonify({"success": False, "error": "Export is restricted to the local computer."}), 403
    data = request.get_json(silent=True) or {}
    scope = str(data.get("scope") or "")
    allowed_scopes = {"all", "video", "music", "film", "anime", "image"}
    if scope not in allowed_scopes:
        return jsonify({"success": False, "error": "Unsupported export scope."}), 400

    dist_dir = BASE_DIR / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    picker = Path(__file__).with_name("folder_picker.py")
    try:
        picker_result = subprocess.run(
            [sys.executable, str(picker), "--save-exe", scope, str(dist_dir)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=600,
            check=False,
            creationflags=SUBPROCESS_CREATION_FLAGS,
        )
    except Exception as exc:
        return jsonify({"success": False, "error": f"Unable to open the save dialog: {exc}"}), 500
    selected = picker_result.stdout.strip()
    if picker_result.returncode != 0:
        return jsonify({"success": False, "error": picker_result.stderr.strip() or "Save dialog failed."}), 500
    if not selected:
        return jsonify({"success": False, "cancelled": True}), 200

    target_path = Path(selected).expanduser().resolve()
    if target_path.parent != dist_dir.resolve() or target_path.suffix.lower() != ".exe":
        return jsonify({"success": False, "error": "Choose an .exe name directly inside the dist folder."}), 400

    from build_export import sanitize_exe_name

    try:
        name = sanitize_exe_name(target_path.name)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    target_path = dist_dir / f"{name}.exe"

    with _EXPORT_LOCK:
        if _EXPORT_RUNNING:
            return jsonify({"success": False, "error": "Another executable is already being built."}), 409
        _EXPORT_RUNNING = True
        job_id = uuid.uuid4().hex[:12]
        _EXPORT_JOBS[job_id] = {
            "id": job_id,
            "scope": scope,
            "name": name,
            "status": "running",
            "progress": 1,
            "stage": "Preparing build",
            "elapsed_seconds": 0,
            "eta_seconds": None,
            "eta_updated_at": time.time(),
            "path": None,
            "error": None,
        }

    threading.Thread(
        target=_run_export_job,
        args=(job_id, scope, name, target_path),
        name=f"export-{job_id}",
        daemon=True,
    ).start()
    return jsonify({"success": True, "job_id": job_id, "name": name})


@app.get("/api/export/<job_id>")
def export_status(job_id: str):
    with _EXPORT_LOCK:
        job = _EXPORT_JOBS.get(job_id)
        if job is None:
            return jsonify({"success": False, "error": "Export job not found."}), 404
        return jsonify({"success": True, "job": dict(job)})


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


def run_server() -> None:
    from logger import banner
    banner(log, "DowFlow — Multi-Site Media Downloader")

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
