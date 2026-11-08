import io
import json
import os
import tempfile
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
            config, "_saved_download_path", return_value=media_root
        ):
            self.assertEqual(config.get_bin_folder(), media_root / "bin")

        with patch.object(config, "IS_FROZEN", False):
            self.assertEqual(config.get_bin_folder(), config.BIN_FOLDER)

    def test_first_frozen_launch_prompts_and_saves_the_media_root(self):
        import folder_picker
        import startup

        selected = Path("C:/media-root")
        with patch.object(startup.sys, "frozen", True, create=True), patch.object(
            config, "get_download_path", return_value=None
        ), patch.object(config, "set_download_path") as save_path, patch.object(
            folder_picker, "select_download_folder", return_value=str(selected)
        ) as picker:
            self.assertTrue(startup._ensure_portable_download_folder())

        picker.assert_called_once_with(None)
        save_path.assert_called_once_with(str(selected))

    def test_missing_saved_media_root_prompts_for_a_replacement(self):
        import folder_picker
        import startup

        missing_root = Path("Z:/disconnected-media")
        replacement = Path("C:/replacement-media")
        with patch.object(startup.sys, "frozen", True, create=True), patch.object(
            config, "get_download_path", return_value=missing_root
        ), patch.object(config, "set_download_path") as save_path, patch.object(
            folder_picker, "select_download_folder", return_value=str(replacement)
        ) as picker, patch.object(Path, "is_dir", return_value=False):
            self.assertTrue(startup._ensure_portable_download_folder())

        picker.assert_called_once_with(None)
        save_path.assert_called_once_with(str(replacement))

    def test_frozen_mode_requires_a_saved_download_folder(self):
        with patch.object(config, "IS_FROZEN", True), patch.object(
            config, "_saved_download_path", return_value=None
        ):
            self.assertIsNone(config.get_download_path(required=False))
            with self.assertRaises(config.DownloadPathNotConfigured):
                config.get_download_path()

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

            with patch.object(config, "IS_FROZEN", True), patch.object(
                config, "BASE_DIR", app_dir
            ), patch.object(config, "CONFIG_FILE", config_file):
                self.assertEqual(config.set_download_path(selected), selected.resolve())
                self.assertEqual(config.get_download_path(), selected.resolve())

            self.assertEqual(
                json.loads(config_file.read_text(encoding="utf-8"))["download_path"],
                str(selected.resolve()),
            )
            self.assertFalse((selected / "music").exists())

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
                    str(media_root / "bin" / "ms-playwright"),
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
            (bin_dir / "aria2c.exe").write_bytes(b"aria2")
            progress = []

            with patch.object(bootstrap, "get_download_path", return_value=media_root), patch.object(
                bootstrap, "get_bin_folder", return_value=bin_dir
            ), patch.object(bootstrap, "configure_runtime_paths", return_value=bin_dir) as configure, patch.object(
                bootstrap, "_read_url", return_value=("a" * 64).encode("ascii")
            ), patch.object(bootstrap, "_aria2_is_current", return_value=True), patch.object(
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

    def test_download_folder_status_only_requires_a_path_in_frozen_mode(self):
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
        self.assertTrue(portable_status["required"])

    def test_menu_shows_dependency_loader_only_in_frozen_mode(self):
        import app as app_module

        client = app_module.app.test_client()
        source_response = client.get("/")
        with patch.object(app_module, "IS_FROZEN", True):
            portable_response = client.get("/")

        self.assertNotIn(b"dependencyLoading", source_response.data)
        self.assertIn(b"dependencyLoading", portable_response.data)
        self.assertIn(b"dependencies-loading.js", portable_response.data)

    def test_export_job_installs_build_requirements_when_pyinstaller_is_missing(self):
        import app as app_module

        class FakeInstallProcess:
            commands = []

            def __init__(self, command, **kwargs):
                self.command = command
                self.commands.append(command)
                if command[1:3] == ["-m", "pip"]:
                    self.stdout = iter(
                        ["Collecting pyinstaller\n", "Successfully installed pyinstaller\n"]
                    )
                else:
                    executable = root / "dist" / "DowFlow-Video.exe"
                    executable.parent.mkdir(parents=True, exist_ok=True)
                    executable.write_bytes(b"exe")
                    self.stdout = iter(
                        [json.dumps({"type": "progress", "percent": 55, "stage": "Compressing Python modules"}) + "\n"]
                    )

            def wait(self):
                return 0

        job_id = "install-test"
        original_job = app_module._EXPORT_JOBS.get(job_id)
        app_module._EXPORT_JOBS[job_id] = {"status": "running"}
        try:
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                requirements_file = root / "requirements-build.txt"
                requirements_file.write_text("pyinstaller>=6\n", encoding="utf-8")
                find_spec = [None, object()]
                with patch.object(app_module, "BASE_DIR", root), patch.object(
                    app_module.importlib.util,
                    "find_spec",
                    side_effect=lambda name: find_spec.pop(0),
                ), patch.object(app_module.subprocess, "Popen", FakeInstallProcess):
                    app_module._run_export_job(
                        job_id,
                        "video",
                        "DowFlow-Video",
                        root / "dist" / "DowFlow-Video.exe",
                    )

                install_command = FakeInstallProcess.commands[0]
                build_command = FakeInstallProcess.commands[1]
                self.assertEqual(install_command[1:4], ["-m", "pip", "install"])
                self.assertEqual(install_command[4:], ["-r", str(requirements_file)])
                self.assertEqual(build_command[1], str(root / "build_export.py"))
                self.assertEqual(app_module._EXPORT_JOBS[job_id]["status"], "success")
        finally:
            if original_job is None:
                app_module._EXPORT_JOBS.pop(job_id, None)
            else:
                app_module._EXPORT_JOBS[job_id] = original_job
            app_module._EXPORT_RUNNING = False

    def test_export_route_uses_native_name_and_reports_completed_build(self):
        import app as app_module

        class ImmediateThread:
            def __init__(self, target, args=(), **kwargs):
                self.target = target
                self.args = args

            def start(self):
                self.target(*self.args)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dist_dir = root / "dist"
            executable = dist_dir / "DowFlow-Video.exe"
            progress_event = {
                "type": "progress",
                "percent": 55,
                "stage": "Compressing Python modules",
                "elapsed_seconds": 22,
                "eta_seconds": 18,
                "eta_updated_at": 1000,
            }

            def fake_run(command, **kwargs):
                if "folder_picker.py" in command[1]:
                    return SimpleNamespace(returncode=0, stdout=str(executable), stderr="")
                raise AssertionError("The build must use Popen to stream progress.")

            class FakeProcess:
                stdout = iter([json.dumps(progress_event) + "\n"])

                def __init__(self, *args, **kwargs):
                    executable.parent.mkdir(parents=True, exist_ok=True)
                    executable.write_bytes(b"exe")

                def wait(self):
                    return 0

            with patch.object(app_module, "BASE_DIR", root), patch.object(
                app_module.importlib.util, "find_spec", return_value=object()
            ), patch.object(app_module.subprocess, "run", side_effect=fake_run), patch.object(
                app_module.subprocess, "Popen", FakeProcess
            ), patch.object(
                app_module.threading, "Thread", ImmediateThread
            ):
                response = app_module.app.test_client().post(
                    "/api/export", json={"scope": "video"}
                )
                payload = response.get_json()
                status_response = app_module.app.test_client().get(
                    f"/api/export/{payload['job_id']}"
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(payload["name"], "DowFlow-Video")
            self.assertTrue(executable.is_file())
            job = status_response.get_json()["job"]
            self.assertEqual(job["scope"], "video")
            self.assertEqual(job["status"], "success")
            self.assertEqual(job["progress"], 100)
            self.assertEqual(job["stage"], "Complete")
            self.assertEqual(job["eta_seconds"], 0)
            self.assertEqual(Path(job["path"]), executable)

    def test_menu_and_video_pages_render_portable_folder_controls(self):
        import app as app_module

        client = app_module.app.test_client()
        menu_response = client.get("/")
        video_response = client.get("/video")

        self.assertEqual(menu_response.status_code, 200)
        self.assertIn(b"downloadFolderDialog", menu_response.data)
        self.assertIn(b'data-export-scope="all"', menu_response.data)
        self.assertIn(b"data-export-percent", menu_response.data)
        self.assertIn(b"data-export-eta", menu_response.data)
        self.assertEqual(video_response.status_code, 200)
        self.assertIn(b"chooseDownloadFolder", video_response.data)
        self.assertIn(b"chooseDownloadedVideo", video_response.data)
        self.assertIn(b'data-export-scope="video"', video_response.data)

        music_response = client.get("/music/explore")
        self.assertEqual(music_response.status_code, 200)
        self.assertIn(b'data-export-scope="music"', music_response.data)

        category_response = client.get("/film")
        self.assertEqual(category_response.status_code, 200)
        self.assertIn(b'data-export-scope="film"', category_response.data)

    def test_scoped_app_hides_pages_outside_its_build(self):
        import app as app_module

        with patch.object(app_module, "IS_FROZEN", True), patch.object(
            app_module, "APP_SCOPE", "video"
        ):
            client = app_module.app.test_client()
            self.assertEqual(client.get("/video").status_code, 200)
            self.assertEqual(client.get("/music").status_code, 404)

    def test_export_name_is_safe_for_windows(self):
        self.assertEqual(build_export.sanitize_exe_name("My DowFlow.exe"), "My DowFlow")
        with self.assertRaises(ValueError):
            build_export.sanitize_exe_name("CON.exe")

    def test_build_helper_passes_scope_and_removes_temporary_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected = root / "dist" / "Music Edition.exe"
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
                    self_unit.assertEqual(self.kwargs["env"]["DOWFLOW_BUILD_SCOPE"], "music")
                    self_unit.assertEqual(self.kwargs["env"]["DOWFLOW_BUILD_NAME"], "Music Edition")
                    profile = root / "build" / "app_scope.json"
                    self_unit.assertEqual(json.loads(profile.read_text(encoding="utf-8"))["scope"], "music")

            self_unit = self

            with patch.object(build_export.subprocess, "Popen", FakeProcess):
                result = build_export.build_executable(
                    "music",
                    "Music Edition.exe",
                    root,
                    progress_callback=progress_events.append,
                )

            self.assertEqual(result, expected)
            self.assertFalse((root / "build" / "app_scope.json").exists())
            self.assertEqual(progress_events[0]["percent"], 1)
            self.assertEqual(progress_events[-1]["percent"], 100)
            self.assertTrue(any(event["stage"] == "Compressing Python modules" for event in progress_events))

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
            video = folder / "youtube" / "clip.mp4"
            video.parent.mkdir()
            video.write_bytes(b"video")
            unknown_video = folder / "vacances" / "private.mp4"
            unknown_video.parent.mkdir()
            unknown_video.write_bytes(b"ignore")
            (folder / "notes.txt").write_text("ignore", encoding="utf-8")

            with patch.object(app_module, "_download_folder", return_value=folder):
                response = app_module.app.test_client().get("/api/local-videos")

            payload = response.get_json()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(payload["items"][0]["relative_path"], "youtube/clip.mp4")
            self.assertEqual(payload["items"][0]["file_url"], "/media/youtube/clip.mp4")
            self.assertEqual(len(payload["items"]), 1)

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
