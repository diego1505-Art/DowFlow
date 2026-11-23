"""Tests for the blank (release) build path of build_export.

PyInstaller and Inno Setup are stubbed: these tests only assert how a blank
build prepares its folders, its command line and its output directory.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import build_export


class BlankBuildTests(unittest.TestCase):
    def test_blank_build_cleans_stale_output_and_keeps_the_setup_in_downloads(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            stale = root / "build" / "out" / "DowFlow-Films" / "leftover.txt"
            stale.parent.mkdir(parents=True)
            stale.write_text("data from an earlier build", encoding="utf-8")
            seen: dict[str, list[str]] = {}

            class FakeProcess:
                stdout = iter(())

                def __init__(self, command, **kwargs) -> None:
                    seen["command"] = list(command)
                    output = root / "build" / "out" / "DowFlow-Films"
                    output.mkdir(parents=True, exist_ok=True)
                    (output / "DowFlow-Films.exe").write_text("exe", encoding="utf-8")

                def wait(self) -> int:
                    return 0

            with (
                mock.patch.object(build_export.subprocess, "Popen", FakeProcess),
                mock.patch.object(build_export, "prepare_tools", return_value=None),
                mock.patch.object(build_export, "build_installer") as installer,
            ):
                installer.return_value = (
                    root / "build" / "release" / "DowFlow-Films-Setup.exe"
                )
                build_export.build_executable(
                    "film",
                    project_root=root,
                    installer=True,
                    blank=True,
                )

            self.assertIn("--clean", seen["command"])
            self.assertFalse(
                stale.exists(), "a blank build must not reuse the previous output"
            )
            self.assertIsNone(
                installer.call_args[0][2],
                "a blank setup must land in the default Downloads folder",
            )

    def test_every_setup_lands_in_downloads(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder)
            downloads = profile / "Downloads"
            downloads.mkdir()
            with mock.patch.dict(
                build_export.os.environ, {"USERPROFILE": str(profile)}
            ):
                self.assertEqual(build_export.default_output_dir(), downloads)


class MusicBundlingTests(unittest.TestCase):
    """The whole-menu setup has to bring the Music app with it."""

    def _installer_kwargs(self, scope: str, name: str) -> dict:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            # The Music backend Liner embeds, so the build never recurses.
            backend = root / "build" / "out" / "DowFlow-Music" / "DowFlow-Music.exe"
            backend.parent.mkdir(parents=True)
            backend.write_text("exe", encoding="utf-8")

            class FakeProcess:
                stdout = iter(())

                def __init__(self, command, **kwargs) -> None:
                    output = root / "build" / "out" / name
                    output.mkdir(parents=True, exist_ok=True)
                    (output / f"{name}.exe").write_text("exe", encoding="utf-8")

                def wait(self) -> int:
                    return 0

            with (
                mock.patch.object(build_export.subprocess, "Popen", FakeProcess),
                mock.patch.object(build_export, "prepare_tools", return_value=None),
                mock.patch.object(build_export, "build_liner_app") as liner,
                mock.patch.object(
                    build_export, "liner_app_dir", return_value=root / "liner"
                ),
                mock.patch.object(build_export, "build_installer") as installer,
            ):
                installer.return_value = root / "setup.exe"
                build_export.build_executable(
                    scope, name, project_root=root, installer=True, blank=True
                )
            self.assertEqual(liner.call_count, 1 if scope in {"all", "music"} else 0)
            return installer.call_args.kwargs

    def test_whole_menu_setup_installs_music(self) -> None:
        kwargs = self._installer_kwargs("all", "DowFlow")
        self.assertIsNotNone(kwargs.get("liner_dir"))

    def test_video_setup_stays_without_music(self) -> None:
        kwargs = self._installer_kwargs("video", "DowFlow-Video")
        self.assertIsNone(kwargs.get("liner_dir"))

    def test_installer_template_copies_music_only_when_asked(self) -> None:
        text = (Path(__file__).parent / "build" / "installer.iss").read_text(
            encoding="utf-8"
        )
        self.assertIn("#ifdef LinerDir", text)
        self.assertIn('DestDir: "{app}\\submenus\\music"', text)


if __name__ == "__main__":
    unittest.main()
