import re
import unittest

import app as app_module


class MusicStreamUiRouteTests(unittest.TestCase):
    def setUp(self):
        app_module.app.config.update(TESTING=True)
        self.client = app_module.app.test_client()

    def test_music_home_links_to_streaming(self):
        response = self.client.get("/music")
        try:
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'href="/music/stream"', response.data)
        finally:
            response.close()

    def test_stream_route_serves_built_react_entry_and_asset(self):
        response = self.client.get("/music/stream")
        try:
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"DowFlow Music", response.data)
            match = re.search(rb"/static/music-stream/assets/[^\"]+\.js", response.data)
            self.assertIsNotNone(match)
            asset_response = self.client.get(match.group(0).decode("utf-8"))
            try:
                self.assertEqual(asset_response.status_code, 200)
                self.assertGreater(len(asset_response.data), 10_000)
            finally:
                asset_response.close()
        finally:
            response.close()

    def test_music_export_scope_allows_stream_route(self):
        self.assertTrue(app_module._scope_allows_path("music", "/music/stream"))


if __name__ == "__main__":
    unittest.main()
