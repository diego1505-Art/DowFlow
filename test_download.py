import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import playlist
from launcher import (
    _is_dowflow_server,
    _is_redundant_server_line,
    _next_available_port,
    _read_appended_runtime_logs,
    _read_appended_server_logs,
    _read_existing_server_logs,
)


class FakeYoutubeDL:
    instances = []

    def __init__(self, options):
        self.options = options
        self.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def extract_info(self, url, download=True):
        if not download:
            return {
                "title": "clip",
                "formats": [
                    {"height": 2160, "vcodec": "vp9", "filesize": 1000 * 1024 * 1024},
                    {"height": 1080, "vcodec": "h264", "filesize": 100 * 1024 * 1024},
                    {"height": 480, "vcodec": "h264", "filesize": 10 * 1024 * 1024},
                    {"height": 240, "vcodec": "h264", "filesize": 2 * 1024 * 1024},
                    {"vcodec": "none", "acodec": "aac", "filesize": 5 * 1024 * 1024},
                ],
            }
        output_path = self.options["outtmpl"].replace("%(title).200s.%(ext)s", "clip.mp4")
        Path(output_path).write_bytes(b"video")
        return {"title": "clip", "ext": "mp4", "filepath": output_path}

    def download(self, urls):
        raise RuntimeError("HTTP Error 429: Too Many Requests")


class BotCheckYoutubeDL(FakeYoutubeDL):
    """YouTube requires a signed-in session when no cookie is provided."""

    def extract_info(self, url, download=True):
        if not (self.options.get("cookiefile") or self.options.get("cookiesfrombrowser")):
            raise RuntimeError("Sign in to confirm you're not a bot. Use --cookies")
        return super().extract_info(url, download)


class BotCheckLockedChromeYoutubeDL(FakeYoutubeDL):
    """YouTube requires a session, then Windows locks Chrome's cookie database."""

    def extract_info(self, url, download=True):
        if self.options.get("cookiesfrombrowser"):
            raise RuntimeError("Could not copy Chrome cookie database: Permission denied")
        if not self.options.get("cookiefile"):
            raise RuntimeError("Sign in to confirm you're not a bot. Use --cookies")
        return super().extract_info(url, download)


