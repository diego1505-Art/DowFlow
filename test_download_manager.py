import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import download_manager

NETSCAPE = (
    "# Netscape HTTP Cookie File\n"
    ".youtube.com\tTRUE\t/\tTRUE\t1893456000\tSID\tabc\n"
    "#HttpOnly_.instagram.com\tTRUE\t/\tTRUE\t1893456000\tsessionid\tdef\n"
)


class MusicIndexTests(unittest.TestCase):
    def test_records_a_download_in_an_index_next_to_the_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            track = root / "Track.mp3"
            track.write_bytes(b"audio")

            entry = download_manager.record_download(
                "https://youtu.be/abc123", "Track", "Artist", track, index_root=root
            )

            self.assertEqual(entry["status"], "present")
            self.assertTrue((root / "dowflow_music_index.json").is_file())
            payload = json.loads(
                (root / "dowflow_music_index.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(payload), 1)
            self.assertEqual(
                set(payload[0]),
                {"url", "title", "artist", "path", "downloaded_at", "status"},
            )
            self.assertEqual(payload[0]["url"], "https://youtu.be/abc123")
            self.assertEqual(payload[0]["title"], "Track")
            self.assertEqual(payload[0]["artist"], "Artist")

    def test_recording_the_same_url_updates_instead_of_duplicating(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "Track.mp3"
            first.write_bytes(b"audio")
            download_manager.record_download(
                "https://youtu.be/abc", "Track", "Artist", first, index_root=root
            )

            second = root / "Track remaster.mp3"
            second.write_bytes(b"audio")
            download_manager.record_download(
                "https://youtu.be/abc",
                "Track (remaster)",
                "Artist",
                second,
                index_root=root,
            )

            entries = download_manager.load_index(index_root=root)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["title"], "Track (remaster)")
        self.assertEqual(entries[0]["path"], str(second))

    def test_manual_deletion_marks_the_entry_deleted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            track = root / "Track.mp3"
            track.write_bytes(b"audio")
            download_manager.record_download(
                "https://youtu.be/abc", "Track", "Artist", track, index_root=root
            )

            track.unlink()
            entries = download_manager.mark_missing(index_root=root)

            self.assertEqual(entries[0]["status"], "deleted")
            self.assertTrue(
                download_manager.is_deleted("https://youtu.be/abc", index_root=root)
            )
            self.assertEqual(download_manager.present_entries(index_root=root), [])

    def test_mark_deleted_matches_a_filename(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            track = root / "Track.mp3"
            track.write_bytes(b"audio")
            download_manager.record_download(
                "https://youtu.be/abc", "Track", "Artist", track, index_root=root
            )

            self.assertTrue(
                download_manager.mark_deleted(filename="Track.mp3", index_root=root)
            )
            entry = download_manager.find_entry(
                "https://youtu.be/abc", index_root=root
            )
        self.assertEqual(entry["status"], "deleted")

    def test_index_moves_out_of_downloads_into_the_dowflow_data_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            downloads = base / "Downloads"
            data_root = base / "DowFlow"
            downloads.mkdir()
            data_root.mkdir()
            legacy = downloads / "dowflow_music_index.json"
            legacy.write_text(
                json.dumps(
                    [
                        {
                            "url": "https://youtu.be/abc",
                            "title": "Track",
                            "artist": "Artist",
                            "path": str(downloads / "Track.mp3"),
                            "downloaded_at": "2026-01-01T00:00:00+00:00",
                            "status": "present",
                        }
                    ]
                ),
                encoding="utf-8",
            )

            with patch.object(
                download_manager, "get_data_root", return_value=data_root
            ), patch.object(
                download_manager, "download_root", return_value=downloads
            ):
                entries = download_manager.load_index()

            self.assertFalse(legacy.exists())
            self.assertTrue((data_root / "dowflow_music_index.json").is_file())
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["url"], "https://youtu.be/abc")

    def test_corrupt_index_is_ignored(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "dowflow_music_index.json").write_text("not json", encoding="utf-8")
            self.assertEqual(download_manager.load_index(index_root=root), [])


class CookieImportTests(unittest.TestCase):
    def test_parse_reads_domains_including_httponly_lines(self):
        self.assertEqual(
            download_manager.parse_netscape_cookies(NETSCAPE),
            ["youtube.com", "instagram.com"],
        )

    def test_parse_rejects_non_netscape_content(self):
        self.assertEqual(download_manager.parse_netscape_cookies('{"cookies": []}'), [])
        self.assertEqual(
            download_manager.parse_netscape_cookies(
                ".youtube.com\tTRUE\t/\tTRUE\t1893456000\tSID"
            ),
            [],
        )
        self.assertEqual(
            download_manager.parse_netscape_cookies(
                ".youtube.com\tTRUE\t/\tMAYBE\t1893456000\tSID\tvalue"
            ),
            [],
        )

    def test_import_validates_and_copies_the_export(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "youtube_cookies.txt"
            source.write_text(NETSCAPE, encoding="utf-8")
            destination = base / "DowFlow" / "cookies"

            imported = download_manager.import_cookie_file(source, destination)

            self.assertEqual(imported["filename"], "youtube_cookies.txt")
            self.assertEqual(imported["domains"], ["youtube.com", "instagram.com"])
            self.assertTrue((destination / "youtube_cookies.txt").is_file())
            self.assertEqual(
                download_manager.list_imported_cookies(destination),
                ["youtube_cookies.txt"],
            )

    def test_import_names_a_plain_youtube_export_for_ytdlp(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "cooki youtube.txt"
            source.write_text(NETSCAPE, encoding="utf-8")
            destination = base / "cookies"

            imported = download_manager.import_cookie_file(source, destination)

            self.assertEqual(imported["filename"], "youtube_cookies.txt")
            self.assertTrue((destination / "youtube_cookies.txt").is_file())

    def test_import_prefers_youtube_in_a_combined_export(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "export.txt"
            source.write_text(
                "# Netscape HTTP Cookie File\n"
                ".instagram.com\tTRUE\t/\tTRUE\t1893456000\tsessionid\tdef\n"
                ".youtube.com\tTRUE\t/\tTRUE\t1893456000\tSID\tabc\n",
                encoding="utf-8",
            )
            destination = base / "cookies"

            imported = download_manager.import_cookie_file(source, destination)

            self.assertEqual(imported["filename"], "youtube_cookies.txt")

    def test_import_rejects_an_invalid_export(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "bad.txt"
            source.write_text("this is not a cookie export", encoding="utf-8")

            with self.assertRaises(ValueError):
                download_manager.import_cookie_file(source, base / "cookies")
            self.assertFalse((base / "cookies" / "bad.txt").exists())


class MusicSettingsApiTests(unittest.TestCase):
    def test_settings_endpoint_exposes_the_root_and_cookie_folder(self):
        import app as app_module

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(app_module, "get_download_path", return_value=root), patch.object(
                app_module, "DOWFLOW_COOKIES_DIR", root / "cookies"
            ):
                response = app_module.app.test_client().get("/api/music/settings")

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["download_root"], str(root))
        self.assertEqual(payload["cookies"], [])

    def test_cookie_import_route_copies_a_valid_export(self):
        import app as app_module

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "youtube_cookies.txt"
            source.write_text(NETSCAPE, encoding="utf-8")
            destination = base / "DowFlow" / "cookies"
            with patch.object(
                app_module, "select_cookie_file", return_value=str(source)
            ), patch.object(app_module, "DOWFLOW_COOKIES_DIR", destination):
                response = app_module.app.test_client().post("/api/music/cookies/import")

            payload = response.get_json()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(payload["filename"], "youtube_cookies.txt")
            self.assertTrue((destination / "youtube_cookies.txt").is_file())

    def test_cookie_import_path_route_accepts_the_native_picker_result(self):
        import app as app_module

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "cooki youtube.txt"
            source.write_text(NETSCAPE, encoding="utf-8")
            destination = base / "DowFlow" / "cookies"
            with patch.object(app_module, "DOWFLOW_COOKIES_DIR", destination):
                response = app_module.app.test_client().post(
                    "/api/music/cookies/import-path", json={"path": str(source)}
                )

            payload = response.get_json()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(payload["filename"], "youtube_cookies.txt")
            self.assertTrue((destination / "youtube_cookies.txt").is_file())

    def test_download_root_route_updates_the_single_root(self):
        import app as app_module

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(
                app_module, "set_download_path", return_value=root
            ) as setter:
                response = app_module.app.test_client().post(
                    "/api/music/download-root", json={"path": str(root)}
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["path"], str(root))
            setter.assert_called_once_with(str(root))


if __name__ == "__main__":
    unittest.main()
