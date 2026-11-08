"""Open a native folder picker and print the selected path for the caller."""
from __future__ import annotations

import sys
from pathlib import Path
from tkinter import Tk, filedialog


def select_download_folder(
    initial_directory: str | None = None,
    title: str = "Select Media Download Folder",
) -> str | None:
    root = Tk()
    root.withdraw()
    try:
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass
        return filedialog.askdirectory(
            parent=root,
            title=title,
            initialdir=initial_directory or str(Path.home()),
            mustexist=True,
        ) or None
    finally:
        root.destroy()


def main(arguments: list[str] | None = None) -> int:
    values = arguments if arguments is not None else sys.argv[1:]
    if values and values[0] == "--save-exe":
        if len(values) < 3:
            return 2
        scope, initial_directory = values[1], values[2]
        default_name = "DowFlow.exe" if scope == "all" else f"DowFlow-{scope.title()}.exe"
        root = Tk()
        root.withdraw()
        try:
            try:
                root.attributes("-topmost", True)
            except Exception:
                pass
            selected = filedialog.asksaveasfilename(
                parent=root,
                title="Export DowFlow as a Windows executable",
                initialdir=initial_directory,
                initialfile=default_name,
                defaultextension=".exe",
                filetypes=[("Windows executable", "*.exe")],
                confirmoverwrite=True,
            )
        finally:
            root.destroy()
        if selected:
            print(selected)
        return 0

    initial_directory = values[0] if values else None
    selected = select_download_folder(initial_directory)
    if selected:
        print(selected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
