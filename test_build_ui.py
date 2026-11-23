"""Tests for the build menu banner while a build owns the console."""
import io
import time
import unittest

import build_ui


class FakeConsole:
    """Minimal console: only what Flow needs."""

    def __init__(self) -> None:
        self.out = io.StringIO()

    def write(self, text: str = "") -> None:
        self.out.write(text)

    def banner(self, tick: int, subtitle: str) -> list[str]:
        return ["wave", f"title {subtitle}", "wave"]

    def drawn(self) -> int:
        return self.out.getvalue().count("title")


class FlowTests(unittest.TestCase):
    def test_pause_freezes_the_banner_and_resume_revives_it(self) -> None:
        console = FakeConsole()
        flow = build_ui.Flow(console, "PyInstaller")
        flow.start()
        self.assertIsNotNone(flow._thread)

        time.sleep(build_ui.FLOW_INTERVAL * 3)
        flow.pause()
        frozen = console.drawn()

        time.sleep(build_ui.FLOW_INTERVAL * 4)
        self.assertEqual(console.drawn(), frozen, "a paused banner must stop drawing")

        flow.resume()
        time.sleep(build_ui.FLOW_INTERVAL * 4)
        self.assertGreater(console.drawn(), frozen, "resume must animate again")

        flow.stop()
        self.assertIsNone(flow._thread)
        stopped = console.drawn()
        time.sleep(build_ui.FLOW_INTERVAL * 3)
        self.assertEqual(console.drawn(), stopped, "a stopped banner must stay still")

    def test_resume_after_stop_redraws_once(self) -> None:
        console = FakeConsole()
        flow = build_ui.Flow(console, "PyInstaller")
        flow.start()
        flow.stop()
        before = console.drawn()
        flow.start()
        self.assertGreaterEqual(console.drawn(), before + 1)
        flow.stop()


if __name__ == "__main__":
    unittest.main()
