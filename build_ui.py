"""Coloured, animated front-end for the DowFlow build launcher.

``build.bat`` only bootstraps the virtual environment and then hands over to
this module so the menu, the prompts, the status lines and the progress bar all
share one coloured console. The wave banner keeps flowing for as long as the
menu waits for a choice.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import build_progress as bp
from build_export import default_output_dir

ROOT = Path(__file__).resolve().parent

SCOPES = (
    ("1", "all", "Whole menu", "DowFlow", "DowFlow-Setup.exe"),
    ("2", "video", "Video", "DowFlow-Video", "DowFlow-Video-Setup.exe"),
    ("3", "music", "Music", "DowFlow-Music", "DowFlow-Music-Setup.exe"),
    ("4", "film", "Movies / Series", "DowFlow-Films", "DowFlow-Films-Setup.exe"),
    ("5", "anime", "Anime", "DowFlow-Anime", "DowFlow-Anime-Setup.exe"),
)

WAVE = "▁▂▃▄▅▆▇█▇▆▅▄▃▂"
BLANK_ANSWERS = frozenset({"o", "oui", "y", "yes"})

CYAN = (34, 211, 238)
AMBER = (251, 191, 36)
GREEN = (74, 222, 128)
RED = (248, 113, 113)
MUTED = (148, 163, 184)
WHITE = (241, 245, 249)
PATH_BLUE = (129, 140, 248)

SAVE_CURSOR = "\x1b7"
RESTORE_CURSOR = "\x1b8"
FLOW_INTERVAL = 0.045


class Console:
    """Small coloured console with an animated flow banner."""

    def __init__(self) -> None:
        self.is_tty = bool(getattr(sys.stdout, "isatty", lambda: False)())
        self.vt = bp.enable_vt() if self.is_tty else False
        self.colour = self.vt and not os.environ.get("NO_COLOR")
        self.width = max(40, min(shutil.get_terminal_size((100, 24)).columns, 140))
        self._write_lock = threading.Lock()

    def paint(self, text: str, colour: tuple[int, int, int], bold: bool = False) -> str:
        if not self.colour:
            return text
        painted = bp.paint(text, colour, True)
        return f"\x1b[1m{painted}" if bold else painted

    def write(self, text: str = "") -> None:
        with self._write_lock:
            sys.stdout.write(text)
            sys.stdout.flush()

    def clear(self) -> None:
        if self.vt:
            self.write("\x1b[2J\x1b[H")
        elif self.is_tty:
            os.system("cls")

    def clear_below(self, rows: int) -> None:
        """Clear everything under the animated banner without touching it."""
        self.write(f"\x1b[{rows + 1};1H\x1b[0J")

    def wave(self, tick: int) -> str:
        span = max(10, self.width - 4)
        cells = []
        for index in range(span):
            char = WAVE[(index + tick) % len(WAVE)]
            shade = bp.gradient((index / span + tick * 0.02) % 1.0)
            cells.append(bp.paint(char, shade, True))
        return "  " + "".join(cells)

    def banner(self, tick: int, subtitle: str) -> list[str]:
        title = "  " + bp.rainbow_text("DOWFLOW BUILD", True, tick * 0.015)
        return [
            self.wave(tick),
            f"{title}  {self.paint(subtitle, CYAN, True)}",
            self.wave(-tick * 2),
        ]

    def start_flow(self, subtitle: str) -> "Flow | None":
        """Reserve the banner rows and animate them for the whole session."""
        if not (self.is_tty and self.colour):
            self.write(f"\n\n\n  DOWFLOW BUILD  {subtitle}\n")
            return None
        flow = Flow(self, subtitle)
        flow.start()
        return flow

    def rule(self, span: int = 46) -> str:
        return "".join(
            bp.paint("─", bp.gradient(index / max(1, span - 1), None), True)
            if self.colour
            else "─"
            for index in range(span)
        )

    def menu(self) -> None:
        self.write("\n  " + self.rule() + "\n\n")
        for index, (key, _scope, label, _name, setup) in enumerate(SCOPES):
            number = self.paint(key, bp._STOPS[index % len(bp._STOPS)], bold=True)
            target = str(default_output_dir() / setup)
            self.write(
                f"    {number}  {self.paint(f'{label:<18}', WHITE, bold=True)}"
                f"{self.paint(target, PATH_BLUE)}\n"
            )
        zero = self.paint("0", (244, 114, 182), bold=True)
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


class Flow:
    """Loop the wave banner on its own thread, above the prompt."""

    def __init__(self, console: Console, subtitle: str, rows: int = 3) -> None:
        self.console = console
        self.subtitle = subtitle
        self.rows = rows
        self.tick = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def draw(self) -> None:
        frame = [SAVE_CURSOR]
        for row, line in enumerate(self.console.banner(self.tick, self.subtitle), start=1):
            frame.append(f"\x1b[{row};1H\x1b[2K{line}")
        frame.append(RESTORE_CURSOR)
        self.console.write("".join(frame))

    def _loop(self) -> None:
        while not self._stop.wait(FLOW_INTERVAL):
            self.tick += 1
            self.draw()

    def start(self) -> None:
        self._stop.clear()
        self.console.write("\n" * self.rows)
        self.draw()
        self._thread = threading.Thread(
            target=self._loop,
            name="menu-flow",
            daemon=True,
        )
        self._thread.start()

    def pause(self) -> None:
        """Freeze the banner so a running build owns the console."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
            self._thread = None

    def resume(self) -> None:
        if self._thread is None:
            self.start()

    def stop(self) -> None:
        self.pause()
        self.draw()


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


