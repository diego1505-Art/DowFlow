import unittest
from pathlib import Path
from unittest.mock import patch

import app as app_module


class MusicDownloadApiTests(unittest.TestCase):
    def setUp(self):
        app_module.app.config.update(TESTING=True)
        self.client = app_module.app.test_client()

    def test_download_forwards_stable_youtube_url_options_and_output_folder(self):
        stable_url = "https://www.youtube.com/watch?v=stable-video-id"
        expected_folder = Path("/expected/download/folder")
        job_id = "music-job-123"

        with patch.object(app_module, "_download_folder", return_value=expected_folder) as folder_mock, patch.object(
            app_module, "start_download_job", return_value=job_id
        ) as start_job_mock:
            response = self.client.post(
                "/api/music/download",
                json={
                    "url": stable_url,
                    "audio_format": "flac",
                    "with_cover": True,
                    "title": "A track",
                    "artist": "An artist",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"success": True, "async": True, "job_id": job_id},
        )
        folder_mock.assert_called_once_with()
        start_job_mock.assert_called_once_with(
            app_module.music.download_music_track,
            stable_url,
            output_path=str(expected_folder),
            audio_format="flac",
            with_cover=True,
            title="A track",
            artist="An artist",
        )

    def test_job_status_is_available_in_frozen_music_scope(self):
        job_id = "music-job-456"
        job = {"id": job_id, "status": "running", "progress": 42.0}
        with patch.object(app_module, "IS_FROZEN", True), patch.object(
            app_module, "APP_SCOPE", "music"
        ), patch.object(app_module, "get_job", return_value=job) as get_job_mock:
            response = self.client.get(f"/jobs/{job_id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"success": True, "job": job})
        get_job_mock.assert_called_once_with(job_id)


if __name__ == "__main__":
    unittest.main()
