import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

import database
from music_stream_api import music_stream_api


class MusicStreamFavoritesApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(database, "DB_PATH", Path(self.temp_dir.name) / "test.db")
        self.db_patch.start()
        database.init_db()

        app = Flask(__name__)
        app.config.update(TESTING=True)
        app.register_blueprint(music_stream_api)
        self.client = app.test_client()

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_get_favorites_starts_empty(self):
        response = self.client.get("/api/music/stream/favorites")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"success": True, "items": []})

    def test_post_adds_favorite_and_get_returns_contract_fields(self):
        response = self.client.post(
            "/api/music/stream/favorites",
            json={
                "source": "youtube",
                "track_id": "yt-123",
                "title": "Track",
                "artist": "Artist",
                "cover_url": "https://example.test/cover.jpg",
                "duration_ms": 123000,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"success": True})
        get_response = self.client.get("/api/music/stream/favorites")
        self.assertEqual(get_response.status_code, 200)
        payload = get_response.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(len(payload["items"]), 1)
        item = payload["items"][0]
        self.assertEqual(
            set(item),
            {"source", "track_id", "title", "artist", "cover_url", "duration_ms", "created_at"},
        )
        self.assertEqual(
            {key: item[key] for key in item if key != "created_at"},
            {
                "source": "youtube",
                "track_id": "yt-123",
                "title": "Track",
                "artist": "Artist",
                "cover_url": "https://example.test/cover.jpg",
                "duration_ms": 123000,
            },
        )
        self.assertIsInstance(item["created_at"], float)

    def test_post_is_idempotent_and_updates_metadata(self):
        url = "/api/music/stream/favorites"
        first = {
            "source": "local",
            "track_id": "folder/song.mp3",
            "title": "Old title",
            "artist": "Old artist",
            "cover_url": None,
            "duration_ms": 1000,
        }
        self.assertEqual(self.client.post(url, json=first).status_code, 200)
        created_at = self.client.get(url).get_json()["items"][0]["created_at"]

        updated = {**first, "title": "New title", "artist": "New artist", "cover_url": "/cover.jpg", "duration_ms": 2500}
        self.assertEqual(self.client.post(url, json=updated).status_code, 200)
        items = self.client.get(url).get_json()["items"]

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "New title")
        self.assertEqual(items[0]["artist"], "New artist")
        self.assertEqual(items[0]["cover_url"], "/cover.jpg")
        self.assertEqual(items[0]["duration_ms"], 2500)
        self.assertEqual(items[0]["created_at"], created_at)

    def test_delete_reports_whether_favorite_existed(self):
        self.client.post(
            "/api/music/stream/favorites",
            json={"source": "local", "track_id": "folder/delete-me.mp3", "title": "Song", "artist": "Artist"},
        )

        removed = self.client.delete("/api/music/stream/favorites/local/folder/delete-me.mp3")
        missing = self.client.delete("/api/music/stream/favorites/local/folder/delete-me.mp3")

        self.assertEqual(removed.status_code, 200)
        self.assertEqual(removed.get_json(), {"success": True, "removed": True})
        self.assertEqual(missing.get_json(), {"success": True, "removed": False})
        self.assertEqual(self.client.get("/api/music/stream/favorites").get_json()["items"], [])

    def test_post_rejects_invalid_or_unbounded_fields(self):
        base = {"source": "youtube", "track_id": "id", "title": "Song", "artist": "Artist"}
        invalid_payloads = [
            {**base, "source": "spotify"},
            {**base, "track_id": "   "},
            {**base, "title": "  "},
            {**base, "title": "x" * 1001},
            {**base, "artist": "x" * 501},
            {**base, "duration_ms": -1},
            {**base, "duration_ms": True},
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                response = self.client.post("/api/music/stream/favorites", json=payload)
                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.get_json()["success"])

        missing_metadata = self.client.post(
            "/api/music/stream/favorites", json={"source": "youtube", "track_id": "id"}
        )
        malformed = self.client.post(
            "/api/music/stream/favorites", data="not-json", content_type="application/json"
        )
        self.assertEqual(missing_metadata.status_code, 400)
        self.assertEqual(malformed.status_code, 400)
        self.assertEqual(self.client.get("/api/music/stream/favorites").get_json()["items"], [])

    def test_stream_favorites_are_separate_from_legacy_file_favorites(self):
        database.favorite_add("song.mp3")
        self.client.post(
            "/api/music/stream/favorites",
            json={"source": "local", "track_id": "song.mp3", "title": "Song", "artist": "Artist"},
        )

        self.assertEqual(database.favorite_list(), ["song.mp3"])
        self.assertEqual(len(self.client.get("/api/music/stream/favorites").get_json()["items"]), 1)

    def test_blueprint_is_registered_and_allowed_in_music_scope(self):
        import app as app_module

        routes = {rule.rule for rule in app_module.app.url_map.iter_rules()}
        self.assertIn("/api/music/stream/favorites", routes)
        self.assertTrue(
            app_module._scope_allows_path("music", "/api/music/stream/favorites")
        )


if __name__ == "__main__":
    unittest.main()
