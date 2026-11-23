"""Animated console progress for the DowFlow PyInstaller build.

``build.bat`` calls this module instead of ``build_export.py`` so a long
long build shows a moving, coloured progress bar instead of a silent
window. The real build still runs in ``build_export.py``; its JSON progress
events are consumed here.
"""
from __future__ import annotations

import ctypes
import json
import math
import os
import queue
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
HIDE_CURSOR = "\x1b[?25l"
SHOW_CURSOR = "\x1b[?25h"
SAVE_CURSOR = "\x1b7"
RESTORE_CURSOR = "\x1b8"

_STOPS = (
    (244, 63, 94),
    (251, 146, 60),
    (250, 204, 21),
    (74, 222, 128),
    (34, 211, 238),
    (96, 165, 250),
    (167, 139, 250),
    (232, 121, 249),
)

_STAGE_LABELS = {
    "Preparing build": "Préparation",
    "Scanning dependencies": "Analyse des dépendances",
    "Analyzing application": "Analyse de l'application",
    "Collecting runtime libraries": "Collecte des bibliothèques",
    "Compressing Python modules": "Compression des modules",
    "Packing application files": "Assemblage des fichiers",
    "Creating executable": "Création de l'exécutable",
    "Finalizing executable": "Finalisation",
    "Assembling application folder": "Assemblage des fichiers",
    "Finalizing application folder": "Finalisation des fichiers",
    "Preparing media tools": "Préparation des outils",
    "Compressing the installer": "Compression de l'installeur",
    "Building executable": "Compilation",
    "Complete": "Terminé",
}


@dataclass
class ProgressState:
    percent: int = 0
    stage: str = "Preparing build"
    eta_seconds: int | None = None
    complete: bool = False
    failed: bool = False


def _enable_vt() -> bool:
    """Enable ANSI escapes in the Windows console when possible."""
    if os.name != "nt":
        return True
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, int(mode.value) | 0x0004))
    except Exception:
        return False


def _paint(text: str, colour: tuple[int, int, int], enabled: bool) -> str:
    if not enabled:
        return text
    return f"\x1b[38;2;{colour[0]};{colour[1]};{colour[2]}m{text}{RESET}"


def _bold(text: str, enabled: bool) -> str:
    return f"{BOLD}{text}{RESET}" if enabled else text


