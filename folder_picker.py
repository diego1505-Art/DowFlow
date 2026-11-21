"""Open a native folder picker and print the selected path for the caller."""
from __future__ import annotations

import sys
from pathlib import Path


def select_download_folder(
    initial_directory: str | None = None,
    title: str = "Select Media Download Folder",
) -> str | None:
    from tkinter import Tk, filedialog

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


def select_cookie_file(
    initial_directory: str | None = None,
    title: str = "Select a Netscape cookie export",
) -> str | None:
    """Open a native file picker for a cookies.txt export."""
    from tkinter import Tk, filedialog

    root = Tk()
    root.withdraw()
    try:
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass
        return filedialog.askopenfilename(
            parent=root,
            title=title,
            initialdir=initial_directory or str(Path.home() / "Downloads"),
            filetypes=[("Cookie exports", "*.txt"), ("All files", "*.*")],
        ) or None
    finally:
        root.destroy()


def main(arguments: list[str] | None = None) -> int:
    values = arguments if arguments is not None else sys.argv[1:]
    initial_directory = values[0] if values else None
    selected = select_download_folder(initial_directory)
    if selected:
        print(selected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
