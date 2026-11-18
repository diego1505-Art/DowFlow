"""Standalone API for locally persisted streaming music favorites."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

import database

music_stream_api = Blueprint(
    "music_stream_api", __name__, url_prefix="/api/music/stream"
)


@music_stream_api.get("/favorites")
def list_favorites():
    return jsonify(success=True, items=database.music_stream_favorite_list())


@music_stream_api.post("/favorites")
def add_favorite():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(success=False, error="A JSON object is required"), 400

    try:
        database.music_stream_favorite_add(
            source=payload.get("source"),
            track_id=payload.get("track_id"),
            title=payload.get("title"),
            artist=payload.get("artist"),
            cover_url=payload.get("cover_url"),
            duration_ms=payload.get("duration_ms"),
        )
    except ValueError as exc:
        return jsonify(success=False, error=str(exc)), 400
    return jsonify(success=True), 200


@music_stream_api.delete("/favorites/<source>/<path:track_id>")
def delete_favorite(source: str, track_id: str):
    try:
        removed = database.music_stream_favorite_remove(source, track_id)
    except ValueError as exc:
        return jsonify(success=False, error=str(exc)), 400
    return jsonify(success=True, removed=removed)