def _truncate(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit == 1:
        return "…"
    return text[: limit - 1] + "…"


def _format_eta(seconds: int | None) -> str:
    if seconds is None:
        return "~--:--"
    seconds = max(0, int(seconds))
    minutes, sec = divmod(seconds, 60)
    if minutes >= 60:
        hours, minutes = divmod(minutes, 60)
        return f"~{hours}h{minutes:02d}"
    return f"~{minutes:02d}:{sec:02d}"


def _stage_label(stage: str) -> str:
    return _STAGE_LABELS.get(stage, stage or "Compilation")


def _gradient(
    value: float,
    stops: tuple[tuple[int, int, int], ...] | None = None,
) -> tuple[int, int, int]:
    palette = stops or _STOPS
    value = max(0.0, min(1.0, value))
    scaled = value * (len(palette) - 1)
    index = min(int(scaled), len(palette) - 2)
    fraction = scaled - index
    left, right = palette[index], palette[index + 1]
    return tuple(
        round(left[channel] + (right[channel] - left[channel]) * fraction)
        for channel in range(3)
    )


def _rainbow_text(text: str, colour: bool, phase: float = 0.0) -> str:
    """Paint each visible character along the colour palette."""
    if not colour:
        return text
    last = max(1, len(text) - 1)
    painted = []
    for index, char in enumerate(text):
        if char == " ":
            painted.append(char)
            continue
        shade = _gradient((index / last + phase) % 1.0)
        painted.append(_paint(char, shade, True))
    return "".join(painted)


paint = _paint
gradient = _gradient
rainbow_text = _rainbow_text
enable_vt = _enable_vt


def render_frame(
    state: ProgressState,
    tick: int,
    width: int,
    colour: bool = True,
) -> str:
    """Build one line of the animated progress display."""
    width = max(40, int(width))
    percent = max(0, min(100, state.percent))
    remaining = max(0, 100 - percent)
    eta = _format_eta(state.eta_seconds)

    if state.failed:
        spinner = "×"
        stage = "ÉCHEC"
        percent_colour = (239, 68, 68)
        spinner_colour = (239, 68, 68)
    elif state.complete:
        spinner = "✓"
        stage = "Terminé"
        percent_colour = (34, 197, 94)
        spinner_colour = (34, 197, 94)
    else:
        spinner = SPINNER[tick % len(SPINNER)]
        stage = _stage_label(state.stage)
        percent_colour = _gradient(percent / 100)
        spinner_colour = _STOPS[(tick * 2) % len(_STOPS)]

    if width < 60:
        plain_suffix = f"] {percent:3d}%  {remaining:3d}%"
        bar_width = max(8, min(24, width - len(plain_suffix) - 8))
        stage_text = ""
    else:
        plain_suffix = f"] {percent:3d}%  reste {remaining:3d}%  {eta}"
        bar_width = max(12, min(36, width - len(plain_suffix) - 12))
        stage_space = width - 5 - bar_width - len(plain_suffix) - 2
        stage_text = (
            "  " + _truncate(stage, stage_space) if stage_space >= 6 else ""
        )

    bracket = _paint("[", (148, 163, 184), colour)
    prefix = f"  {_paint(spinner, spinner_colour, colour)} {bracket}"
    filled = int(round(bar_width * percent / 100))
    scan = int((math.sin(tick * 0.20) + 1) * 0.5 * max(0, bar_width - 1))
    cells: list[str] = []
    for index in range(bar_width):
        if index < filled:
            if state.failed:
                cell_colour = (239, 68, 68)
            elif state.complete:
                cell_colour = (34, 197, 94)
            else:
                cell_colour = _gradient(index / max(1, bar_width - 1))
            cell = "█"
            if not state.complete and not state.failed and abs(index - scan) <= 1:
                cell = "▓"
                cell_colour = (
                    (255, 255, 255) if (tick // 2) % 2 == 0 else (250, 204, 21)
                )
        else:
            cell = "░"
            cell_colour = (86, 78, 122)
            if not state.complete and not state.failed and index == scan:
                cell = "·"
                cell_colour = (148, 163, 184)
        cells.append(_paint(cell, cell_colour, colour))

    percent_text = _paint(f"{percent:3d}%", percent_colour, colour)
    remaining_colour = (
        (34, 197, 94) if state.complete else (239, 68, 68) if state.failed else (244, 114, 182)
    )
    remaining_text = _paint(
        f"reste {remaining:3d}%" if width >= 60 else f"{remaining:3d}%",
        remaining_colour,
        colour,
    )
    eta_text = _paint(eta, (251, 191, 36), colour) if width >= 60 else ""
    close = _paint("]", (148, 163, 184), colour)
    suffix = f"{close} {percent_text}  {remaining_text}" + (
        f"  {eta_text}" if eta_text else ""
    )
    stage_part = (
        _paint(
            stage_text,
            (34, 197, 94)
            if state.complete
            else (239, 68, 68)
            if state.failed
            else (165, 180, 252),
            colour,
        )
        if stage_text
        else ""
    )
    return f"{prefix}{''.join(cells)}{suffix}{stage_part}"


class BuildDisplay:
    """Render progress on a background thread while PyInstaller runs."""

    def __init__(
        self,
        scope: str,
        name: str,
        stream: object | None = None,
        top_row: int | None = None,
    ) -> None:
        self.scope = scope
        self.name = name
        self.stream = stream or sys.stdout
        # When the caller keeps its own animated banner on the reserved rows,
        # the progress line is pinned under it instead of pushing the screen.
        self.top_row = top_row
        self.is_tty = bool(
            getattr(self.stream, "isatty", lambda: False)()
        )
        self.vt = _enable_vt() if self.is_tty else False
        self.colour = self.vt and not os.environ.get("NO_COLOR")
        self.width = max(
            40,
            min(shutil.get_terminal_size((100, 20)).columns, 140),
        )
        self.state = ProgressState(stage="Lancement de PyInstaller")
        self.tick = 0
        self.shown = 0.0
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = False

    @property
    def started(self) -> bool:
        return self._started

    def _write(self, text: str) -> None:
        with self._write_lock:
            self.stream.write(text)
            self.stream.flush()

    def start(self) -> None:
        if not self.is_tty:
            return
        if self.vt:
            self._write(HIDE_CURSOR)
        if self.top_row is not None:
            # Keep the caller's cursor position: the progress line is drawn at
            # the bottom of the window and the messages resume where they were.
            self._write(SAVE_CURSOR)
        if self.top_row is None:
            rule = "".join(
                _paint("─", _gradient(index / 51), self.colour) for index in range(52)
            )
            title = _bold(_rainbow_text("DOWFLOW BUILD", self.colour), self.vt)
            subtitle = _paint(
                f"{self.scope} · {self.name}", (125, 211, 252), self.colour
            )
            spark = _paint("◆", (250, 204, 21), self.colour)
            self._write(f"\n  {rule}\n  {spark} {title}  {subtitle}\n  {rule}\n")
        self._started = True
        self._thread = threading.Thread(
            target=self._loop,
            name="build-progress",
            daemon=True,
        )
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(0.075):
            with self._lock:
                self.tick += 1
            self.render()

    def update(self, event: dict[str, object]) -> None:
        with self._lock:
            try:
                value = int(event.get("percent", self.state.percent))
            except (TypeError, ValueError):
                value = self.state.percent
            self.state.percent = max(self.state.percent, min(100, value))
            stage = event.get("stage")
            if isinstance(stage, str) and stage:
                self.state.stage = stage
            eta = event.get("eta_seconds")
            if eta is None:
                self.state.eta_seconds = None
            elif isinstance(eta, (int, float)):
                self.state.eta_seconds = max(0, int(eta))

    def render(self) -> None:
        if not self._started:
            return
        with self._lock:
            target = 100.0 if self.state.complete else float(self.state.percent)
            self.shown += (target - self.shown) * 0.25
            if abs(target - self.shown) < 0.05:
                self.shown = target
            frame_state = ProgressState(
                percent=int(round(self.shown)),
                stage=self.state.stage,
                eta_seconds=self.state.eta_seconds,
                complete=self.state.complete,
                failed=self.state.failed,
            )
            tick = self.tick
        frame = render_frame(frame_state, tick, self.width, self.colour)
        if self.top_row is not None:
            self._write(f"\x1b[{self.top_row};1H\x1b[2K{frame}")
            return
        clear = "\x1b[2K\r" if self.vt else "\r" + " " * self.width + "\r"
        self._write(clear + frame)

    def stop(self, success: bool) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
        if not self._started:
            return
        with self._lock:
            self.state.complete = success
            self.state.failed = not success
            self.state.stage = "Complete" if success else "ÉCHEC"
            if success:
                self.state.percent = 100
                self.shown = 100.0
            self.tick += 1
        self.render()
        if self.top_row is not None:
            # Back to the line the caller was on before the build started.
            self._write((RESTORE_CURSOR + SHOW_CURSOR) if self.vt else "")
        else:
            self._write("\n" + (SHOW_CURSOR if self.vt else ""))
        self._started = False


def _pump(stream: object, messages: queue.Queue[tuple[str, object]]) -> None:
    try:
        for raw in stream:  # type: ignore[union-attr]
            line = raw.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except (TypeError, ValueError):
                messages.put(("log", line))
                continue
            if not isinstance(payload, dict):
                messages.put(("log", line))
                continue
            kind = payload.get("type")
            if kind in {"progress", "complete"}:
                messages.put((str(kind), payload))
            else:
                messages.put(("log", line))
    finally:
        messages.put(("eof", None))


def run_animated(
    scope: str,
    name: str,
    installer: bool = True,
    blank: bool = False,
    top_row: int | None = None,
) -> int:
    display = BuildDisplay(scope, name, top_row=top_row)
    display.start()
    command = [
        sys.executable,
        str(ROOT / "build_export.py"),
        scope,
        name,
        "--json-progress",
    ]
    if installer:
        command.append("--installer")
    if blank:
        command.append("--blank")
    try:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except OSError as exc:
        display.stop(False)
        print(f"\n  Impossible de lancer le build : {exc}", file=sys.stderr)
        return 1

    messages: queue.Queue[tuple[str, object]] = queue.Queue()
    logs: list[str] = []
    reader = threading.Thread(
        target=_pump,
        args=(process.stdout, messages),
        name="build-output",
        daemon=True,
    )
    reader.start()
    completed_path = ""
    loop_finished = False

    try:
        try:
            while True:
                kind, payload = messages.get()
                if kind == "progress" and isinstance(payload, dict):
                    display.update(payload)
                elif kind == "complete" and isinstance(payload, dict):
                    completed_path = str(payload.get("path") or "")
                    display.update({"percent": 100, "stage": "Complete"})
                elif kind == "log":
                    logs.append(str(payload))
                else:
                    break
            loop_finished = True
        except KeyboardInterrupt:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            print("\n  Build interrompu.", file=sys.stderr)
            return 130
    finally:
        if not loop_finished and display.started:
            display.stop(False)

    returncode = process.wait()
    reader.join(timeout=1)
    success = (
        returncode == 0
        and bool(completed_path)
        and Path(completed_path).is_file()
    )
    display.stop(success)
    if success:
        return 0
    if logs:
        print("\n".join(logs[-80:]), file=sys.stderr)
    print(f"\n  Build échoué (code {returncode}).", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("Usage: build_progress.py <scope> <name>", file=sys.stderr)
        return 2
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    if not sys.stdout.isatty():
        return subprocess.call(
            [
                sys.executable,
                str(ROOT / "build_export.py"),
                args[0],
                args[1],
                "--installer",
            ],
            cwd=ROOT,
        )
    return run_animated(args[0], args[1], installer=True)


if __name__ == "__main__":
    raise SystemExit(main())