class DownloadStabilityTests(unittest.TestCase):
    def setUp(self):
        FakeYoutubeDL.instances.clear()
        # Keep the developer's real cookie exports out of these tests; the
        # default paths live under %APPDATA% and would otherwise change which
        # file _resolve_cookie_file() picks.
        self._cookie_temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._cookie_temp.cleanup)
        cookie_root = Path(self._cookie_temp.name)
        for name, value in {
            "YOUTUBE_COOKIES_FILE": cookie_root / "youtube_cookies.txt",
            "LINER_COOKIES_DIR": cookie_root / "DowFlow Music" / "cookies",
            "DOWFLOW_COOKIES_DIR": cookie_root / "DowFlow" / "cookies",
        }.items():
            patcher = patch.object(playlist, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        environment = patch.dict(
            os.environ,
            {
                "DOWFLOW_YOUTUBE_COOKIES": "",
                "DOWFLOW_INSTAGRAM_COOKIES": "",
                "DOWFLOW_TIKTOK_COOKIES": "",
                "DOWFLOW_COOKIES": "",
            },
        )
        environment.start()
        self.addCleanup(environment.stop)

    def test_yt_dlp_progress_hook_logs_percent_speed_and_eta(self):
        hook = playlist._make_download_progress_log_hook()
        with patch.object(playlist.log, "info") as log_info:
            hook(
                {
                    "status": "downloading",
                    "_percent_str": " 0.7%",
                    "_total_bytes_str": "1.45GiB",
                    "_speed_str": "5.04MiB/s",
                    "_eta_str": "04:53",
                }
            )

        log_info.assert_called_once_with(
            "%s", "[download] 0.7% of 1.45GiB at 5.04MiB/s ETA 04:53"
        )

    def test_download_logs_one_final_success_with_id_and_collision_note(self):
        with patch.object(playlist.yt_dlp, "YoutubeDL", FakeYoutubeDL), patch.object(
            playlist, "download_start", return_value=164
        ), patch.object(playlist, "download_finish"), patch.object(
            playlist.log, "success"
        ) as log_success, tempfile.TemporaryDirectory() as output:
            result = playlist.download_media(
                "https://www.youtube.com/shorts/12345678901",
                output_path=output,
                quality="720p",
                adaptive_quality=False,
            )

        log_success.assert_called_once_with(
            "Download #%d succeeded%s — %s",
            164,
            "",
            result["filename"],
        )

    def test_existing_dowflow_server_is_detected(self):
        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                import json

                return json.dumps(
                    {"ready": True, "service": "DowFlow", "build_id": "current-build"}
                ).encode("utf-8")

        with patch("launcher.urlopen", return_value=FakeResponse()), patch(
            "config.get_runtime_build_id", return_value="current-build"
        ):
            self.assertTrue(_is_dowflow_server("127.0.0.1", 5001))

    def test_dowflow_server_with_an_older_build_is_not_reused(self):
        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"ready":true,"service":"DowFlow","build_id":"old-build"}'

        with patch("launcher.urlopen", return_value=FakeResponse()), patch(
            "config.get_runtime_build_id", return_value="current-build"
        ):
            self.assertFalse(_is_dowflow_server("127.0.0.1", 5001))

    def test_non_dowflow_service_is_not_reused(self):
        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"ready":true,"service":"Other"}'

        with patch("launcher.urlopen", return_value=FakeResponse()):
            self.assertFalse(_is_dowflow_server("127.0.0.1", 5001))

    def test_next_port_finder_skips_occupied_ports(self):
        with patch("launcher._port_is_open", side_effect=[True, True, False]) as check_port:
            self.assertEqual(_next_available_port("127.0.0.1", 5001), 5004)

        self.assertEqual(check_port.call_count, 3)

    def test_server_http_access_logs_are_filtered(self):
        get_line = (
            '22:27:38 | INFO | werkzeug | 127.0.0.1 - - [05/Nov/2026 22:27:38] '
            '"GET /static/export.css HTTP/1.1" 304 -'
        )
        get_line_ansi = (
            '22:27:38 | INFO | werkzeug | 127.0.0.1 - - [05/Nov/2026 22:27:38] '
            '"\033[36mGET /static/export.css HTTP/1.1\033[0m" 304 -'
        )
        post_line = (
            '22:28:00 | INFO | werkzeug | 127.0.0.1 - - [05/Nov/2026 22:28:00] '
            '"POST /download-async HTTP/1.1" 200 -'
        )

        self.assertTrue(_is_redundant_server_line(get_line))
        self.assertTrue(_is_redundant_server_line(get_line_ansi))
        self.assertTrue(_is_redundant_server_line(post_line))

    def test_existing_server_logs_are_recovered_and_tailed(self):
        with tempfile.TemporaryDirectory() as temporary:
            log_path = Path(temporary) / "dowflow.log"
            startup_log = (
                "2026-11-04 23:03:19 | SUCCESS | app              | 100 | 1 | "
                "Server started at http://127.0.0.1:5001\n"
            )
            network_log = (
                "2026-11-04 23:03:20 | INFO    | playlist         | 100 | 1 | "
                "[perf] Connection tier: x16\n"
            )
            log_path.write_text(
                "2026-11-04 23:03:18 | INFO    | app              | 100 | 1 | "
                "DowFlow — Multi-Site Media Downloader\n"
                + startup_log
                + "2026-11-04 23:03:19 | WARNING | werkzeug         | 100 | 1 | "
                "WARNING: This is a development server. Do not use it in a production deployment.\n"
                + "2026-11-04 23:03:19 | INFO    | app              | 100 | 1 | "
                "Press Ctrl+C to stop\n"
                + "2026-11-04 23:03:19 | INFO    | werkzeug         | 100 | 1 | "
                "* Running on http://127.0.0.1:5001\n"
                + "2026-11-04 23:03:19 | INFO    | werkzeug         | 100 | 1 | "
                "Press CTRL+C to quit\n",
                encoding="utf-8",
            )

            existing_lines, offset = _read_existing_server_logs(log_path)
            self.assertTrue(
                any("Server started at http://127.0.0.1:5001" in line for line in existing_lines)
            )
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(network_log)

            appended_lines, _ = _read_appended_server_logs(log_path, offset)

        self.assertEqual(len(existing_lines), 4)
        self.assertEqual(len(appended_lines), 1)
        self.assertIn("Connection tier: x16", appended_lines[0])
        self.assertTrue(any("development server" in line for line in existing_lines))
        self.assertEqual(sum("Press Ctrl+C to stop" in line for line in existing_lines), 1)
        self.assertFalse(any("Running on http://" in line for line in existing_lines))
        self.assertFalse(any("Press CTRL+C to quit" in line for line in existing_lines))

    def test_runtime_log_reader_keeps_download_events(self):
        with tempfile.TemporaryDirectory() as temporary:
            log_path = Path(temporary) / "dowflow.log"
            log_path.write_text("", encoding="utf-8")
            offset = log_path.stat().st_size
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(
                    "2026-11-04 23:20:17 | INFO    | playlist         | 100 | 1 | "
                    "yt-dlp — Downloaded: sample.mp4\n"
                )

            lines, _ = _read_appended_runtime_logs(log_path, offset)

        self.assertEqual(len(lines), 1)
        self.assertIn("yt-dlp — Downloaded: sample.mp4", lines[0])

    def test_youtube_uses_native_fragments_and_skips_subtitles_by_default(self):
        with patch.object(playlist.yt_dlp, "YoutubeDL", FakeYoutubeDL):
            with tempfile.TemporaryDirectory() as output:
                result = playlist._ydlp_download(
                    "https://www.youtube.com/shorts/12345678901",
                    output_path=output,
                    quality="720p",
                    download_id=92,
                )
                self.assertTrue(Path(result["filepath"]).is_file())

        # A fixed quality uses yt-dlp native fragments.
        self.assertEqual(len(FakeYoutubeDL.instances), 1)
        options = FakeYoutubeDL.instances[-1].options
        self.assertNotIn("writesubtitles", options)
        self.assertTrue(options["noprogress"])
        self.assertNotIn("external_downloader", options)
        self.assertNotIn("external_downloader_args", options)
        self.assertTrue(options["quiet"])
        self.assertIn("[protocol^=http]", options["format"])
        self.assertEqual(options["retries"], 10)
        self.assertEqual(options["fragment_retries"], 10)
        self.assertEqual(options["remote_components"], ["ejs:github"])

    def test_adaptive_download_uses_native_progress_and_retries_lower_quality(self):
        class AdaptiveYoutubeDL(FakeYoutubeDL):
            calls = 0

            def extract_info(self, url, download=True):
                type(self).calls += 1
                progress_hooks = self.options.get("progress_hooks", [])
                height = 2160 if type(self).calls == 1 else 1440
                first = {
                    "status": "downloading",
                    "filename": "clip.mp4",
                    "info_dict": {"width": 2560, "height": height},
                    "downloaded_bytes": 0,
                    "total_bytes": 1700 * 1024 * 1024,
                }
                second = {
                    **first,
                    "downloaded_bytes": (11 if type(self).calls == 1 else 700) * 1024 * 1024,
                }
                with patch.object(playlist.log, "info"):
                    with patch.object(
                        playlist.time,
                        "time",
                        side_effect=[1000.0, 1011.0],
                    ):
                        for hook in progress_hooks:
                            hook(first)
                        for hook in progress_hooks:
                            hook(second)
                output_path = self.options["outtmpl"].replace("%(title).200s.%(ext)s", "clip.mp4")
                Path(output_path).write_bytes(b"video")
                return {"title": "clip", "ext": "mp4", "filepath": output_path}

        AdaptiveYoutubeDL.calls = 0
        with patch.object(playlist.yt_dlp, "YoutubeDL", AdaptiveYoutubeDL), patch.object(
            playlist, "get_connection_tier", return_value=16
        ):
            with tempfile.TemporaryDirectory() as output:
                result = playlist._ydlp_download(
                    "https://www.youtube.com/watch?v=123",
                    output_path=output,
                    quality="best",
                )

        self.assertTrue(result["quality_changed"])
        self.assertEqual(result["quality_used"], "1440p")
        self.assertEqual(len(AdaptiveYoutubeDL.instances), 2)
        self.assertNotIn("external_downloader", AdaptiveYoutubeDL.instances[0].options)
        self.assertEqual(
            AdaptiveYoutubeDL.instances[0].options["concurrent_fragment_downloads"], 16
        )
        self.assertEqual(
            AdaptiveYoutubeDL.instances[1].options["concurrent_fragment_downloads"], 16
        )
        self.assertEqual(
            AdaptiveYoutubeDL.instances[1].options["format_sort"], ["res:1440"]
        )

    def test_auto_subtitles_only_request_french(self):
        options = playlist._build_subtitle_lang_options(None)

        self.assertEqual(options["subtitleslangs"], ["fr"])

    def test_runtime_uses_browser_cookies_for_youtube(self):
        options = playlist.yt_dlp_runtime_options()

        self.assertNotIn("cookiesfrombrowser", options)
        youtube_options = playlist.yt_dlp_runtime_options(include_browser_cookies=True)
        self.assertEqual(youtube_options["cookiesfrombrowser"], ("chrome",))

    def test_youtube_first_attempt_uses_no_cookies(self):
        with patch.object(playlist.yt_dlp, "YoutubeDL", FakeYoutubeDL):
            with tempfile.TemporaryDirectory() as output:
                result = playlist._ydlp_download(
                    "https://www.youtube.com/shorts/12345678901",
                    output_path=output,
                )
                self.assertTrue(Path(result["filepath"]).is_file())

        self.assertEqual(len(FakeYoutubeDL.instances), 1)
        options = FakeYoutubeDL.instances[-1].options
        self.assertNotIn("cookiesfrombrowser", options)
        self.assertNotIn("cookiefile", options)

    def test_youtube_bot_check_retries_with_exported_cookie_file(self):
        with tempfile.TemporaryDirectory() as output:
            cookie_file = Path(output) / "youtube_cookies.txt"
            cookie_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
            with patch.object(playlist, "YOUTUBE_COOKIES_FILE", cookie_file):
                with patch.object(playlist.yt_dlp, "YoutubeDL", BotCheckYoutubeDL):
                    result = playlist._ydlp_download(
                        "https://www.youtube.com/shorts/12345678901",
                        output_path=output,
                        quality="240p",
                    )
                    self.assertTrue(Path(result["filepath"]).is_file())

        # Pas d'analyse adaptative car quality="240p" (pas "best")
        # First attempt without cookies, then retry with cookies.
        self.assertEqual(len(BotCheckYoutubeDL.instances), 2)
        first_options = BotCheckYoutubeDL.instances[0].options
        self.assertNotIn("cookiesfrombrowser", first_options)
        self.assertNotIn("cookiefile", first_options)
        retry_options = BotCheckYoutubeDL.instances[1].options
        self.assertEqual(retry_options["cookiefile"], str(cookie_file))
        self.assertNotIn("cookiesfrombrowser", retry_options)

    def test_resolve_cookie_file_selects_site_specific_exports(self):
        with tempfile.TemporaryDirectory() as output:
            root = Path(output)
            exports = {
                "youtube.com_cookies.txt": "https://www.youtube.com/watch?v=abc",
                "instagram.com_cookies.txt": "https://www.instagram.com/reel/123/",
                "tiktok.com_cookies.txt": "https://www.tiktok.com/@user/video/123",
                "example.org_cookies.txt": "https://example.org/video/123",
            }
            for filename in exports:
                (root / filename).write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")

            with patch.object(playlist, "YOUTUBE_COOKIES_FILE", root / "youtube_cookies.txt"):
                with patch.dict(
                    os.environ,
                    {
                        "DOWFLOW_YOUTUBE_COOKIES": "",
                        "DOWFLOW_INSTAGRAM_COOKIES": "",
                        "DOWFLOW_TIKTOK_COOKIES": "",
                        "DOWFLOW_COOKIES": "",
                    },
                ):
                    for filename, url in exports.items():
                        self.assertEqual(playlist._resolve_cookie_file(url), str(root / filename))

                    (root / "instagram.com_cookies.txt").unlink()
                    self.assertIsNone(
                        playlist._resolve_cookie_file("https://www.instagram.com/")
                    )

    def test_resolve_cookie_file_reads_dowflow_music_exports(self):
        with tempfile.TemporaryDirectory() as output:
            root = Path(output)
            liner_dir = root / "DowFlow Music" / "cookies"
            liner_dir.mkdir(parents=True)
            export = liner_dir / "youtube.com_cookies.txt"
            export.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
            with patch.object(playlist, "YOUTUBE_COOKIES_FILE", root / "youtube_cookies.txt"):
                with patch.object(playlist, "LINER_COOKIES_DIR", liner_dir):
                    with patch.dict(
                        os.environ,
                        {"DOWFLOW_YOUTUBE_COOKIES": "", "DOWFLOW_COOKIES": ""},
                    ):
                        self.assertEqual(
                            playlist._resolve_cookie_file(
                                "https://www.youtube.com/watch?v=abc"
                            ),
                            str(export),
                        )

    def test_resolve_cookie_file_falls_back_to_generic_export(self):
        with tempfile.TemporaryDirectory() as output:
            root = Path(output)
            generic_file = root / "cookies.txt"
            generic_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
            with patch.object(playlist, "YOUTUBE_COOKIES_FILE", root / "youtube_cookies.txt"):
                with patch.dict(
                    os.environ,
                    {
                        "DOWFLOW_YOUTUBE_COOKIES": "",
                        "DOWFLOW_INSTAGRAM_COOKIES": "",
                        "DOWFLOW_TIKTOK_COOKIES": "",
                        "DOWFLOW_COOKIES": "",
                    },
                ):
                    self.assertEqual(
                        playlist._resolve_cookie_file("https://www.instagram.com/"),
                        str(generic_file),
                    )

    def test_youtube_bot_check_without_cookie_file_reports_actionable_error(self):
        with patch.object(playlist.yt_dlp, "YoutubeDL", BotCheckLockedChromeYoutubeDL):
            with tempfile.TemporaryDirectory() as output:
                with patch.dict(os.environ, {"DOWFLOW_YOUTUBE_COOKIES": ""}):
                    with patch.object(playlist, "YOUTUBE_COOKIES_FILE", Path(output) / "missing.txt"):
                        with self.assertRaisesRegex(RuntimeError, "matching site cookie file"):
                            playlist._ydlp_download(
                                "https://www.youtube.com/shorts/12345678901",
                                output_path=output,
                                quality="240p",
                            )

        # Two attempts: no cookies, then Chrome cookies.
        self.assertEqual(len(BotCheckLockedChromeYoutubeDL.instances), 2)
        self.assertNotIn(
            "cookiesfrombrowser", BotCheckLockedChromeYoutubeDL.instances[0].options
        )
        self.assertEqual(
            BotCheckLockedChromeYoutubeDL.instances[1].options["cookiesfrombrowser"],
            ("chrome",),
        )

    def test_instagram_access_denied_retries_with_cookies(self):
        class InstagramAccessDeniedDL(FakeYoutubeDL):
            def extract_info(self, url, download=True):
                if not (self.options.get("cookiefile") or self.options.get("cookiesfrombrowser")):
                    raise RuntimeError("Streams found but inaccessible: ['blob:https://instagram.com/123']")
                return super().extract_info(url, download)

        with patch.object(playlist.yt_dlp, "YoutubeDL", InstagramAccessDeniedDL):
            with tempfile.TemporaryDirectory() as output:
                # Simulate the presence of Chrome cookies.
                with patch.dict(os.environ, {"DOWFLOW_YOUTUBE_COOKIES": ""}):
                    with patch.object(playlist, "YOUTUBE_COOKIES_FILE", Path(output) / "missing.txt"):
                        with patch.object(
                            playlist,
                            "yt_dlp_runtime_options",
                            side_effect=lambda include_browser_cookies=False: {
                                "cookiesfrombrowser": ("chrome",)
                            } if include_browser_cookies else {},
                        ):
                            result = playlist._ydlp_download(
                                "https://www.instagram.com/reel/123/",
                                output_path=output,
                                quality="240p",
                            )
                            self.assertTrue(Path(result["filepath"]).is_file())

        self.assertEqual(len(InstagramAccessDeniedDL.instances), 2)
        self.assertIn("cookiesfrombrowser", InstagramAccessDeniedDL.instances[1].options)

    def test_downloads_are_written_directly_into_the_root(self):
        with patch.object(playlist.yt_dlp, "YoutubeDL", FakeYoutubeDL), patch.object(
            playlist, "download_start", return_value=12
        ), patch.object(playlist, "download_finish"), tempfile.TemporaryDirectory() as output:
            result = playlist.download_media(
                "https://twitter.com/user/status/123",
                output_path=output,
                quality="best",
            )

        self.assertEqual(Path(result["filepath"]).parent, Path(output))
        self.assertEqual(result["folder"], "")
        self.assertFalse((Path(output) / "twitter").exists())

    def test_chrome_cookie_lock_has_actionable_message(self):
        message = playlist._friendly_cookie_error(
            RuntimeError("Could not copy Chrome cookie database: Permission denied")
        )

        self.assertIsNotNone(message)
        self.assertIn("Close all Chrome processes", message)
        self.assertIn("--disable-features=LockProfileCookieDatabase", message)
        self.assertIn("Netscape format", message)
        self.assertIn("cookies.txt", message)
        self.assertIn("do not share or publish it", message)

    def test_other_sites_use_native_fragments(self):
        with patch.object(playlist.yt_dlp, "YoutubeDL", FakeYoutubeDL):
            with patch.object(playlist, "get_connection_tier", return_value=32):
                with tempfile.TemporaryDirectory() as output:
                    result = playlist._ydlp_download(
                        "https://www.instagram.com/reel/example/",
                        output_path=output,
                        quality="720p",
                    )
                    self.assertTrue(Path(result["filepath"]).is_file())

        options = FakeYoutubeDL.instances[-1].options
        self.assertNotIn("external_downloader", options)
        self.assertNotIn("external_downloader_args", options)
        self.assertEqual(options["concurrent_fragment_downloads"], 32)

    def test_subtitles_are_requested_in_main_download_when_enabled(self):
        with patch.object(playlist.yt_dlp, "YoutubeDL", FakeYoutubeDL):
            with tempfile.TemporaryDirectory() as output:
                result = playlist._ydlp_download(
                    "https://example.com/video",
                    output_path=output,
                    write_subtitles=True,
                    language="fr",
                )
                self.assertTrue(Path(result["filepath"]).is_file())

        # Single pass: fetch subtitles in the same call as the video, avoiding a
        # second dedicated `yt-dlp` request (a source of HTTP 429 errors).
        self.assertEqual(len(FakeYoutubeDL.instances), 1)
        options = FakeYoutubeDL.instances[0].options
        self.assertTrue(options["writesubtitles"])
        self.assertTrue(options["writeautomaticsub"])
        self.assertEqual(options["subtitlesformat"], "vtt/best")
        self.assertIn("fr", options["subtitleslangs"])

    def test_subtitle_http_429_does_not_fail_video_download(self):
        class Subtitle429YoutubeDL(FakeYoutubeDL):
            def _write_subtitles(self, info_dict, filename):
                raise playlist.yt_dlp.utils.DownloadError("HTTP Error 429: Too Many Requests")

            def extract_info(self, url, download=True):
                self._write_subtitles({}, "clip.mp4")
                return super().extract_info(url, download)

        with patch.object(playlist.yt_dlp, "YoutubeDL", Subtitle429YoutubeDL):
            with tempfile.TemporaryDirectory() as output:
                result = playlist._ydlp_download(
                    "https://www.youtube.com/watch?v=123",
                    output_path=output,
                    write_subtitles=True,
                    language="fr",
                )
                self.assertTrue(Path(result["filepath"]).is_file(), repr(result))
        self.assertEqual(len(Subtitle429YoutubeDL.instances), 1)

    def test_subtitles_are_converted_to_vtt_when_ffmpeg_available(self):
        with patch.object(playlist, "_resolve_ffmpeg_dir", return_value="/fake/ffmpeg"):
            with patch.object(playlist.yt_dlp, "YoutubeDL", FakeYoutubeDL):
                with tempfile.TemporaryDirectory() as output:
                    playlist._ydlp_download(
                        "https://example.com/video",
                        output_path=output,
                        write_subtitles=True,
                        language="fr",
                    )

        postprocessors = FakeYoutubeDL.instances[0].options["postprocessors"]
        self.assertTrue(
            any(
                pp.get("key") == "FFmpegSubtitlesConvertor" and pp.get("format") == "vtt"
                for pp in postprocessors
            )
        )

    def test_adaptive_watch_hook_downgrades_when_eta_is_too_long(self):
        events = []
        hook = playlist._make_adaptive_watch_hook(events.append)
        first = {
            "status": "downloading",
            "filename": "video.f137.mp4",
            "info_dict": {"width": 3840, "height": 2160},
            "downloaded_bytes": 0,
            "total_bytes": 1000 * 1024 * 1024,
        }
        # 11 Mo en 11 s → ~1 Mo/s : ETA ≈ 989 s > seuil 4K (300 s)
        second = {**first, "downloaded_bytes": 11 * 1024 * 1024}

        base = 1000.0
        with patch.object(playlist.log, "info") as info:
            with patch.object(playlist.time, "time", side_effect=[base, base + 11.0]):
                hook(first)  # Start the observation window.
                with self.assertRaises(playlist._AdaptiveDowngrade) as ctx:
                    hook(second)  # Exceed the 10-second window and trigger a downgrade.

        info.assert_not_called()

        self.assertEqual(ctx.exception.quality, "1440p")
        self.assertEqual(
            ctx.exception.note,
            "2160p -> 1440p; ETA 989 s > 300 s; retry at 0%.",
        )
        self.assertEqual(events[-1]["status"], "adaptive_quality")
        self.assertEqual(events[-1]["quality_from"], "2160p")
        self.assertEqual(events[-1]["quality_to"], "1440p")
        self.assertEqual(events[-1]["adaptive_eta_seconds"], 989)
        self.assertEqual(events[-1]["adaptive_threshold_seconds"], 300)
        self.assertIn("retry at 0%", events[-1]["adaptive_note"])

    def test_adaptive_watch_keeps_720p_when_eta_is_under_twenty_minutes(self):
        hook = playlist._make_adaptive_watch_hook()
        first = {
            "status": "downloading",
            "filename": "video.f22.mp4",
            "info_dict": {"width": 1280, "height": 720},
            "downloaded_bytes": 0,
            "total_bytes": 1000 * 1024 * 1024,
        }
        second = {**first, "downloaded_bytes": 11 * 1024 * 1024}

        with patch.object(playlist.time, "time", side_effect=[1000.0, 1011.0]):
            hook(first)
            hook(second)

        self.assertEqual(playlist._ADAPTIVE_TIME_THRESHOLDS["720p"], 1200)

    def test_adaptive_watch_hook_keeps_quality_when_eta_is_short(self):
        hook = playlist._make_adaptive_watch_hook()
        first = {
            "status": "downloading",
            "filename": "video.f137.mp4",
            "info_dict": {"width": 3840, "height": 2160},
            "downloaded_bytes": 0,
            "total_bytes": 1000 * 1024 * 1024,
        }
        # 700 MB in 11 seconds is about 64 MB/s: ETA is well below the threshold.
        second = {**first, "downloaded_bytes": 700 * 1024 * 1024}

        base = 2000.0
        with patch.object(playlist.log, "info"):
            with patch.object(playlist.time, "time", side_effect=[base, base + 11.0]):
                hook(first)
                hook(second)  # Must finish without raising an exception.

    def test_adaptive_watch_hook_resets_for_new_file_and_can_retry(self):
        hook = playlist._make_adaptive_watch_hook()
        first = {
            "status": "downloading",
            "filename": "video-1.f137.mp4",
            "info_dict": {"width": 3840, "height": 2160},
            "downloaded_bytes": 0,
            "total_bytes": 1000 * 1024 * 1024,
        }
        short = {**first, "downloaded_bytes": 700 * 1024 * 1024}
        second = {
            "status": "downloading",
            "filename": "video-2.f137.mp4",
            "info_dict": {"width": 3840, "height": 2160},
            "downloaded_bytes": 0,
            "total_bytes": 1000 * 1024 * 1024,
        }
        slow = {**second, "downloaded_bytes": 11 * 1024 * 1024}

        base = 2500.0
        with patch.object(playlist.log, "info"):
            with patch.object(playlist.time, "time", side_effect=[base, base + 11.0, base + 12.0, base + 23.0, base + 24.0]):
                hook(first)
                hook(short)
                hook(second)
                with self.assertRaises(playlist._AdaptiveDowngrade):
                    hook(slow)

    def test_quality_target_uses_resolution_sort_for_portrait_videos(self):
        selector = playlist._build_video_format_string("240p", "mp4", True, prefer_http=True)

        # A `height<=240` filter would not match a portrait Short (144x256).
        self.assertNotIn("height<=", selector)
        self.assertIn("[protocol^=http]", selector)
        self.assertTrue(selector.endswith("bestvideo*+bestaudio/best"))
        self.assertEqual(playlist._build_video_format_sort("240p"), ["res:240"])
        self.assertIsNone(playlist._build_video_format_sort("best"))

    def test_quality_target_is_forwarded_to_yt_dlp_options(self):
        with patch.object(playlist.yt_dlp, "YoutubeDL", FakeYoutubeDL):
            with tempfile.TemporaryDirectory() as output:
                playlist._ydlp_download(
                    "https://www.youtube.com/shorts/12345678901",
                    output_path=output,
                    quality="720p",
                )

        self.assertEqual(FakeYoutubeDL.instances[0].options["format_sort"], ["res:720"])

    def test_adaptive_quality_attaches_watch_hook_only_when_enabled(self):
        with patch.object(playlist.yt_dlp, "YoutubeDL", FakeYoutubeDL):
            with tempfile.TemporaryDirectory() as output:
                # Enabled by default: attach a monitoring hook.
                playlist._ydlp_download(
                    "https://www.youtube.com/watch?v=123",
                    output_path=output,
                    quality="best",
                    adaptive_quality=True,
                )
                # Disabled: keep logging progress, but omit adaptive monitoring.
                playlist._ydlp_download(
                    "https://www.youtube.com/watch?v=123",
                    output_path=output,
                    quality="best",
                    adaptive_quality=False,
                )

        enabled_hooks = FakeYoutubeDL.instances[-2].options["progress_hooks"]
        disabled_hooks = FakeYoutubeDL.instances[-1].options["progress_hooks"]
        self.assertEqual(len(enabled_hooks), 2)
        self.assertEqual(len(disabled_hooks), 1)
        self.assertIn("_make_download_progress_log_hook", disabled_hooks[0].__qualname__)

    def test_async_progress_hook_uses_native_downloader_when_adaptation_is_disabled(self):
        with patch.object(playlist.yt_dlp, "YoutubeDL", FakeYoutubeDL):
            with tempfile.TemporaryDirectory() as output:
                playlist._ydlp_download(
                    "https://www.youtube.com/shorts/12345678901",
                    output_path=output,
                    quality="best",
                    adaptive_quality=False,
                    progress_hook=lambda event: None,
                )

        options = FakeYoutubeDL.instances[-1].options
        self.assertNotIn("external_downloader", options)
        self.assertEqual(len(options["progress_hooks"]), 2)


if __name__ == "__main__":
    unittest.main()
