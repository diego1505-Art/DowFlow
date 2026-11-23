"""Tests for the DowFlow Music updater artifacts the build writes."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import build_export


def _manifest(folder: Path, payload: dict) -> Path:
    (folder / "package.json").write_text(json.dumps(payload), encoding="utf-8")
    return folder


class LinerBuildVersionTests(unittest.TestCase):
    def test_the_build_stamps_its_date_so_updates_are_newer(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = _manifest(Path(folder), {"version": "0.2.12"})
            with mock.patch.object(
                build_export.time, "strftime", return_value="202611232145"
            ):
                version = build_export.liner_build_version(root)
            self.assertEqual(version, "0.2.202611232145")

            with mock.patch.object(
                build_export.time, "strftime", return_value="202611232146"
            ):
                self.assertNotEqual(build_export.liner_build_version(root), version)

    def test_a_missing_manifest_still_gives_a_version(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            version = build_export.liner_build_version(Path(folder))
        self.assertTrue(version.startswith("0.0."))


class LinerUpdateConfigTests(unittest.TestCase):
    def _root(self, folder: Path) -> Path:
        return _manifest(
            folder,
            {
                "version": "0.2.12",
                "build": {
                    "publish": [
                        {
                            "provider": "github",
                            "owner": "diego1505-Art",
                            "repo": "DowFlow",
                        }
                    ]
                },
            },
        )

    def test_writes_the_update_target_when_the_build_produced_none(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = self._root(Path(folder))
            app_dir = root / "release" / "win-unpacked"
            (app_dir / "resources").mkdir(parents=True)
            config = build_export._write_liner_update_config(root, app_dir)

            self.assertIsNotNone(config)
            text = (app_dir / "resources" / "app-update.yml").read_text(
                encoding="utf-8"
            )
            self.assertIn("provider: github", text)
            self.assertIn("repo: DowFlow", text)

    def test_keeps_the_file_the_build_wrote(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = self._root(Path(folder))
            app_dir = root / "release" / "win-unpacked"
            resources = app_dir / "resources"
            resources.mkdir(parents=True)
            written = resources / "app-update.yml"
            written.write_text("provider: github\nowner: someone\n", encoding="utf-8")

            build_export._write_liner_update_config(root, app_dir)

            self.assertEqual(
                written.read_text(encoding="utf-8"),
                "provider: github\nowner: someone\n",
            )

    def test_a_non_github_target_is_left_alone(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = _manifest(
                Path(folder),
                {"build": {"publish": [{"provider": "s3", "bucket": "x"}]}},
            )
            app_dir = root / "release" / "win-unpacked"
            (app_dir / "resources").mkdir(parents=True)

            self.assertIsNone(build_export._write_liner_update_config(root, app_dir))
            self.assertFalse((app_dir / "resources" / "app-update.yml").exists())


if __name__ == "__main__":
    unittest.main()
