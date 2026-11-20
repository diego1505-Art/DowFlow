import re
import unittest
from pathlib import Path
from unittest.mock import patch

import app as app_module


class MusicStreamUiRouteTests(unittest.TestCase):
    MUSIC_ROUTES = ("/music", "/music/stream", "/music/explore", "/music/liked")

    def setUp(self):
        app_module.app.config.update(TESTING=True)
        self.client = app_module.app.test_client()

    def test_music_routes_serve_the_same_built_react_entry_and_asset(self):
        bundle_index = Path(app_module.app.static_folder or "static") / "music-stream" / "index.html"
        if not bundle_index.is_file():
            self.skipTest("The compiled Music React bundle is not present.")

        responses = []
        try:
            for route in self.MUSIC_ROUTES:
                response = self.client.get(route)
                responses.append(response)
                self.assertEqual(response.status_code, 200, route)
                self.assertIn(b"DowFlow Music", response.data)
                self.assertIn(b'id="root"', response.data)

            expected = responses[0].data
            self.assertTrue(all(response.data == expected for response in responses[1:]))
            match = re.search(rb"/static/music-stream/assets/[^\"]+\.js", expected)
            self.assertIsNotNone(match)
            asset_response = self.client.get(match.group(0).decode("utf-8"))
            try:
                self.assertEqual(asset_response.status_code, 200)
                self.assertGreater(len(asset_response.data), 10_000)
            finally:
                asset_response.close()
        finally:
            for response in responses:
                response.close()

    def test_music_routes_return_503_when_react_bundle_is_missing(self):
        with patch.object(app_module.Path, "is_file", return_value=False):
            for route in self.MUSIC_ROUTES:
                response = self.client.get(route)
                try:
                    self.assertEqual(response.status_code, 503, route)
                finally:
                    response.close()

    def test_legacy_music_routes_are_removed(self):
        for route in ("/music/explore/legacy", "/music/liked/legacy"):
            with self.subTest(route=route):
                response = self.client.get(route)
                try:
                    self.assertEqual(response.status_code, 404)
                finally:
                    response.close()

    def test_music_export_scope_allows_only_react_routes(self):
        for route in self.MUSIC_ROUTES:
            with self.subTest(route=route):
                self.assertTrue(app_module._scope_allows_path("music", route))
        self.assertTrue(app_module._scope_allows_path("music", "/jobs/job-123"))
        self.assertFalse(app_module._scope_allows_path("music", "/jobs"))
        self.assertFalse(app_module._scope_allows_path("music", "/music/explore/legacy"))
        self.assertFalse(app_module._scope_allows_path("music", "/music/liked/legacy"))
        self.assertFalse(app_module._scope_allows_path("music", "/music/not-a-route"))
        self.assertFalse(app_module._scope_allows_path("music", "/history"))


if __name__ == "__main__":
    unittest.main()
