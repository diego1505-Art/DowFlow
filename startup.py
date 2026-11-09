"""DowFlow's animated terminal startup screen and Flask launcher."""

import codecs
import io
import json
import os
import re
import socket
import subprocess
import sys
import time
from collections import deque
from queue import Empty, Queue
from pathlib import Path
from threading import Event, Thread
from typing import BinaryIO
from urllib.request import urlopen

from config import SUBPROCESS_CREATION_FLAGS, get_data_root
from rich.align import Align
from rich.box import ROUNDED
from rich.console import Console, Group
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

STARTUP_PANEL_HEIGHT = 18
NETWORK_LOG_CAPTURE_TIMEOUT_SECONDS = 20.0
APP_VERSION = "V15"
_LOG_ENTRY_RE = re.compile(
    r"^(?P<time>\d{2}:\d{2}:\d{2})\s*\|\s*(?P<level>[A-Z]+)\s*\|\s*"
    r"(?P<logger>[^|]+?)\s*\|\s*(?P<message>.*)$"
)
_FILE_LOG_ENTRY_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}\s+(?P<time>\d{2}:\d{2}:\d{2})\s*\|\s*"
    r"(?P<level>[A-Z]+)\s*\|\s*(?P<logger>[^|]+?)\s*\|\s*\d+\s*\|\s*\d+\s*\|\s*(?P<message>.*)$"
)
_HTTP_ACCESS_RE = re.compile(
    r'^(?P<ip>.+?)\s+-\s+-\s+\[(?P<date>[^\]]+)\]\s+"'
    r'(?P<method>[A-Z]+)\s+(?P<path>.*?)\s+HTTP/(?P<version>[\d.]+)"\s+'
    r'(?P<status>\d{3})\s+(?P<size>\S+)$'
)
_ANSI_ESCAPE_RE = re.compile(r"\033\[[0-9;]*m")
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


