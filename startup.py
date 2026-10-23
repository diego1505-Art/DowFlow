"""DowFlow's animated terminal startup screen and Flask launcher."""

import codecs
import os
import re
import socket
import subprocess
import sys
import time
import webbrowser
from collections import deque
from queue import Empty, Queue
from pathlib import Path
from threading import Thread
from typing import BinaryIO

from rich.align import Align
from rich.box import ROUNDED
from rich.console import Console, Group
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

STARTUP_PANEL_HEIGHT = 18
APP_VERSION = "V13"


def _triangle_rows(console: Console, frame_number: int) -> Table:
    """Build a round-dot triangle on a fixed nine-column grid."""
    unicode_terminal = console.encoding.lower().startswith("utf")
    glyph = "●" if unicode_terminal else "#"
    counts = (9, 7, 5, 3, 1)
    highlight_row = (frame_number // 2) % len(counts)
    grid = Table.grid(padding=(0, 1), expand=False)
    for _ in range(9):
        grid.add_column(width=1, justify="center")
    for row_number, count in enumerate(counts):
        style = "bold #ff5a3d" if row_number == highlight_row else "bold #b82c2e"
        start = (9 - count) // 2
        cells = [Text("") for _ in range(9)]
        for column in range(start, start + count):
            cells[column] = Text(glyph, style=style)
        grid.add_row(*cells)
    return grid


def _frame(
    console: Console,
    frame_number: int,
    complete: bool = False,
    failed: bool = False,
    version_text: str = "",
) -> Panel:
    unicode_terminal = console.encoding.lower().startswith("utf")
    bar_empty = "·" if unicode_terminal else "."
    bar_fill = "━" if unicode_terminal else "="
    progress_width = 30
    progress = progress_width if complete else min(progress_width - 1, frame_number // 3)
    status = (
        "Initialisation terminée" if complete
        else "Échec de l'initialisation" if failed
        else "Démarrage du serveur"
    )
    dots = "" if complete or failed else "." * ((frame_number // 5) % 4)
    bar_style = "bold red" if failed else "bold #ff5a3d"
    bar = Text(bar_fill * progress + bar_empty * (progress_width - progress), style=bar_style)
    content: list[Text | Align | Table] = [
        Text(""),
        Align.center(_triangle_rows(console, frame_number)),
        Text(""),
        Text("D O W F L O W", style="bold white", justify="center"),
        Text("VIDEO   AUDIO   MEDIA", style="dim", justify="center"),
        Text(""),
        bar,
        Text(f"{status}{dots}", style="bold red" if failed else "dim", justify="center"),
    ]
    if complete and version_text:
        content.append(Text(version_text, style="dim #ff5a3d", justify="center"))
    panel = Panel(
        Group(*content),
        title=f" DOWFLOW {APP_VERSION} / STARTUP ",
        title_align="center",
        border_style="#7d2829",
        box=ROUNDED,
        padding=(1, 4),
    )
    return panel


def _port_is_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.15):
            return True
    except OSError:
        return False


def _version_line(command: str) -> str | None:
    try:
        result = subprocess.run(
            [command, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return next((line.strip() for line in result.stdout.splitlines() if line.strip()), None)


def _startup_version_text() -> str:
    aria2_version = _version_line("aria2c")
    node_version = _version_line("node")
    details: list[str] = [f"DowFlow {APP_VERSION}"]
    if aria2_version:
        version = aria2_version.removeprefix("aria2 version ")
        details.append(f"aria2c v{version}")
    else:
        details.append("aria2c indisponible")
    details.append(f"Node {node_version}" if node_version else "Node.js absent")
    return "  |  ".join(details)


def _capture_output(stream: BinaryIO, output: Queue[str | None]) -> None:
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    pending = ""
    while chunk := stream.read(4096):
        pending += decoder.decode(chunk)
        lines = re.split(r"[\r\n]+", pending)
        pending = lines.pop()
        for line in lines:
            output.put(line)
    pending += decoder.decode(b"", final=True)
    if pending:
        output.put(pending)
    output.put(None)


def _drain_output(output: Queue[str | None], lines: deque[str]) -> bool:
    finished = False
    while True:
        try:
            item = output.get_nowait()
        except Empty:
            return finished
        if item is None:
            finished = True
        else:
            lines.append(item)


def _logs_panel(lines: deque[str], max_lines: int) -> Panel:
    visible_lines = list(lines)[-max_lines:]
    if not visible_lines:
        visible_lines = ["En attente des journaux du serveur..."]
    content = Group(*(Text.from_ansi(line) for line in visible_lines))
    return Panel(content, title="Journaux système", border_style="#7d2829")


def _update_dashboard(
    layout: Layout,
    console: Console,
    frame_number: int,
    lines: deque[str],
    complete: bool = False,
    failed: bool = False,
    version_text: str = "",
) -> None:
    layout["startup"].update(
        Align.center(
            _frame(console, frame_number, complete, failed, version_text),
            vertical="middle",
            height=STARTUP_PANEL_HEIGHT,
        )
    )
    log_height = max(1, console.size.height - STARTUP_PANEL_HEIGHT - 3)
    layout["logs"].update(_logs_panel(lines, log_height))


def main() -> int:
    console = Console()
    host = os.environ.get("DOWFLOW_HOST", "127.0.0.1")
    port = int(os.environ.get("DOWFLOW_PORT", "5001"))
    probe_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    url_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    url = f"http://{url_host}:{port}"
    process = None
    output: Queue[str | None] = Queue()
    output_reader: Thread | None = None
    failure = None

    if _port_is_open(probe_host, port):
        failure = f"Le port {port} est déjà utilisé."
    else:
        try:
            process = subprocess.Popen(
                [sys.executable, str(Path(__file__).with_name("app.py"))],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
            )
            assert process.stdout is not None
            output_reader = Thread(target=_capture_output, args=(process.stdout, output), daemon=True)
            output_reader.start()
        except OSError as error:
            failure = f"Impossible de lancer Flask : {error}"

    deadline = time.monotonic() + 10
    frame_number = 0
    ready = False
    output_finished = False
    exit_code = 1
    version_text = ""
    log_lines: deque[str] = deque(["Démarrage du serveur DowFlow..."], maxlen=500)
    layout = Layout()
    layout.split_column(
        Layout(name="startup", size=STARTUP_PANEL_HEIGHT),
        Layout(name="logs", ratio=1, minimum_size=4),
    )
    _update_dashboard(layout, console, frame_number, log_lines)
    try:
        with Live(layout, console=console, refresh_per_second=8, transient=False):
            while True:
                output_finished = _drain_output(output, log_lines) or output_finished

                if not ready and failure is None:
                    if process is not None and _port_is_open(probe_host, port):
                        ready = True
                        version_text = _startup_version_text()
                        log_lines.append(f"Serveur démarré sur {url}")
                        try:
                            browser_opened = webbrowser.open(url)
                        except Exception:
                            browser_opened = False
                        if browser_opened:
                            log_lines.append("Interface ouverte dans le navigateur.")
                        else:
                            log_lines.append(f"Ouvrez cette adresse dans votre navigateur : {url}")
                    elif process is not None and process.poll() is not None:
                        failure = f"Le serveur s'est arrêté au démarrage (code {process.returncode})."
                    elif process is not None and time.monotonic() >= deadline:
                        failure = "Le serveur n'a pas répondu après 10 secondes."

                if failure is not None:
                    if process is not None and process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
                    if output_reader is not None:
                        output_reader.join(timeout=2)
                    output_finished = _drain_output(output, log_lines) or output_finished
                    log_lines.append(failure)
                    log_lines.append("Consultez le dossier logs pour le détail.")
                    _update_dashboard(
                        layout, console, frame_number, log_lines, failed=True
                    )
                    break

                _update_dashboard(
                    layout,
                    console,
                    frame_number,
                    log_lines,
                    complete=ready,
                    version_text=version_text,
                )
                if ready and process is not None and process.poll() is not None and output_finished:
                    exit_code = process.returncode or 0
                    if exit_code:
                        log_lines.append(f"Serveur arrêté avec le code {exit_code}.")
                        _update_dashboard(
                            layout,
                            console,
                            frame_number,
                            log_lines,
                            complete=True,
                            version_text=version_text,
                        )
                    break

                frame_number += 1
                time.sleep(0.125)
    except KeyboardInterrupt:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait()
        if output_reader is not None:
            output_reader.join(timeout=2)
        return 0

    return exit_code


if __name__ == "__main__":
    main()