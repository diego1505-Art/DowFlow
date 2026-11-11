import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import database


class Phase4StatsTests(unittest.TestCase):
    def test_database_records_strategy_and_fragmentation(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "stats.db"
            with patch.object(database, "DB_PATH", db_path):
                database.init_db()
                download_id = database.download_start("https://example.test/file.mp4")
                database.download_finish(
                    download_id,
                    "success",
                    extractor_type="yt-dlp",
                    file_size_bytes=1024,
                    duration_ms=2500,
                    strategy="yt-dlp-mono",
                    is_fragmented=False,
                )
                stats = database.download_stats()

            self.assertEqual(stats["totals"]["total"], 1)
            self.assertEqual(stats["totals"]["successes"], 1)
            self.assertEqual(stats["by_strategy"][0]["strategy"], "yt-dlp-mono")
            self.assertFalse(stats["recent"][0]["is_fragmented"])

    def test_stats_api_and_page_are_available(self):
        import app

        client = app.app.test_client()
        response = client.get("/api/stats")
        page = client.get("/stats")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Download performance", page.data)


if __name__ == "__main__":
    unittest.main()
