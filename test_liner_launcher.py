"""Tests for the DowFlow Music (Liner) launcher lookup in an installed build."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app


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


if __name__ == "__main__":
    unittest.main()
