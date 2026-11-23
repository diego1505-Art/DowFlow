import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import download_manager
import music
import playlist


class FakeResponse:
    def __init__(self, payload=None, content=b""):
        self._payload = payload if payload is not None else {}
        self.content = content

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class MusicHelperTests(unittest.TestCase):
    def test_video_id_from_url(self):
        self.assertEqual(music._video_id_from_url("https://www.youtube.com/watch?v=abc123"), "abc123")
        self.assertEqual(music._video_id_from_url("https://youtu.be/xyz789"), "xyz789")
        self.assertEqual(music._video_id_from_url("https://www.youtube.com/shorts/short42"), "short42")
        self.assertIsNone(music._video_id_from_url("https://vimeo.com/12345"))

class MusicCoverTests(unittest.TestCase):
    def test_fetch_cover_uses_deezer(self):
        payload = {"data": [{"album": {"cover_xl": "https://cdn/cover.jpg"}}]}
        with patch.object(music.requests, "get", return_value=FakeResponse(payload)):
            self.assertEqual(music.fetch_cover_url("Artist", "Track"), "https://cdn/cover.jpg")

    def test_fetch_cover_returns_none_without_title(self):
        self.assertIsNone(music.fetch_cover_url("Artist", ""))


class MusicDownloadTests(unittest.TestCase):
    def test_download_writes_into_root_and_records_the_index(self):
        with tempfile.TemporaryDirectory() as output:
            media_path = Path(output) / "Track.mp3"
            media_path.write_bytes(b"audio")

            def fake_download_media(url, **kwargs):
                self.assertNotIn("force_folder", kwargs)
                self.assertEqual(kwargs["download_type"], "audio")
                self.assertEqual(Path(kwargs["output_path"]), Path(output))
                return {"filepath": str(media_path), "filename": "Track.mp3"}

            cover_payload = {"data": [{"album": {"cover_xl": "https://cdn/cover.jpg"}}]}

            def fake_get(url, **kwargs):
                if "deezer" in url:
                    return FakeResponse(cover_payload)
                return FakeResponse(content=b"image-bytes")

            with patch.object(playlist, "download_media", side_effect=fake_download_media):
                with patch.object(music.requests, "get", side_effect=fake_get):
                    with patch.object(
                        download_manager,
                        "get_data_root",
                        return_value=Path(output),
                    ):
                        result = music.download_music_track(
                            "https://www.youtube.com/watch?v=abc123",
                            output_path=output,
                            audio_format="mp3",
                            with_cover=True,
                            title="Track",
                            artist="Artist",
                        )

            self.assertTrue(Path(result["cover_path"]).is_file())
            self.assertEqual(result["cover_url"], "/media/Track.jpg")
            index = download_manager.load_index(index_root=Path(output))
            self.assertEqual(len(index), 1)
            self.assertEqual(index[0]["url"], "https://www.youtube.com/watch?v=abc123")
            self.assertEqual(index[0]["title"], "Track")
            self.assertEqual(index[0]["status"], "present")

if __name__ == "__main__":
    unittest.main()
