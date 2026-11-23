import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent


class MusicPackagingTests(unittest.TestCase):
    def test_music_edition_ships_liner_with_the_dowflow_backend(self):
        import build_export

        music = build_export.EDITIONS["music"]
        self.assertTrue(music["liner"])
        self.assertEqual(music["app_exe"], "dowflow-music.exe")
        backend = (PROJECT_ROOT / "desktop" / "liner" / "electron" / "dowflow-backend.ts").read_text(
            encoding="utf-8"
        )
        self.assertIn("export function startBundledDowflowBackend", backend)
        self.assertIn('path.join(process.resourcesPath, "backend", "DowFlow-Music.exe")', backend)
        self.assertIn("export function stopBundledDowflowBackend", backend)
        main = (PROJECT_ROOT / "desktop" / "liner" / "electron" / "main.ts").read_text(
            encoding="utf-8"
        )
        self.assertIn("startBundledDowflowBackend();", main)
        self.assertIn("stopBundledDowflowBackend();", main)
        package = json.loads(
            (PROJECT_ROOT / "desktop" / "liner" / "package.json").read_text(encoding="utf-8")
        )
        resource = next(
            item for item in package["build"]["extraResources"] if item["to"] == "backend"
        )
        self.assertEqual(resource["from"], "../../build/out/DowFlow-Music")

    def test_build_does_not_embed_personal_portable_seeds(self):
        spec = (PROJECT_ROOT / "build" / "dowflow.spec").read_text(encoding="utf-8")
        self.assertIn('os.environ.get("DOWFLOW_EMBED_PORTABLE_DATA") == "1"', spec)
        self.assertNotIn("DOWFLOW_ELECTRON_BUILD", spec)
        for seed in ("dowflow.db", "dowflow.db-wal", "config.json", "youtube.com_cookies.txt"):
            self.assertIn(seed, spec)

    def test_desktop_shell_paths_stay_in_user_data_after_media_folder_selection(self):
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


if __name__ == "__main__":
    unittest.main()