def _is_dowflow_server(host: str, port: int) -> bool:
    """Return True only for a live DowFlow instance running the current build."""
    try:
        with urlopen(f"http://{host}:{port}/api/status", timeout=0.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not (
            response.status == 200
            and isinstance(payload, dict)
            and payload.get("ready") is True
            and payload.get("service") == "DowFlow"
        ):
            return False
        from config import get_runtime_build_id

        return payload.get("build_id") == get_runtime_build_id()
    except (OSError, ValueError, TimeoutError):
        return False


def _next_available_port(host: str, port: int, attempts: int = 20) -> int | None:
    final_port = min(65535, port + attempts)
    for candidate in range(port + 1, final_port + 1):
        if not _port_is_open(host, candidate):
            return candidate
    return None


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
            creationflags=SUBPROCESS_CREATION_FLAGS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return next((line.strip() for line in result.stdout.splitlines() if line.strip()), None)


def _startup_version_text() -> str:
    node_version = _version_line("node")
    details: list[str] = [f"DowFlow {APP_VERSION}", "yt-dlp native fragments"]
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

        download_match = _YTDLP_PROGRESS_RE.match(message)
        if download_match:
            text.append("[download] ", style="bold bright_cyan")
            text.append(download_match["percent"], style="bold bright_cyan")
            text.append(" of ", style="dim")
            text.append(download_match["details"], style="white")
            return text

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


def _stream_output(console: Console, output: Queue[str | None]) -> None:
    while True:
        line = output.get()
        if line is None:
            return
        if _is_redundant_server_line(line):
            continue
        _print_output_line(console, line)


def _network_detection_log_kind(line: str) -> str | None:
    match = _LOG_ENTRY_RE.match(Text.from_ansi(line).plain.strip())
    if not match:
        return None
    logger = match["logger"].strip()
    message = match["message"]
    if logger == "app" and message.startswith(("Network speed detected:", "Network speed unavailable")):
        return "network_speed"
    if logger == "playlist" and message.startswith("[perf] Connection tier:"):
        return "connection_tier"
    return None


def _is_redundant_server_line(line: str) -> bool:
    plain = _ANSI_ESCAPE_RE.sub("", Text.from_ansi(line).plain).strip()
    if plain.startswith("* Running on http://"):
        return True
    match = _LOG_ENTRY_RE.match(plain)
    logger = match["logger"].strip() if match else "werkzeug"
    message = match["message"].strip() if match else plain
    if logger != "werkzeug":
        return False
    if message.lower().startswith(("* running on http://", "press ctrl+c to quit")):
        return True
    return _HTTP_ACCESS_RE.match(message) is not None


def _format_file_log_line(line: str) -> str | None:
    match = _FILE_LOG_ENTRY_RE.match(line.strip())
    if not match:
        return None
    return (
        f"{match['time']} | {match['level']} | {match['logger'].strip()} | "
        f"{match['message']}"
    )


def _is_startup_file_log(line: str) -> bool:
    match = _LOG_ENTRY_RE.match(line)
    if not match:
        plain = Text.from_ansi(line).plain.strip()
        return plain.startswith(("* Serving Flask app", "* Debug mode:"))
    logger = match["logger"].strip()
    message = match["message"]
    if logger == "app":
        return message.startswith((
            "DowFlow — Multi-Site Media Downloader",
            "Measuring network speed",
            "Server started at ",
            "Press Ctrl+C to stop",
            "Network speed detected:",
            "Network speed unavailable",
        ))
    if logger == "playlist":
        return message.startswith("[perf] Connection tier:")
    return logger == "werkzeug" and message.startswith((
        "WARNING: This is a development server",
        "* Serving Flask app",
        "* Debug mode:",
        "* Running on http://",
        "Press CTRL+C to quit",
    ))


def _read_existing_server_logs(log_path: Path) -> tuple[list[str], int]:
    try:
        with log_path.open("r", encoding="utf-8", errors="replace") as handle:
            file_size = handle.seek(0, os.SEEK_END)
            start_offset = max(0, file_size - 512 * 1024)
            handle.seek(start_offset)
            if start_offset:
                handle.readline()
            raw_lines = handle.readlines()
            offset = handle.tell()
    except OSError:
        return [], 0

    formatted = [
        _format_file_log_line(line) or line.rstrip("\r\n")
        for line in raw_lines
    ]
    start_index = next(
        (
            index
            for index in range(len(formatted) - 1, -1, -1)
            if (match := _LOG_ENTRY_RE.match(formatted[index]))
            and match["logger"].strip() == "app"
            and match["message"].startswith("DowFlow — Multi-Site Media Downloader")
        ),
        None,
    )
    if start_index is None:
        start_index = next(
            (
                index
                for index in range(len(formatted) - 1, -1, -1)
                if (match := _LOG_ENTRY_RE.match(formatted[index]))
                and match["logger"].strip() == "app"
                and match["message"].startswith("Server started at ")
            ),
            max(0, len(formatted) - 30),
        )
    lines = [
        line for line in formatted[start_index:]
        if _is_startup_file_log(line) and not _is_redundant_server_line(line)
    ]
    return lines, offset


def _read_appended_server_logs(log_path: Path, offset: int) -> tuple[list[str], int]:
    try:
        with log_path.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(offset)
            appended = handle.readlines()
            next_offset = handle.tell()
    except OSError:
        return [], offset
    lines = []
    for raw_line in appended:
        line = _format_file_log_line(raw_line) or raw_line.rstrip("\r\n")
        if _is_startup_file_log(line) and not _is_redundant_server_line(line):
            lines.append(line)
    return lines, next_offset


def _read_appended_runtime_logs(log_path: Path, offset: int) -> tuple[list[str], int]:
    try:
        with log_path.open("r", encoding="utf-8", errors="replace") as handle:
            if handle.seek(0, os.SEEK_END) < offset:
                offset = 0
            handle.seek(offset)
            appended = handle.readlines()
            next_offset = handle.tell()
    except OSError:
        return [], offset
    lines = []
    for raw_line in appended:
        line = _format_file_log_line(raw_line) or raw_line.rstrip("\r\n")
        if not _is_redundant_server_line(line):
            lines.append(line)
    return lines, next_offset


def _stream_existing_server_logs(
    log_path: Path,
    offset: int,
    console: Console,
    stop_event: Event,
) -> None:
    while not stop_event.wait(0.2):
        appended, offset = _read_appended_runtime_logs(log_path, offset)
        for line in appended:
            _print_output_line(console, line)


def _drain_startup_output(
    output: Queue[str | None],
    log_lines: deque[str],
    network_log_kinds: set[str],
) -> bool:
    finished = False
    while True:
        try:
            item = output.get_nowait()
        except Empty:
            return finished
        if item is None:
            finished = True
            continue
        if _is_redundant_server_line(item):
            continue
        log_kind = _network_detection_log_kind(item)
        if log_kind:
            network_log_kinds.add(log_kind)
        log_lines.append(item)


def _logs_panel(lines: deque[str]) -> Panel:
    visible_lines = list(lines)
    if not visible_lines:
        visible_lines = ["Waiting for startup logs..."]
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
    layout["logs"].update(_logs_panel(lines))


def _startup_capture_complete(
    ready: bool,
    frozen: bool,
    network_log_kinds: set[str],
    now: float,
    deadline: float | None,
) -> bool:
    if not ready:
        return False
    if frozen or network_log_kinds == {"network_speed", "connection_tier"}:
        return True
    return deadline is not None and now >= deadline


def _ensure_portable_download_folder() -> bool:
    if not getattr(sys, "frozen", False):
        return True

    from config import get_download_path, set_download_path
    from folder_picker import select_download_folder

    current_path = get_download_path(required=False)
    if current_path is not None and current_path.is_dir():
        from config import configure_runtime_paths

        configure_runtime_paths(current_path)
        return True
    selected = select_download_folder(
        str(current_path) if current_path and current_path.is_dir() else None
    )
    if not selected:
        return False
    set_download_path(selected)
    return True


def _run_webview_session(
    console: Console,
    url: str,
    process,
    output_reader: Thread | None,
    output: Queue[str | None],
    existing_server: bool,
    existing_log_path: Path,
    existing_log_offset: int | None,
) -> int:
    if process is not None and process.poll() is not None:
        return process.returncode or 0

    output_streamer: Thread | None = None
    existing_log_streamer: Thread | None = None
    stream_stop = Event()
    try:
        if process is not None and output_reader is not None:
            output_streamer = Thread(
                target=_stream_output,
                args=(console, output),
                name="dowflow-live-logs",
                daemon=True,
            )
            output_streamer.start()
        elif existing_server and existing_log_offset is not None:
            existing_log_streamer = Thread(
                target=_stream_existing_server_logs,
                args=(existing_log_path, existing_log_offset, console, stream_stop),
                name="dowflow-file-logs",
                daemon=True,
            )
            existing_log_streamer.start()

        import webview

        bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        icon_path = bundle_root / "static" / "dowflow.ico"
        webview.create_window(
            "DowFlow",
            url,
            width=1280,
            height=860,
            min_size=(900, 600),
            icon=str(icon_path) if icon_path.is_file() else None,
        )
        webview.start()
        return 0
    except Exception as error:
        log.error("Could not open the native application window: %s", error, exc_info=True)
        return 1
    finally:
        stream_stop.set()
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if output_reader is not None:
            output_reader.join(timeout=2)
        if output_streamer is not None:
            output_streamer.join(timeout=2)
        if existing_log_streamer is not None:
            existing_log_streamer.join(timeout=2)


def main() -> int:
    console = Console(file=sys.stdout or io.StringIO())
    if not _ensure_portable_download_folder():
        return 0
    host = os.environ.get("DOWFLOW_HOST", "127.0.0.1")
    port = int(os.environ.get("DOWFLOW_PORT", "5001"))
    probe_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    url_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    url = f"http://{url_host}:{port}"
    process = None
    output: Queue[str | None] = Queue()
    output_reader: Thread | None = None
    failure = None
    existing_server = False
    port_notice: str | None = None

    if _port_is_open(probe_host, port):
        if _is_dowflow_server(probe_host, port):
            existing_server = True
            port_notice = "Connected to the existing DowFlow server"
        else:
            available_port = _next_available_port(probe_host, port)
            if available_port is None:
                failure = f"Ports {port} through {min(65535, port + 20)} are already in use."
            else:
                stale_notice = (
                    f"Outdated or busy DowFlow on port {port}; "
                    f"starting a fresh server at http://{url_host}:{available_port}"
                )
                port = available_port
                url = f"http://{url_host}:{port}"
                port_notice = stale_notice

    if failure is None and not existing_server:
        try:
            capture_output = not getattr(sys, "frozen", False)
            server_args = (
                [sys.executable, "--server"]
                if getattr(sys, "frozen", False)
                else [sys.executable, str(Path(__file__).with_name("app.py"))]
            )
            process = subprocess.Popen(
                server_args,
                stdout=subprocess.PIPE if capture_output else subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
                bufsize=0,
                creationflags=SUBPROCESS_CREATION_FLAGS,
                env={**os.environ, "DOWFLOW_PORT": str(port)},
            )
            if process.stdout is not None:
                output_reader = Thread(
                    target=_capture_output,
                    args=(process.stdout, output),
                    daemon=True,
                )
                output_reader.start()
        except OSError as error:
            failure = f"Could not start Flask: {error}"

    startup_timeout = 1800 if getattr(sys, "frozen", False) else 10
    deadline = time.monotonic() + startup_timeout
    frame_number = 0
    ready = existing_server
    output_finished = False
    exit_code = 1
    version_text = _startup_version_text() if existing_server else ""
    network_log_kinds: set[str] = set()
    network_log_deadline: float | None = (
        time.monotonic() + NETWORK_LOG_CAPTURE_TIMEOUT_SECONDS
        if existing_server else None
    )
    log_lines: deque[str] = deque(["Starting DowFlow server..."])
    if port_notice:
        log_lines.append(port_notice)
    existing_log_path = get_data_root() / "logs" / "dowflow.log"
    existing_log_offset: int | None = None
    if existing_server:
        existing_lines, existing_log_offset = _read_existing_server_logs(existing_log_path)
        log_lines.extend(existing_lines)
        for line in existing_lines:
            log_kind = _network_detection_log_kind(line)
            if log_kind:
                network_log_kinds.add(log_kind)
        if not existing_lines:
            log_lines.append("Waiting for the existing server's startup logs...")

    layout = Layout()
    layout.split_column(
        Layout(name="startup", size=STARTUP_PANEL_HEIGHT),
        Layout(name="logs", ratio=1, minimum_size=4),
    )
    _update_dashboard(layout, console, frame_number, log_lines)
    try:
        with Live(layout, console=console, refresh_per_second=8, transient=False):
            while True:
                output_finished = _drain_startup_output(
                    output,
                    log_lines,
                    network_log_kinds,
                ) or output_finished
                if existing_server and existing_log_offset is not None:
                    appended_lines, existing_log_offset = _read_appended_server_logs(
                        existing_log_path,
                        existing_log_offset,
                    )
                    log_lines.extend(appended_lines)
                    for line in appended_lines:
                        log_kind = _network_detection_log_kind(line)
                        if log_kind:
                            network_log_kinds.add(log_kind)

                if not ready and failure is None:
                    if process is not None and _port_is_open(probe_host, port):
                        ready = True
                        network_log_deadline = time.monotonic() + NETWORK_LOG_CAPTURE_TIMEOUT_SECONDS
                        version_text = _startup_version_text()
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
                    output_finished = _drain_startup_output(
                        output,
                        log_lines,
                        network_log_kinds,
                    ) or output_finished
                    log_lines.extend((failure, "See the logs folder for details."))
                    _update_dashboard(layout, console, frame_number, log_lines, failed=True)
                    break

                if ready and process is not None and process.poll() is not None:
                    if output_reader is not None:
                        output_reader.join(timeout=2)
                    output_finished = _drain_startup_output(
                        output,
                        log_lines,
                        network_log_kinds,
                    ) or output_finished
                    exit_code = process.returncode or 0
                    log_lines.append(f"Server process exited with code {exit_code}.")
                    _update_dashboard(
                        layout,
                        console,
                        frame_number,
                        log_lines,
                        complete=exit_code == 0,
                        failed=exit_code != 0,
                        version_text=version_text,
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
                if _startup_capture_complete(
                    ready,
                    getattr(sys, "frozen", False),
                    network_log_kinds,
                    time.monotonic(),
                    network_log_deadline,
                ):
                    break
                frame_number += 1
                time.sleep(0.125)

        if ready:
            exit_code = _run_webview_session(
                console,
                url,
                process,
                output_reader,
                output,
                existing_server,
                existing_log_path,
                existing_log_offset,
            )
    except KeyboardInterrupt:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait()
        if output_reader is not None:
            output_reader.join(timeout=2)
        return 0

    return exit_code

if __name__ == "__main__":
    if getattr(sys, "frozen", False) and "--choose-folder" in sys.argv:
        from folder_picker import main as folder_picker_main

        raise SystemExit(folder_picker_main(sys.argv[2:]))
    if getattr(sys, "frozen", False) and "--server" in sys.argv:
        from app import run_server

        run_server()
    else:
        main()
