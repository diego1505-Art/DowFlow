"""Tests for build_export: setup location, user-data stripping, Music bundling.

PyInstaller and Inno Setup are stubbed: these tests only assert how a build
prepares its folders, its command line and its output directory.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import build_export


class SetupLocationTests(unittest.TestCase):
    def test_every_setup_lands_in_downloads(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            profile = Path(folder)
            downloads = profile / "Downloads"
            downloads.mkdir()
            with mock.patch.dict(
                build_export.os.environ, {"USERPROFILE": str(profile)}
            ):
                self.assertEqual(build_export.default_output_dir(), downloads)


class UserDataIsolationTests(unittest.TestCase):
    """No setup may carry the database, config or logs of this machine."""

    def test_strips_the_runtime_files_of_an_app_folder(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            edition = Path(folder) / "DowFlow"
            edition.mkdir()
            (edition / "DowFlow.exe").write_text("exe", encoding="utf-8")
            (edition / "_internal").mkdir()
            (edition / "_internal" / "portable_data").mkdir()
            files = ("dowflow.db", "dowflow.db-wal", "config.json", "youtube.com_cookies.txt")
            folders = ("logs", "bin", "browser_profile", "portable_data")
            for name in files:
                (edition / name).write_text("data", encoding="utf-8")
            for name in folders:
                (edition / name).mkdir()
                (edition / name / "inside.txt").write_text("data", encoding="utf-8")

            removed = build_export.strip_user_data(edition)

            self.assertEqual(sorted(removed), sorted((*files, *folders)))
            self.assertTrue((edition / "DowFlow.exe").is_file())
            self.assertTrue((edition / "_internal" / "portable_data").is_dir())
            for name in (*files, *folders):
                self.assertFalse((edition / name).exists(), name)

    def test_a_setup_built_from_a_used_folder_stays_clean(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / "build" / "out" / "DowFlow-Video"
            output.mkdir(parents=True)
            (output / "dowflow.db").write_text("db", encoding="utf-8")
            (output / "logs").mkdir()

            class FakeProcess:
                stdout = iter(())

                def __init__(self, command, **kwargs) -> None:
                    (output / "DowFlow-Video.exe").write_text(
                        "exe", encoding="utf-8"
                    )

                def wait(self) -> int:
                    return 0

            with (
                mock.patch.object(build_export.subprocess, "Popen", FakeProcess),
                mock.patch.object(build_export, "prepare_tools", return_value=None),
                mock.patch.object(build_export, "build_installer") as installer,
            ):
                installer.return_value = root / "setup.exe"
                build_export.build_executable(
                    "video",
                    "DowFlow-Video",
                    project_root=root,
                    installer=True,
                )

            self.assertFalse((output / "dowflow.db").exists())
            self.assertFalse((output / "logs").exists())

    def test_a_music_backend_is_reused_when_one_exists(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            backend = root / "build" / "out" / "DowFlow-Music" / "DowFlow-Music.exe"

            self.assertFalse(build_export.music_backend_is_reusable(root))
            backend.parent.mkdir(parents=True)
            backend.write_text("exe", encoding="utf-8")
            self.assertTrue(build_export.music_backend_is_reusable(root))


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
                    # PyInstaller is faked for whichever edition runs, which can
                    # also be the Music backend a whole-menu build rebuilds.
                    built = kwargs["env"]["DOWFLOW_BUILD_NAME"]
                    output = root / "build" / "out" / built
                    output.mkdir(parents=True, exist_ok=True)
                    (output / f"{built}.exe").write_text("exe", encoding="utf-8")

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
                    scope, name, project_root=root, installer=True
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
        music_block = text.split("#ifdef LinerDir", 1)[1].split("#endif", 1)[0]
        self.assertIn("submenus", music_block)
        self.assertIn("{#LinerDir}", music_block)


if __name__ == "__main__":
    unittest.main()
