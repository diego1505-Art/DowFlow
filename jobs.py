"""
DowFlow — Download job queue and real-time progress.
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Callable

from logger import get_logger

log = get_logger("jobs")

_LOCK = threading.Lock()
_JOBS: dict[str, dict[str, Any]] = {}
_MAX_JOBS = 200

# Allowed fields in job.result (never the raw yt-dlp info dictionary)
_SAFE_RESULT_KEYS = {
    "success",
    "skipped",
    "reason",
    "message",
    "error",
    "filename",
    "filepath",
    "relative_path",
    "folder",
    "language",
    "title",
    "subtitle_files",
    "player_name",
    "lecteur",
    "stream_url",
    "quality_requested",
    "quality_used",
    "quality_changed",
    "adaptive_note",
    "artist",
    "duration",
    "cover_url",
    "cover_path",
}


def sanitize_job_result(result: dict[str, Any] | None) -> dict[str, Any] | None:
    """Remove non-JSON-serializable objects (e.g. FFmpegMergerPP in info)."""
    if not isinstance(result, dict):
        return None
    out: dict[str, Any] = {}
    for key in _SAFE_RESULT_KEYS:
        if key not in result:
            continue
        value = result[key]
        if key == "subtitle_files" and isinstance(value, list):
            out[key] = [str(item) for item in value]
        elif isinstance(value, (str, int, float, bool)) or value is None:
            out[key] = value
        else:
            out[key] = str(value)
    return out


def _new_job(url: str, meta: dict[str, Any] | None = None) -> str:
    job_id = uuid.uuid4().hex[:12]
    now = time.time()
    with _LOCK:
        if len(_JOBS) >= _MAX_JOBS:
            # Purge the oldest completed jobs.
            finished = sorted(
                (
                    (jid, j)
                    for jid, j in _JOBS.items()
                    if j.get("status") in {"success", "failed", "skipped"}
                ),
                key=lambda item: item[1].get("finished_at") or item[1].get("started_at") or 0,
            )
            for jid, _ in finished[: max(1, len(finished) // 4)]:
                _JOBS.pop(jid, None)
        _JOBS[job_id] = {
            "id": job_id,
            "url": url,
            "status": "queued",
            "progress": 0.0,
            "speed": None,
            "eta": None,
            "message": "Queued",
            "result": None,
            "error": None,
            "started_at": now,
            "finished_at": None,
            "meta": meta or {},
        }
    return job_id


def update_job(job_id: str, **fields: Any) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        job.update(fields)


def get_job(job_id: str) -> dict[str, Any] | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job else None


def list_jobs(limit: int = 50) -> list[dict[str, Any]]:
    with _LOCK:
        items = sorted(_JOBS.values(), key=lambda j: j.get("started_at") or 0, reverse=True)
        return [dict(j) for j in items[:limit]]


def make_progress_hook(job_id: str) -> Callable[[dict[str, Any]], None]:
    def hook(d: dict[str, Any]) -> None:
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            pct = (done / total * 100.0) if total else float(d.get("_percent_str", "0").replace("%", "") or 0)
            try:
                pct = float(pct)
            except (TypeError, ValueError):
                pct = 0.0
            speed = d.get("speed")
            eta = d.get("eta")
            update_job(
                job_id,
                status="running",
                progress=max(0.0, min(99.0, pct)),
                speed=speed,
                eta=eta,
                message=f"Downloading {pct:.1f}%",
            )
        elif status == "finished":
            update_job(job_id, progress=99.0, message="Finalizing / merging...")
        elif status == "adaptive_quality":
            update_job(
                job_id,
                quality_changed=True,
                quality_from=d.get("quality_from"),
                quality_to=d.get("quality_to"),
                quality_used=d.get("quality_used"),
                adaptive_note=d.get("adaptive_note"),
                adaptive_eta_seconds=d.get("adaptive_eta_seconds"),
                adaptive_threshold_seconds=d.get("adaptive_threshold_seconds"),
                message=d.get("adaptive_note") or "Quality lowered automatically",
            )
        elif status == "error":
            update_job(job_id, message=str(d.get("error") or "yt-dlp error"))

    return hook


def start_download_job(download_fn: Callable[..., dict[str, Any]], url: str, **kwargs: Any) -> str:
    """Run download_fn in a thread and return the job ID immediately."""
    job_id = _new_job(url, meta={k: v for k, v in kwargs.items() if k != "progress_hook"})
    update_job(job_id, status="running", message="Starting...")

    def runner() -> None:
        try:
            kwargs_with_hook = dict(kwargs)
            kwargs_with_hook["progress_hook"] = make_progress_hook(job_id)
            result = download_fn(url, **kwargs_with_hook)
            result_dict = result if isinstance(result, dict) else {}
            safe = sanitize_job_result(result_dict or None)
            filepath = (safe or {}).get("filepath") or result_dict.get("filepath")
            if result_dict.get("skipped"):
                update_job(
                    job_id,
                    status="skipped",
                    progress=100.0,
                    message=(safe or {}).get("reason") or "Skipped",
                    result=safe,
                    finished_at=time.time(),
                )
            elif filepath:
                update_job(
                    job_id,
                    status="success",
                    progress=100.0,
                    message=(safe or {}).get("filename") or "OK",
                    result=safe,
                    finished_at=time.time(),
                )
            else:
                update_job(
                    job_id,
                    status="failed",
                    progress=100.0,
                    message=(safe or {}).get("error") or "Failed",
                    error=(safe or {}).get("error"),
                    result=safe,
                    finished_at=time.time(),
                )
        except Exception as e:
            log.error("Job %s failed: %s", job_id, e, exc_info=True)
            update_job(
                job_id,
                status="failed",
                progress=100.0,
                message=str(e),
                error=str(e),
                finished_at=time.time(),
            )

    threading.Thread(target=runner, name=f"dl-{job_id}", daemon=True).start()
    return job_id
