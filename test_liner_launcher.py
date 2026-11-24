"""Tests for the DowFlow Music (Liner) launcher lookup in an installed build."""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import app
import launcher


class LinerLauncherTests(unittest.TestCase):
    def _spec_for(self, executable: Path):
        with (
            mock.patch.object(app, "IS_FROZEN", True),
            mock.patch.object(app.sys, "executable", str(executable)),
        ):
            return app._liner_launcher_spec()

    def test_menu_edition_finds_music_installed_beside_it(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "DowFlow"
            menu = root / "menu"
            music = root / "submenus" / "music"
            menu.mkdir(parents=True)
            music.mkdir(parents=True)
            executable = menu / "DowFlow.exe"
            executable.write_text("exe", encoding="utf-8")
            liner = music / "dowflow-music.exe"
            liner.write_text("exe", encoding="utf-8")

            spec = self._spec_for(executable)

            self.assertIsNotNone(spec, "the menu must find the installed Music edition")
            self.assertEqual(spec[0], [str(liner.resolve())])
            self.assertEqual(spec[1], music.resolve())

    def test_music_edition_finds_its_own_executable(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            music = Path(folder) / "DowFlow" / "submenus" / "music"
            music.mkdir(parents=True)
            executable = music / "dowflow-music.exe"
            executable.write_text("exe", encoding="utf-8")

            spec = self._spec_for(executable)

            self.assertIsNotNone(spec)
            self.assertEqual(spec[0], [str(executable.resolve())])

    def test_no_music_edition_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            menu = Path(folder) / "DowFlow" / "menu"
            menu.mkdir(parents=True)
            executable = menu / "DowFlow.exe"
            executable.write_text("exe", encoding="utf-8")

            self.assertIsNone(self._spec_for(executable))


    def test_source_mode_prefers_the_fresh_build(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "src"
            liner = source / "desktop" / "liner"
            (liner / "release" / "win-unpacked").mkdir(parents=True)
            (liner / "release-build" / "win-unpacked").mkdir(parents=True)
            (liner / "package.json").write_text("{}", encoding="utf-8")
            (liner / "release" / "win-unpacked" / "dowflow-music.exe").write_text(
                "exe", encoding="utf-8"
            )
            fresh = liner / "release-build" / "win-unpacked" / "dowflow-music.exe"
            fresh.write_text("exe", encoding="utf-8")

            with (
                mock.patch.object(app, "IS_FROZEN", False),
                mock.patch.object(app, "SOURCE_DIR", source),
            ):
                spec = app._liner_launcher_spec()

            self.assertIsNotNone(spec)
            self.assertEqual(spec[0], [str(fresh)])

class MusicBuildFreshnessTests(unittest.TestCase):
    """start.bat music must rebuild the packaged app when sources changed."""

    def _tree(self, folder: str, source_age: float, build_age: float) -> Path:
        root = Path(folder)
        liner = root / "desktop" / "liner"
        (liner / "src").mkdir(parents=True)
        source = liner / "src" / "App.tsx"
        source.write_text("source", encoding="utf-8")
        package = liner / "package.json"
        package.write_text("{}", encoding="utf-8")
        executable = liner / "release-build" / "win-unpacked" / "dowflow-music.exe"
        executable.parent.mkdir(parents=True)
        executable.write_text("exe", encoding="utf-8")
        now = time.time()
        # package.json counts as a source, so it gets the source age too: left at
        # "now", it made the comparison hinge on a one-millisecond margin that a
        # coarser filesystem clock can invert.
        aged = ((source, source_age), (package, source_age), (executable, build_age))
        for path, age in aged:
            os.utime(path, (now - age, now - age))
        return root

    def test_missing_packaged_app_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "desktop" / "liner").mkdir(parents=True)
            self.assertFalse(launcher.liner_build_is_current(root))

    def test_newer_source_triggers_a_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = self._tree(folder, source_age=0, build_age=600)
            self.assertFalse(launcher.liner_build_is_current(root))

    def test_fresh_build_is_reused(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = self._tree(folder, source_age=600, build_age=0)
            self.assertTrue(launcher.liner_build_is_current(root))


if __name__ == "__main__":
    unittest.main()
