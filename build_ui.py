"""Coloured, animated front-end for the DowFlow build launcher.

``build.bat`` only bootstraps the virtual environment and then hands over to
this module so the menu, the prompts, the status lines and the progress bar all
share one coloured console with a looping flow animation instead of plain
``echo`` text.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import build_progress as bp

ROOT = Path(__file__).resolve().parent

SCOPES = (
    ("1", "all", "Whole menu", "dist\\DowFlow.exe"),
    ("2", "video", "Video", "dist\\DowFlow-Video.exe"),
    ("3", "music", "Music", "dist\\DowFlow-Music.exe"),
    ("4", "film", "Movies / Series", "dist\\DowFlow-Films.exe"),
    ("5", "anime", "Anime", "dist\\DowFlow-Anime.exe"),
)

WAVE = "▁▂▃▄▅▆▇█▇▆▅▄▃▂"

CYAN = (34, 211, 238)
BLUE = (96, 165, 250)
VIOLET = (167, 139, 250)
PINK = (244, 114, 182)
AMBER = (251, 191, 36)
GREEN = (74, 222, 128)
RED = (248, 113, 113)
MUTED = (148, 163, 184)
WHITE = (241, 245, 249)
PATH_BLUE = (129, 140, 248)

_INVALID_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def clean_name(value: str) -> str:
    """Sanitise an executable name the same way the build export does."""
    name = Path(value).stem.strip()
    name = _INVALID_NAME.sub("_", name).strip(" .")
    if not name or name.upper() in _RESERVED_NAMES:
        raise ValueError("Choisis un nom d'exécutable Windows valide.")
    return name[:100]


class Console:
    """Small coloured console with an animated flow banner."""

    def __init__(self) -> None:
        self.is_tty = bool(getattr(sys.stdout, "isatty", lambda: False)())
        self.vt = bp.enable_vt() if self.is_tty else False
        self.colour = self.vt and not os.environ.get("NO_COLOR")
        self.width = max(40, min(shutil.get_terminal_size((100, 24)).columns, 140))

    def paint(self, text: str, colour: tuple[int, int, int], bold: bool = False) -> str:
        if not self.colour:
            return text
        painted = bp.paint(text, colour, True)
        return f"\x1b[1m{painted}" if bold else painted

    def write(self, text: str = "") -> None:
        sys.stdout.write(text)
        sys.stdout.flush()

    def clear(self) -> None:
        if self.vt:
            self.write("\x1b[2J\x1b[H")
        elif self.is_tty:
            os.system("cls")

    def wave(self, tick: int) -> str:
        span = max(10, self.width - 4)
        cells = []
        for index in range(span):
            char = WAVE[(index + tick) % len(WAVE)]
            shade = bp.gradient((index / span + tick * 0.02) % 1.0)
            cells.append(bp.paint(char, shade, True))
        return "  " + "".join(cells)

    def show_flow(self, subtitle: str, duration: float = 2.0) -> None:
        """Loop a flowing wave banner, then leave the last frame on screen."""
        if not (self.is_tty and self.colour):
            self.write(f"\n  DOWFLOW BUILD  {subtitle}\n\n")
            return
        frames = max(12, int(duration / 0.045))
        self.write("\n" + bp.HIDE_CURSOR)
        for frame in range(frames):
            title = "  " + bp.rainbow_text("DOWFLOW BUILD", True, frame * 0.015)
            block = [
                self.wave(frame),
                f"{title}  {self.paint(subtitle, CYAN, True)}",
                self.wave(-frame * 2),
            ]
            if frame:
                self.write("\x1b[3A")
            for line in block:
                self.write("\x1b[2K" + line + "\n")
            time.sleep(0.045)
        self.write(bp.SHOW_CURSOR)

    def rule(self, span: int = 46) -> str:
        return "".join(
            bp.paint("─", bp.gradient(index / max(1, span - 1), None), True)
            if self.colour
            else "─"
            for index in range(span)
        )

    def menu(self) -> None:
        self.write("\n  " + self.rule() + "\n\n")
        for index, (key, _scope, label, target) in enumerate(SCOPES):
            number = self.paint(key, bp._STOPS[index % len(bp._STOPS)], bold=True)
            self.write(
                f"    {number}  {self.paint(f'{label:<18}', WHITE, bold=True)}"
                f"{self.paint(target, PATH_BLUE)}\n"
            )
        zero = self.paint("0", PINK, bold=True)
        self.write(f"    {zero}  {self.paint('Quit', MUTED)}\n\n")
        self.write("  " + self.rule() + "\n")

    def note(
        self,
        text: str,
        colour: tuple[int, int, int] = MUTED,
        marker: str = "◆",
    ) -> None:
        self.write(f"  {self.paint(marker, colour, True)} {self.paint(text, colour)}\n")

    def ask(self, label: str) -> str:
        prompt = (
            "  "
            + self.paint("›", AMBER, True)
            + " "
            + self.paint(label, CYAN)
            + " "
        )
        return input(prompt)

    def pause(self, label: str = "Entrée pour revenir au menu") -> None:
        self.ask(label)


def ensure_build_requirements(console: Console) -> bool:
    probe = subprocess.run(
        [sys.executable, "-c", "import PyInstaller"],
        capture_output=True,
    )
    if probe.returncode == 0:
        return True
    console.note("Installation des dépendances de build…", AMBER, "↓")
    code = subprocess.call(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-q",
            "-r",
            str(ROOT / "requirements-build.txt"),
        ]
    )
    if code != 0:
        console.note("Impossible d'installer les dépendances de build.", RED, "×")
        return False
    return True


def run_build(console: Console, scope: str, name: str) -> int:
    console.write("\n")
    sys.stdout.flush()
    if console.is_tty:
        return bp.run_animated(scope, name)
    return subprocess.call(
        [sys.executable, str(ROOT / "build_export.py"), scope, name],
        cwd=ROOT,
    )


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    console = Console()
    try:
        while True:
            console.clear()
            console.show_flow("PyInstaller · Windows")
            console.menu()
            choice = console.ask("Choix [0-5] :").strip()

            if choice == "0":
                console.write("\n  " + console.paint("À bientôt.", MUTED) + "\n\n")
                return 0
            match = next((row for row in SCOPES if row[0] == choice), None)
            if match is None:
                console.note("Choix invalide, recommence.", RED, "×")
                time.sleep(0.7)
                continue

            _key, scope, label, default_name = match
            console.write("\n")
            console.note(f"Édition « {label} »", CYAN)
            console.note(
                "Ferme DowFlow : l'exécutable embarque la base actuelle.",
                AMBER,
                "!",
            )
            console.write("\n")
            while True:
                raw = console.ask(f"Nom de l'exécutable [{default_name}] :").strip()
                try:
                    name = clean_name(raw or default_name)
                except ValueError as exc:
                    console.note(str(exc), RED, "×")
                    continue
                break

            if not ensure_build_requirements(console):
                console.write("\n")
                console.pause()
                continue

            code = run_build(console, scope, name)
            target = ROOT / "dist" / f"{name}.exe"
            console.write("\n")
            if code == 0 and target.is_file():
                console.note(str(target), GREEN, "✓")
            else:
                console.note(
                    "Le build a échoué, regarde les messages au-dessus.",
                    RED,
                    "×",
                )
            console.write("\n")
            console.pause()
    except KeyboardInterrupt:
        sys.stdout.write("\n  " + console.paint("Interrompu.", MUTED) + "\n\n")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
