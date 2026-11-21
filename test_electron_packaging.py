import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
ELECTRON_ROOT = PROJECT_ROOT / "desktop" / "electron"


class ElectronPackagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.package = json.loads((ELECTRON_ROOT / "package.json").read_text(encoding="utf-8"))

    def test_builder_targets_unsigned_per_user_nsis_without_update_feed(self):
        build = self.package["build"]
        self.assertEqual(build["appId"], "DowFlow.DowFlow")
        self.assertEqual(build["productName"], "DowFlow")
        self.assertEqual(build["directories"]["output"], "release")
        self.assertEqual(build["win"]["target"], [{"target": "nsis", "arch": ["x64"]}])
        self.assertEqual(build["nsis"]["perMachine"], False)
        self.assertEqual(build["nsis"]["deleteAppDataOnUninstall"], False)
        self.assertNotIn("publish", build)
        self.assertEqual(
            next(item for item in build["extraResources"] if item["to"] == "backend")["from"],
            "../../build/out/DowFlow",
        )
        self.assertEqual(
            next(item for item in build["extraResources"] if item["to"] == "liner")["from"],
            "../liner/release/win-unpacked",
        )
        self.assertIn("../../static/dowflow.ico", build["win"]["icon"])

    def test_windows_script_builds_renderer_backend_then_installer(self):
        script = (ELECTRON_ROOT / "build-win.ps1").read_text(encoding="utf-8")
        self.assertIn('"pnpm" @("check")', script)
        self.assertIn('"python" @("-m", "build_export", "all", "DowFlow")', script)
        self.assertIn('"pnpm" @("native:build")', script)
        self.assertIn('"pnpm" @("exec", "electron-builder", "--win", "--dir", "--x64")', script)
        self.assertIn('release/win-unpacked/dowflow-music.exe', script)
        self.assertIn('resources/liner/dowflow-music.exe', script)
        self.assertIn('"pnpm" @("exec", "electron-builder", "--win", "nsis", "--x64")', script)
        self.assertIn('build/out/DowFlow/DowFlow.exe', script)
        self.assertLess(script.index('"pnpm" @("check")'), script.index('"python" @("-m", "build_export", "all", "DowFlow")'))
        self.assertLess(script.index('"python" @("-m", "build_export", "all", "DowFlow")'), script.index('"pnpm" @("exec", "electron-builder", "--win", "nsis", "--x64")'))
        self.assertIn('$env:DOWFLOW_ELECTRON_BUILD = "1"', script)

    def test_music_launcher_is_restricted_and_has_a_browser_fallback(self):
        main = (ELECTRON_ROOT / "main.cjs").read_text(encoding="utf-8")
        preload = (ELECTRON_ROOT / "preload.cjs").read_text(encoding="utf-8")
        template = (PROJECT_ROOT / "templates" / "menu.html").read_text(encoding="utf-8")
        self.assertIn('ipcMain.handle("dowflow:music:open"', main)
        self.assertIn('event.sender !== mainWindow.webContents', main)
        self.assertIn("musicLauncher.closeAll()", main)
        self.assertIn('open: () => ipcRenderer.invoke("dowflow:music:open")', preload)
        self.assertIn('href="/music" data-menu-id="music"', template)
        self.assertIn("window.dowflow?.music?.open", template)
        self.assertIn("window.location.assign(musicEntry.href)", template)

    def test_electron_build_does_not_embed_personal_portable_seeds(self):
        spec = (PROJECT_ROOT / "build" / "dowflow.spec").read_text(encoding="utf-8")
        self.assertIn('os.environ.get("DOWFLOW_EMBED_PORTABLE_DATA") == "1"', spec)
        self.assertNotIn("DOWFLOW_ELECTRON_BUILD", spec)
        for seed in ("dowflow.db", "dowflow.db-wal", "config.json", "youtube.com_cookies.txt"):
            self.assertIn(seed, spec)

    def test_backend_paths_stay_in_electron_user_data_after_media_folder_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            user_data = root / "DowFlow-user-data"
            media_root = root / "chosen-media"
            media_root.mkdir()
            env = os.environ.copy()
            env.update(
                {
                    "DOWFLOW_DESKTOP_SHELL": "electron",
                    "DOWFLOW_DATA_ROOT": str(user_data),
                    "DOWFLOW_TEST_MEDIA_ROOT": str(media_root),
                    "PYTHONPATH": str(PROJECT_ROOT),
                }
            )
            code = """
import json, os
from pathlib import Path
import config, database, logger
media_root = Path(os.environ['DOWFLOW_TEST_MEDIA_ROOT'])
config.set_download_path(media_root)
print(json.dumps({
    'base': str(config.BASE_DIR),
    'config': str(config.CONFIG_FILE),
    'database': str(database.DB_PATH),
    'logs': str(logger.LOG_DIR),
    'download': str(config.get_download_path()),
    'tools': str(config.get_bin_folder()),
}))
"""
            completed = subprocess.run(
                [sys.executable, "-c", code],
                cwd=PROJECT_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            result = json.loads(completed.stdout.strip())

            self.assertEqual(Path(result["base"]), user_data.resolve())
            self.assertEqual(Path(result["config"]), user_data.resolve() / "config.json")
            self.assertEqual(Path(result["database"]), user_data.resolve() / "dowflow.db")
            self.assertEqual(Path(result["logs"]), user_data.resolve() / "logs")
            self.assertEqual(Path(result["download"]), media_root.resolve())
            self.assertEqual(Path(result["tools"]), user_data.resolve() / "bin")
            self.assertTrue((user_data / "config.json").is_file())
            self.assertFalse((media_root / "config.json").exists())

    def test_electron_backend_receives_user_data_path_and_packaged_icon_path(self):
        main = (ELECTRON_ROOT / "main.cjs").read_text(encoding="utf-8")
        self.assertIn('DOWFLOW_DESKTOP_SHELL: "electron"', main)
        self.assertIn('DOWFLOW_DATA_ROOT: app.getPath("userData")', main)
        self.assertIn('path.join(process.resourcesPath, "static", "dowflow.ico")', main)
        self.assertIn("app.isPackaged ? 120_000 : 20_000", main)

    def test_windows_validation_is_manual_pinned_and_does_not_upload_installer(self):
        workflow = (PROJECT_ROOT / ".github" / "workflows" / "build-electron-windows.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("runs-on: windows-latest", workflow)
        self.assertIn("pnpm --dir desktop/electron package:win", workflow)
        self.assertIn("python -m unittest discover -v", workflow)
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertNotIn("upload-artifact", workflow)
        self.assertRegex(workflow, r"actions/checkout@[0-9a-f]{40}")
        self.assertRegex(workflow, r"actions/setup-python@[0-9a-f]{40}")
        self.assertRegex(workflow, r"actions/setup-node@[0-9a-f]{40}")


if __name__ == "__main__":
    unittest.main()
