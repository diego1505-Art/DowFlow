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
POST_READY_CAPTURE_SECONDS = 2.0
APP_VERSION = "V13"
_LOG_ENTRY_RE = re.compile(
    r"^(?P<time>\d{2}:\d{2}:\d{2})\s*\|\s*(?P<level>[A-Z]+)\s*\|\s*"
    r"(?P<logger>[^|]+?)\s*\|\s*(?P<message>.*)$"
)
_HTTP_ACCESS_RE = re.compile(
    r'^(?P<ip>.+?)\s+-\s+-\s+\[(?P<date>[^\]]+)\]\s+"'
    r'(?P<method>[A-Z]+)\s+(?P<path>.*?)\s+HTTP/(?P<version>[\d.]+)"\s+'
    r'(?P<status>\d{3})\s+(?P<size>\S+)$'
)
_ARIA2_PROGRESS_RE = re.compile(
    r"^\[#(?P<gid>[0-9a-fA-F]+)\s+(?P<downloaded>[^/\s]+)/(?P<total>[^\s(]+)"
    r"\((?P<percent>[\d.]+%)\)\s+CN:(?P<connections>\d+)"
    r"(?:\s+DL:(?P<speed>\S+))?(?:\s+ETA:(?P<eta>[^\]\s]+))?\]$"
)
_YTDLP_PROGRESS_RE = re.compile(
    r"^\[download\]\s+(?P<percent>[\d.]+%)\s+of\s+(?P<details>.+)$"
)


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
    progress_width = max(30, len(version_text), len("Initialization complete"))
    progress = progress_width if complete else min(progress_width - 1, frame_number // 3)
    status = (
        "Initialization complete" if complete
        else "Initialization failed" if failed
        else "Starting server"
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


def _format_output_line(line: str) -> Text:
    source = Text.from_ansi(line)
    plain = source.plain.strip()

    aria_match = _ARIA2_PROGRESS_RE.match(plain)
    if aria_match:
        parts = aria_match.groupdict()
        percent_style = "bold bright_cyan"
        display_id = parts["gid"]
        if len(display_id) == 6:
            try:
                display_id = str(int(display_id, 16))
            except ValueError:
                pass
        elif len(display_id) == 16:
            try:
                display_id = str(int(display_id, 16))
            except ValueError:
                pass
        text = Text()
        text.append("[", style="dim")
        text.append("#", style="dim")
        text.append(display_id, style="bold bright_magenta")
        text.append(" ", style="dim")
        text.append(parts["downloaded"], style="bold bright_green")
        text.append("/", style="dim")
        text.append(parts["total"], style="bright_black")
        text.append("(", style="dim")
        text.append(parts["percent"], style=percent_style)
        text.append(") CN:", style="dim")
        text.append(parts["connections"], style="bold bright_cyan")
        if parts["speed"]:
            text.append(" DL:", style="dim")
            text.append(parts["speed"], style="bold bright_green")
        if parts["eta"]:
            text.append(" ETA:", style="dim")
            text.append(parts["eta"], style="bold yellow")
        text.append("]", style="dim")
        return text

    ytdlp_match = _YTDLP_PROGRESS_RE.match(plain)
    if ytdlp_match:
        text = Text()
        text.append("[download] ", style="bold bright_cyan")
        text.append(ytdlp_match["percent"], style="bold bright_cyan")
        text.append(" of ", style="dim")
        text.append(ytdlp_match["details"], style="white")
        return text

    log_match = _LOG_ENTRY_RE.match(plain)
    if log_match:
        message = log_match["message"]
        text = Text()
        text.append(log_match["time"], style="dim")
        text.append(" | ", style="bright_black")
        level = log_match["level"]
        level_styles = {
            "DEBUG": "dim cyan",
            "INFO": "bold bright_cyan",
            "SUCCESS": "bold bright_green",
            "WARNING": "bold yellow",
            "ERROR": "bold bright_red",
            "CRITICAL": "bold bright_magenta",
        }
        text.append(level, style=level_styles.get(level, "bold white"))
        text.append(" | ", style="bright_black")
        text.append(log_match["logger"].strip(), style="bold #7dd3fc")
        text.append(" | ", style="bright_black")

        access_match = _HTTP_ACCESS_RE.match(message)
        if access_match:
            access = access_match.groupdict()
            status = int(access["status"])
            status_style = (
                "bold bright_green" if status < 400
                else "bold yellow" if status < 500
                else "bold bright_red"
            )
            text.append(access["ip"], style="dim")
            text.append(f" - - [{access['date']}] ", style="bright_black")
            text.append(f'"{access["method"]} ', style="bold bright_cyan")
            text.append(access["path"], style="white")
            text.append(f' HTTP/{access["version"]}" ', style="bright_black")
            text.append(access["status"], style=status_style)
            text.append(f" {access['size']}", style="dim")
        else:
            text.append_text(Text.from_ansi(message))
        return text

    if plain.startswith("ERROR:"):
        return Text(plain, style="bold bright_red")
    if plain.startswith("WARNING:"):
        return Text(plain, style="bold yellow")
    return source


def _is_adaptive_change_line(line: str) -> bool:
    match = _LOG_ENTRY_RE.match(Text.from_ansi(line).plain.strip())
    return bool(
        match
        and match["logger"].strip() == "playlist"
        and match["message"].startswith("[adaptive] ")
        and "retry at 0%." in match["message"]
    )


def _print_output_line(console: Console, line: str) -> None:
    if _is_adaptive_change_line(line):
        console.print()
    console.print(_format_output_line(line), soft_wrap=True)


def _should_show_output_line(line: str) -> bool:
    plain = Text.from_ansi(line).plain.strip()
    if plain.startswith(
        "WARNING: The extractor specified to use impersonation for this download, but no impersonate target is available."
    ):
        return False
    if plain.startswith("[download]") and ("Unknown B/s" in plain or "ETA Unknown" in plain):
        return False

    log_match = _LOG_ENTRY_RE.match(plain)
    if not log_match or log_match["logger"].strip() != "werkzeug":
        return True
    if log_match["level"] != "INFO":
        return True

    access_match = _HTTP_ACCESS_RE.match(log_match["message"])
    if not access_match:
        return True

    method = access_match["method"]
    path = access_match["path"].split("?", 1)[0]
    if method == "GET":
        return path in {"/", "/video", "/music", "/film", "/anime", "/image"}
    if method == "POST":
        return path in {
            "/api/music/download",
            "/api/music/search",
            "/download",
            "/download-async",
        }
    return False


def _drain_output(output: Queue[str | None], lines: deque[str]) -> bool:
    finished = False
    while True:
        try:
            item = output.get_nowait()
        except Empty:
            return finished
        if item is None:
            finished = True
        elif _should_show_output_line(item):
            lines.append(item)


def _logs_panel(lines: deque[str], max_lines: int) -> Panel:
    visible_lines = list(lines)[-max_lines:]
    if not visible_lines:
        visible_lines = ["Waiting for server logs..."]
    content_lines: list[Text] = []
    for line in visible_lines:
        if _is_adaptive_change_line(line):
            content_lines.append(Text(""))
        content_lines.append(_format_output_line(line))
    content = Group(*content_lines)
    return Panel(content, title="System logs", border_style="#7d2829")


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
        failure = f"Port {port} is already in use."
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
    ready_since: float | None = None
    log_lines: deque[str] = deque(["Starting DowFlow server..."], maxlen=500)
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
                        ready_since = time.monotonic()
                        version_text = _startup_version_text()
                        log_lines.append(f"Server started at {url}")
                        try:
                            browser_opened = webbrowser.open(url)
                        except Exception:
                            browser_opened = False
                        if browser_opened:
                            log_lines.append("Interface opened in the browser.")
                        else:
                            log_lines.append(f"Open this address in your browser: {url}")
                    elif process is not None and process.poll() is not None:
                        failure = f"The server stopped during startup (code {process.returncode})."
                    elif process is not None and time.monotonic() >= deadline:
                        failure = "The server did not respond within 10 seconds."

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
                    log_lines.append("See the logs folder for details.")
                    _update_dashboard(layout, console, frame_number, log_lines, failed=True)
                    break

                _update_dashboard(
                    layout,
                    console,
                    frame_number,
                    log_lines,
                    complete=ready,
                    version_text=version_text,
                )
                if ready and ready_since is not None and time.monotonic() - ready_since >= POST_READY_CAPTURE_SECONDS:
                    break

                frame_number += 1
                time.sleep(0.125)

        if ready and process is not None:
            while not output_finished or process.poll() is None:
                try:
                    line = output.get(timeout=0.1)
                except Empty:
                    continue
                if line is None:
                    output_finished = True
                elif _should_show_output_line(line):
                    _print_output_line(console, line)
            exit_code = process.wait()
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