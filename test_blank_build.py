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
    def test_blank_build_cleans_stale_output_and_writes_to_release(self) -> None:
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
            output_dir = Path(installer.call_args[0][2])
            self.assertEqual(output_dir, root / "build" / "release")

    def test_blank_output_dir_stays_inside_the_build_folder(self) -> None:
        root = Path(tempfile.gettempdir()) / "dowflow-blank-check"
        self.assertEqual(build_export.blank_output_dir(root), root / "build" / "release")


if __name__ == "__main__":
    unittest.main()
