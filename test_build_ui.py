"""Tests for the build menu banner and the progress line placed under it."""
import io
import time
import unittest

import build_progress
import build_ui


class FakeConsole:
    """Minimal console: only what Flow needs."""

    def __init__(self) -> None:
        self.out = io.StringIO()
        self.subtitles: list[str] = []

    def write(self, text: str = "") -> None:
        self.out.write(text)

    def banner(self, tick: int, subtitle: str) -> list[str]:
        self.subtitles.append(subtitle)
        return ["wave", f"title {subtitle}", "wave"]

    def drawn(self) -> int:
        return self.out.getvalue().count("title")


class FakeTty:
    """A tty-looking stream for BuildDisplay."""

    def __init__(self) -> None:
        self.out = io.StringIO()

    def isatty(self) -> bool:
        return True

    def write(self, text: str) -> None:
        self.out.write(text)

    def flush(self) -> None:
        pass


class FlowTests(unittest.TestCase):
    def test_banner_shows_the_build_mode(self) -> None:
        console = FakeConsole()
        flow = build_ui.Flow(console, build_ui.BASE_SUBTITLE)
        flow.start()
        flow.subtitle = f"{build_ui.BASE_SUBTITLE} · à blanc"
        flow.draw()
        flow.stop()
        self.assertIn("· à blanc", console.out.getvalue())

    def test_pause_freezes_the_banner(self) -> None:
        console = FakeConsole()
        flow = build_ui.Flow(console, "PyInstaller")
        flow.start()
        time.sleep(build_ui.FLOW_INTERVAL * 3)
        flow.pause()
        frozen = console.drawn()
        time.sleep(build_ui.FLOW_INTERVAL * 4)
        self.assertEqual(console.drawn(), frozen, "a paused banner must stop drawing")
        flow.stop()


class BuildDisplayRowTests(unittest.TestCase):
    def test_progress_is_pinned_below_the_banner(self) -> None:
        stream = FakeTty()
        display = build_progress.BuildDisplay(
            "video", "DowFlow-Video", stream=stream, top_row=8
        )
        display.start()
        self.assertNotIn(
            "DOWFLOW BUILD", stream.out.getvalue(), "the menu owns the banner"
        )
        display.render()
        self.assertIn("\x1b[8;1H", stream.out.getvalue())
        display.stop(True)


if __name__ == "__main__":
    unittest.main()
