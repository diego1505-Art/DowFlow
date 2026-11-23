import io
import json
import os
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import build_export
import config
import bootstrap


class PortableConfigurationTests(unittest.TestCase):
    def test_dependency_setup_transitions_from_loading_to_ready(self):
        class DeferredThread:
            def __init__(self, target, **kwargs):
                self.target = target

            def start(self):
                return None

            def is_alive(self):
                return False

        progress = {"status": "pending", "percent": 0, "stage": "Waiting", "error": None}
        with patch.object(bootstrap, "IS_FROZEN", True), patch.object(
            bootstrap, "_DEPENDENCY_THREAD", None
        ), patch.object(bootstrap, "_PROGRESS", progress), patch.object(
            bootstrap.threading, "Thread", DeferredThread
        ), patch.object(
            bootstrap,
            "ensure_external_dependencies",
            side_effect=lambda callback: callback(80, "Updating Chromium"),
        ), patch("utils.clear_ffmpeg_cache"):
            worker = bootstrap.start_dependency_setup()
            self.assertEqual(bootstrap.dependency_progress()["status"], "loading")
            worker.target()
            final_progress = bootstrap.dependency_progress()

        self.assertEqual(final_progress["status"], "ready")
        self.assertEqual(final_progress["percent"], 100)

    def test_frozen_bin_folder_is_inside_the_saved_media_root(self):
        media_root = Path("D:/media")
        with patch.object(config, "IS_FROZEN", True), patch.object(
            config, "BASE_DIR", media_root
        ):
            self.assertEqual(config.get_bin_folder(), media_root / "bin")

        with patch.object(config, "IS_FROZEN", False):
            self.assertEqual(config.get_bin_folder(), config.BIN_FOLDER)

    def test_installed_layout_shares_data_between_menu_and_submenus(self):
        with tempfile.TemporaryDirectory() as temporary:
            install = Path(temporary) / "DowFlow"
            data = install / "data"
            data.mkdir(parents=True)
            menu_exe = install / "menu"
            video_exe = install / "submenus" / "video"
            menu_exe.mkdir()
            video_exe.mkdir(parents=True)

            self.assertEqual(config.find_installed_data_root(menu_exe), data.resolve())
            self.assertEqual(config.find_installed_data_root(video_exe), data.resolve())

    def test_frozen_install_prefers_the_shared_tools_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_root = Path(temporary) / "DowFlow" / "data"
            (data_root / "tools").mkdir(parents=True)

            with patch.object(config, "IS_FROZEN", True), patch.object(
                config, "BASE_DIR", data_root
            ):
                self.assertEqual(config.get_bin_folder(), data_root / "tools")
                self.assertEqual(
                    config.get_chromium_folder(), data_root / "tools" / "chromium"
                )

    def test_bundled_tools_skip_runtime_downloads(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tools = root / "tools"
            tools.mkdir()
            (tools / ".tools.ready").write_text("{}", encoding="utf-8")
            (tools / "ffmpeg.exe").write_bytes(b"ffmpeg")
            (tools / "ffprobe.exe").write_bytes(b"ffprobe")
            progress = []

            with patch.object(bootstrap, "IS_FROZEN", True), patch.object(
                bootstrap, "get_bin_folder", return_value=tools
            ), patch.object(
                bootstrap, "get_download_path", return_value=root
            ), patch.object(bootstrap, "configure_runtime_paths"), patch.object(
                bootstrap, "_read_url"
            ) as read_url:
                bootstrap.ensure_external_dependencies(
                    lambda percent, stage, **kwargs: progress.append((percent, stage))
                )

            read_url.assert_not_called()
            self.assertEqual(progress[-1], (100, "Media tools ready"))

    def test_first_frozen_launch_creates_the_download_folder_without_prompting(self):
        import folder_picker
        import launcher

        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "Downloads"
            with patch.object(launcher.sys, "frozen", True, create=True), patch.object(
                config, "get_download_path", return_value=folder
            ), patch.object(config, "configure_runtime_paths") as configure, patch.object(
                folder_picker, "select_download_folder"
            ) as picker:
                self.assertTrue(launcher._ensure_portable_download_folder())

            self.assertTrue(folder.is_dir())
            picker.assert_not_called()
            configure.assert_called_once_with(folder)

    def test_missing_download_folder_is_recreated_without_prompting(self):
        import folder_picker
        import launcher

        with tempfile.TemporaryDirectory() as temporary:
            missing_root = Path(temporary) / "gone"
            with patch.object(launcher.sys, "frozen", True, create=True), patch.object(
                config, "get_download_path", return_value=missing_root
            ), patch.object(config, "configure_runtime_paths"), patch.object(
                folder_picker, "select_download_folder"
            ) as picker:
                self.assertTrue(launcher._ensure_portable_download_folder())

            self.assertTrue(missing_root.is_dir())
            picker.assert_not_called()

    def test_frozen_mode_defaults_to_the_windows_downloads_folder(self):
        with patch.object(config, "IS_FROZEN", True), patch.object(
            config, "_saved_download_path", return_value=None
        ):
            self.assertEqual(
                config.get_download_path(required=False), config.DOWNLOAD_FOLDER
            )
            self.assertEqual(config.get_download_path(), config.DOWNLOAD_FOLDER)

    def test_selected_folder_is_saved_without_copying_bundled_media(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app_dir = root / "app"
            selected = root / "media"
            app_dir.mkdir()
            selected.mkdir()
            bundled_music = app_dir / "music"
            bundled_music.mkdir()
            (bundled_music / "seed.mp3").write_bytes(b"audio")
            config_file = app_dir / "config.json"
            selected_config = selected / "config.json"

            with patch.object(config, "IS_FROZEN", True), patch.object(
                config, "BASE_DIR", app_dir
            ), patch.object(config, "CONFIG_FILE", config_file):
                self.assertEqual(config.set_download_path(selected), selected.resolve())
                self.assertEqual(config.get_download_path(), selected.resolve())

            self.assertEqual(
                json.loads(selected_config.read_text(encoding="utf-8"))["download_path"],
                str(selected.resolve()),
            )
            self.assertFalse(config_file.exists())
            self.assertFalse((selected / "downloads").exists())
            self.assertTrue((selected / "bin").is_dir())
            self.assertFalse((selected / "music").exists())

    def test_source_folder_selection_keeps_data_in_the_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            selected = root / "media"
            project.mkdir()
            selected.mkdir()

            with patch.object(config, "IS_FROZEN", False), patch.object(
                config, "ELECTRON_SHELL", False
            ), patch.object(config, "BASE_DIR", project), patch.object(
                config, "CONFIG_FILE", project / "config.json"
            ), patch.object(config, "BIN_FOLDER", project / "bin"):
                config.set_download_path(selected)
                self.assertEqual(config.get_download_path(), selected.resolve())

            self.assertTrue((project / "config.json").is_file())
            self.assertTrue((selected / "bin").is_dir())
            self.assertFalse((selected / "config.json").exists())

    def test_portable_data_extraction_never_overwrites_existing_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = root / "bundle" / "portable_data"
            app_dir = root / "app"
            bundle.mkdir(parents=True)
            (bundle / "browser_profile").mkdir()
            (bundle / "dowflow.db").write_bytes(b"bundled-db")
            (bundle / "config.json").write_text(
                json.dumps({"download_path": ""}), encoding="utf-8"
            )
            (bundle / "browser_profile" / "profile.dat").write_bytes(b"profile")
            app_dir.mkdir()
            (app_dir / "dowflow.db").write_bytes(b"user-db")
            media_root = root / "media"
            media_root.mkdir()
            (app_dir / "config.json").write_text(
                json.dumps({"download_path": str(media_root)}), encoding="utf-8"
            )

            with patch.object(config, "IS_FROZEN", True), patch.object(
                config, "BUNDLE_DIR", bundle.parent
            ), patch.object(config, "BASE_DIR", app_dir), patch.object(
                config, "CONFIG_FILE", app_dir / "config.json"
            ), patch.dict(os.environ, {"PATH": ""}):
                config.initialize_portable_data()
                self.assertEqual(
                    os.environ["PLAYWRIGHT_BROWSERS_PATH"],
                    str(app_dir / "bin" / "ms-playwright"),
                )

            self.assertEqual((app_dir / "dowflow.db").read_bytes(), b"user-db")
            self.assertEqual(
                json.loads((app_dir / "config.json").read_text(encoding="utf-8")),
                {"download_path": str(media_root)},
            )
            self.assertEqual(
                (app_dir / "browser_profile" / "profile.dat").read_bytes(), b"profile"
            )
            self.assertFalse((app_dir / "bin").exists())

    def test_portable_config_is_extracted_only_when_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            portable_data = root / "bundle" / "portable_data"
            portable_data.mkdir(parents=True)
            (portable_data / "config.json").write_text(
                json.dumps({"download_path": ""}), encoding="utf-8"
            )
            app_dir = root / "app"
            app_dir.mkdir()
            config_file = app_dir / "config.json"

            with patch.object(config, "IS_FROZEN", True), patch.object(
                config, "BUNDLE_DIR", portable_data.parent
            ), patch.object(config, "BASE_DIR", app_dir), patch.object(
                config, "CONFIG_FILE", config_file
            ):
                config.initialize_portable_data()
                self.assertEqual(
                    json.loads(config_file.read_text(encoding="utf-8")),
                    {"download_path": ""},
                )
                config_file.write_text(
                    json.dumps({"download_path": "C:/user-media"}), encoding="utf-8"
                )
                config.initialize_portable_data()

            self.assertEqual(
                json.loads(config_file.read_text(encoding="utf-8")),
                {"download_path": "C:/user-media"},
            )

    def test_ffmpeg_bootstrap_keeps_runtime_dlls_in_bin(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive_buffer = io.BytesIO()
            with zipfile.ZipFile(archive_buffer, "w") as archive:
                archive.writestr("ffmpeg-build/bin/ffmpeg.exe", b"ffmpeg")
                archive.writestr("ffmpeg-build/bin/ffprobe.exe", b"ffprobe")
                archive.writestr("ffmpeg-build/bin/avcodec-1.dll", b"runtime")
                archive.writestr("ffmpeg-build/LICENSE.txt", b"license")
            archive_bytes = archive_buffer.getvalue()
            bin_dir = Path(temporary) / "bin"
            bin_dir.mkdir()

            def fake_read_url(url, destination=None, progress_callback=None):
                if destination is None:
                    return b"f" * 64
                destination.write_bytes(archive_bytes)
                if progress_callback is not None:
                    progress_callback(100)
                return b""

            with patch.object(bootstrap, "get_bin_folder", return_value=bin_dir), patch.object(
                bootstrap, "_read_url", side_effect=fake_read_url
            ), patch.object(bootstrap, "_sha256", return_value="f" * 64):
                bootstrap._install_ffmpeg()

            self.assertEqual((bin_dir / "ffmpeg.exe").read_bytes(), b"ffmpeg")
            self.assertEqual((bin_dir / "ffprobe.exe").read_bytes(), b"ffprobe")
            self.assertEqual((bin_dir / "avcodec-1.dll").read_bytes(), b"runtime")
            self.assertFalse((bin_dir / "LICENSE.txt").exists())

    def test_external_dependency_check_uses_media_root_bin_and_reports_progress(self):
        with tempfile.TemporaryDirectory() as temporary:
            media_root = Path(temporary) / "media"
            bin_dir = media_root / "bin"
            bin_dir.mkdir(parents=True)
            (bin_dir / "ffmpeg.exe").write_bytes(b"ffmpeg")
            (bin_dir / "ffprobe.exe").write_bytes(b"ffprobe")
            (bin_dir / ".ffmpeg.sha256").write_text("a" * 64, encoding="ascii")
            progress = []

            with patch.object(bootstrap, "get_download_path", return_value=media_root), patch.object(
                bootstrap, "get_bin_folder", return_value=bin_dir
            ), patch.object(bootstrap, "configure_runtime_paths", return_value=bin_dir) as configure, patch.object(
                bootstrap, "_read_url", return_value=("a" * 64).encode("ascii")
            ), patch.object(
                bootstrap, "_install_playwright_node"
            ), patch.object(
                bootstrap, "_install_chromium"
            ) as install_chromium:
                bootstrap.ensure_external_dependencies(
                    lambda percent, stage, **kwargs: progress.append((percent, stage))
                )

            configure.assert_called_once_with(media_root)
            install_chromium.assert_called_once_with(bin_dir / "ms-playwright", unittest.mock.ANY)
            self.assertEqual(progress[-1], (100, "Ready"))


class LocalVideoApiTests(unittest.TestCase):
    def test_dependency_progress_endpoint_is_ready_in_source_mode(self):
        import app as app_module

        with patch.object(app_module, "IS_FROZEN", False):
            response = app_module.app.test_client().get("/api/dependencies/progress")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ready")

    def test_application_status_includes_source_build_id(self):
        import app as app_module

        response = app_module.app.test_client().get("/api/status")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["build_id"], app_module._APP_BUILD_ID)

    def test_dependency_progress_endpoint_reports_portable_bootstrap(self):
        import app as app_module

        expected = {
            "status": "loading",
            "percent": 72,
            "stage": "Updating Chromium",
            "error": None,
        }
        with patch.object(app_module, "IS_FROZEN", True), patch(
            "bootstrap.dependency_progress", return_value=expected
        ):
            response = app_module.app.test_client().get("/api/dependencies/progress")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), expected)

    def test_download_folder_status_never_forces_a_choice(self):
        import app as app_module

        missing_root = Path("Z:/disconnected-media")
        with patch.object(app_module, "get_download_path", return_value=missing_root), patch.object(
            app_module, "has_configured_download_path", return_value=True
        ):
            with patch.object(app_module, "IS_FROZEN", False):
                source_status = app_module.app.test_client().get("/api/download-folder").get_json()
            with patch.object(app_module, "IS_FROZEN", True):
                portable_status = app_module.app.test_client().get("/api/download-folder").get_json()

        self.assertFalse(source_status["required"])
        self.assertFalse(portable_status["required"])

    def test_menu_shows_dependency_loader_only_in_frozen_mode(self):
        import app as app_module

        client = app_module.app.test_client()
        source_response = client.get("/")
        with patch.object(app_module, "IS_FROZEN", True):
            portable_response = client.get("/")

        self.assertNotIn(b"dependencyLoading", source_response.data)
        self.assertIn(b"dependencyLoading", portable_response.data)
        self.assertIn(b"dependencies-loading.js", portable_response.data)

    def test_menu_and_video_pages_render_portable_folder_controls(self):
        import app as app_module

        client = app_module.app.test_client()
        menu_response = client.get("/")
        video_response = client.get("/video")

        self.assertEqual(menu_response.status_code, 200)
        self.assertIn(b"downloadFolderDialog", menu_response.data)
        self.assertEqual(video_response.status_code, 200)
        self.assertIn(b"chooseDownloadFolder", video_response.data)
        self.assertIn(b"chooseDownloadedVideo", video_response.data)

        # Music is the DowFlow Music (Liner) desktop app now: the old web page
        # is gone and a scoped Music backend only serves its API.
        for route in ("/music", "/music/stream", "/music/explore", "/music/liked"):
            with self.subTest(route=route):
                self.assertEqual(client.get(route).status_code, 404)
        self.assertTrue(
            app_module._scope_allows_path("music", "/api/music/stream/favorites")
        )
        self.assertFalse(app_module._scope_allows_path("music", "/video"))

        category_response = client.get("/film")
        self.assertEqual(category_response.status_code, 200)

    def test_scoped_app_hides_pages_outside_its_build(self):
        import app as app_module

        with patch.object(app_module, "IS_FROZEN", True), patch.object(
            app_module, "APP_SCOPE", "video"
        ):
            client = app_module.app.test_client()
            self.assertEqual(client.get("/video").status_code, 200)
            self.assertEqual(client.get("/music").status_code, 404)

    def test_scoped_app_redirects_root_to_its_only_page(self):
        import app as app_module

        with patch.object(app_module, "IS_FROZEN", True), patch.object(
            app_module, "APP_SCOPE", "video"
        ):
            response = app_module.app.test_client().get("/", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/video")

    def test_export_name_is_safe_for_windows(self):
        self.assertEqual(build_export.sanitize_exe_name("My DowFlow.exe"), "My DowFlow")
        with self.assertRaises(ValueError):
            build_export.sanitize_exe_name("CON.exe")

    def test_build_helper_passes_scope_and_removes_temporary_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            # The Music edition packages Liner instead of running PyInstaller,
            # so this test keeps a scoped backend edition (Films).
            expected = (
                root / "build" / "out" / "Films Edition" / "Films Edition.exe"
            )
            progress_events = []

            class FakeProcess:
                stdout = iter(
                    [
                        "INFO: Checking Analysis\n",
                        "INFO: Building Analysis\n",
                        "INFO: Processing standard module hook\n",
                        "INFO: Building PYZ\n",
                        "INFO: Building PKG\n",
                        "INFO: Building EXE\n",
                        "INFO: Build completed successfully.\n",
                    ]
                )

                def __init__(self, command, **kwargs):
                    self.command = command
                    self.kwargs = kwargs

                def wait(self):
                    self.assert_build_arguments()
                    expected.parent.mkdir(parents=True, exist_ok=True)
                    expected.write_bytes(b"exe")
                    return 0

                def assert_build_arguments(self):
                    self_unit.assertEqual(self.kwargs["env"]["DOWFLOW_BUILD_SCOPE"], "film")
                    self_unit.assertEqual(self.kwargs["env"]["DOWFLOW_BUILD_NAME"], "Films Edition")
                    self_unit.assertIn(str(root / "build" / "dowflow.spec"), self.command)
                    self_unit.assertIn("--distpath", self.command)
                    self_unit.assertNotIn("--clean", self.command)
                    profile = root / "build" / "app_scope.json"
                    self_unit.assertEqual(json.loads(profile.read_text(encoding="utf-8"))["scope"], "film")

            self_unit = self

            with patch.object(build_export.subprocess, "Popen", FakeProcess):
                result = build_export.build_executable(
                    "film",
                    "Films Edition.exe",
                    root,
                    progress_callback=progress_events.append,
                )

            self.assertEqual(result, expected.resolve())
            self.assertFalse((root / "build" / "app_scope.json").exists())
            self.assertEqual(progress_events[0]["percent"], 1)
            self.assertEqual(progress_events[-1]["percent"], 100)
            self.assertTrue(any(event["stage"] == "Compressing Python modules" for event in progress_events))

    def test_installer_compresses_each_edition_into_its_own_setup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            edition = build_export.EDITIONS["video"]
            source = root / "build" / "out" / edition["name"]
            source.mkdir(parents=True)
            (source / f"{edition['name']}.exe").write_bytes(b"exe")
            tools = root / "build" / "tools"
            tools.mkdir(parents=True)
            (tools / ".tools.ready").write_text("{}", encoding="utf-8")
            (root / "static").mkdir()
            (root / "static" / "dowflow.ico").write_bytes(b"icon")
            setup = root / "build-output" / f"{edition['setup']}.exe"
            captured = {}

            class FakeCompleted:
                returncode = 0
                stdout = "ok"
                stderr = ""

            def fake_run(command, **kwargs):
                captured["command"] = command
                output_dir = next(
                    item.split("=", 1)[1]
                    for item in command
                    if item.startswith("/DOutputDir=")
                )
                staged = Path(output_dir) / f"{edition['setup']}.exe"
                staged.parent.mkdir(parents=True, exist_ok=True)
                staged.write_bytes(b"setup")
                return FakeCompleted()

            with patch.object(build_export, "_find_iscc", return_value="iscc"), patch.object(
                build_export.subprocess, "run", side_effect=fake_run
            ):
                result = build_export.build_installer("video", root, output_dir=root / "build-output")

            self.assertEqual(result, setup)
            command = captured["command"]
            self.assertIn("/DDestDir=submenus\\video", command)
            self.assertIn("/DOutputBase=DowFlow-Video-Setup", command)
            self.assertIn(str(root / "build" / "installer.iss"), command)
            self.assertTrue(
                any(item.startswith("/DSourceDir=") and edition["name"] in item for item in command)
            )

    def test_installer_reports_live_compression_progress(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            edition = build_export.EDITIONS["music"]
            # The Music edition installs the packaged Liner app, so the setup is
            # built from its win-unpacked folder and ships no media tools.
            source = build_export.liner_app_dir(root)
            source.mkdir(parents=True)
            (source / edition["app_exe"]).write_bytes(b"x" * (6 * 1024 * 1024))
            captured = {}
            tools = root / "build" / "tools"
            tools.mkdir(parents=True)
            (tools / ".tools.ready").write_text("{}", encoding="utf-8")
            (root / "static").mkdir()
            (root / "static" / "dowflow.ico").write_bytes(b"icon")
            events = []

            class FakeCompleted:
                returncode = 0
                stdout = "ok"
                stderr = ""

            def fake_run(command, **kwargs):
                captured["command"] = command
                output_dir = next(
                    item.split("=", 1)[1]
                    for item in command
                    if item.startswith("/DOutputDir=")
                )
                staged = Path(output_dir) / f"{edition['setup']}.exe"
                staged.parent.mkdir(parents=True, exist_ok=True)
                for _ in range(5):
                    with staged.open("ab") as handle:
                        handle.write(b"setup" * (64 * 1024))
                    time.sleep(0.3)
                return FakeCompleted()

            with patch.object(build_export, "_find_iscc", return_value="iscc"), patch.object(
                build_export.subprocess, "run", side_effect=fake_run
            ):
                build_export.build_installer(
                    "music",
                    root,
                    output_dir=root / "build-output",
                    progress_callback=lambda percent, stage, eta: events.append(
                        (percent, stage, eta)
                    ),
                )

            self.assertTrue(events)
            self.assertIn("/DAppExe=dowflow-music.exe", captured["command"])
            self.assertTrue(
                any(
                    item.startswith("/DSourceDir=") and "win-unpacked" in item
                    for item in captured["command"]
                )
            )
            self.assertTrue(all(percent >= 90 for percent, _stage, _eta in events))
            self.assertTrue(any("MB/s" in stage for _percent, stage, _eta in events))
            self.assertTrue(any("MB" in stage and "/" in stage for _percent, stage, _eta in events))
            self.assertTrue(any(eta is not None for _percent, _stage, eta in events))
            stored = json.loads(
                (root / "build" / ".export_history.json").read_text(encoding="utf-8")
            )
            self.assertIn("music", stored["installer"])

    def test_folder_picker_route_saves_the_selected_path(self):
        import app as app_module

        with tempfile.TemporaryDirectory() as temporary:
            selected = Path(temporary) / "media"
            result = SimpleNamespace(returncode=0, stdout=str(selected), stderr="")
            with patch.object(app_module, "get_download_path", return_value=None), patch.object(
                app_module, "select_download_folder", return_value=str(selected)
            ) as picker, patch.object(
                app_module, "set_download_path", return_value=selected
            ) as save_path:
                response = app_module.app.test_client().post("/api/download-folder/select")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json(), {"success": True, "path": str(selected)})
            save_path.assert_called_once_with(str(selected))
            picker.assert_called_once_with(str(Path.home()))

    def test_local_video_endpoint_lists_media_relative_to_selected_folder(self):
        import app as app_module

        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            video = folder / "clip.mp4"
            video.write_bytes(b"video")
            nested_video = folder / "vacances" / "private.mp4"
            nested_video.parent.mkdir()
            nested_video.write_bytes(b"ignore")
            (folder / "notes.txt").write_text("ignore", encoding="utf-8")

            with patch.object(app_module, "_download_folder", return_value=folder):
                response = app_module.app.test_client().get("/api/local-videos")

            payload = response.get_json()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(payload["items"]), 1)
            self.assertEqual(payload["items"][0]["relative_path"], "clip.mp4")
            self.assertEqual(payload["items"][0]["file_url"], "/media/clip.mp4")

    def test_local_video_endpoint_does_not_create_a_missing_root(self):
        import app as app_module

        with tempfile.TemporaryDirectory() as temporary:
            missing_root = Path(temporary) / "not-created"
            with patch.object(app_module, "get_download_path", return_value=missing_root):
                response = app_module.app.test_client().get("/api/local-videos")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["items"], [])
            self.assertFalse(missing_root.exists())


if __name__ == "__main__":
    unittest.main()