def run_build(console: Console, scope: str, name: str, blank: bool = False) -> int:
    console.write("\n")
    sys.stdout.flush()
    if console.is_tty:
        return bp.run_animated(scope, name, installer=True, blank=blank)
    command = [sys.executable, str(ROOT / "build_export.py"), scope, name, "--installer"]
    if blank:
        command.append("--blank")
    return subprocess.call(command, cwd=ROOT)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    console = Console()
    console.clear()
    flow = console.start_flow("PyInstaller · Windows")
    try:
        while True:
            if flow is not None:
                console.clear_below(flow.rows)
            else:
                console.clear()
            console.menu()
            try:
                choice = console.ask("Choix [0-5] :").strip()
            except EOFError:
                console.write("\n")
                return 0

            if choice == "0":
                console.write("\n  " + console.paint("À bientôt.", MUTED) + "\n\n")
                return 0
            match = next((row for row in SCOPES if row[0] == choice), None)
            if match is None:
                console.note("Choix invalide, recommence.", RED, "×")
                time.sleep(0.7)
                continue

            _key, scope, label, name, setup = match
            console.write("\n")
            console.note(f"Édition « {label} »", CYAN)
            try:
                answer = (
                    console.ask("Un exe à blanc, pour la release ? [o/N] :")
                    .strip()
                    .lower()
                )
            except EOFError:
                console.write("\n")
                return 0
            blank = answer in BLANK_ANSWERS
            target = default_output_dir() / setup
            console.write("\n")
            if blank:
                console.note(f"Build à blanc (release) → {target}", CYAN)
                console.note(
                    "Sans cache ni données locales, pour la release.",
                    MUTED,
                    "◆",
                )
            else:
                console.note(f"Build normal → {target}", CYAN)
            console.note(
                "Les données iront dans %LOCALAPPDATA%\\DowFlow\\data.",
                MUTED,
                "◆",
            )
            console.write("\n")

            if not ensure_build_requirements(console):
                console.write("\n")
                console.pause()
                continue

            if flow is not None:
                flow.pause()
                console.clear()
            code = run_build(console, scope, name, blank=blank)
            if flow is not None:
                console.clear()
                flow.resume()
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
    finally:
        if flow is not None:
            flow.stop()


if __name__ == "__main__":
    raise SystemExit(main())
