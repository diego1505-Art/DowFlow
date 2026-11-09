"""Small Windows launcher for source-mode DowFlow installations.

The launcher is built as a windowless EXE with the DowFlow icon. It delegates
execution to the project's virtual-environment Python so the local source mode
keeps its normal update and dependency behavior without exposing python.exe as
the launch entry point.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def project_root() -> Path:
    executable_dir = Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False):
        if executable_dir.name.lower() == "dist" and (executable_dir.parent / "startup.py").is_file():
            return executable_dir.parent
        return executable_dir
    return Path(__file__).resolve().parent


def main() -> int:
    root = project_root()
    python_exe = root / ".venv" / "Scripts" / "python.exe"
    if not python_exe.is_file():
        python_exe = root / ".venv" / "bin" / "python"
    if not python_exe.is_file():
        python_exe = Path(sys.executable)

    startup = root / "startup.py"
    if not startup.is_file():
        return 2

    environment = os.environ.copy()
    environment["DOWFLOW_LAUNCHER_ACTIVE"] = "1"
    completed = subprocess.run(
        [str(python_exe), str(startup), *sys.argv[1:]],
        cwd=str(root),
        env=environment,
        check=False,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
