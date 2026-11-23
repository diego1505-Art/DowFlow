"""Tests for the release updater: asset mapping and the update decision.

No test touches the network: ``select_update`` is pure and the download test
uses a small fake session.
"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import build_export
import updater


def _release(published: datetime, assets: list[dict] | None = None) -> dict:
    return {
        "tag_name": "v17",
        "published_at": published.isoformat().replace("+00:00", "Z"),
        "body": "Release notes",
        "assets": assets
        if assets is not None
        else [
            {
                "name": "DowFlow-Setup.exe",
                "browser_download_url": "https://example.com/DowFlow-Setup.exe",
                "size": 123456789,
            }
        ],
    }


class ReleaseAssetTests(unittest.TestCase):
    def test_asset_names_match_the_build_editions(self) -> None:
        for scope, edition in build_export.EDITIONS.items():
            self.assertEqual(
                updater.setup_asset_name(scope),
                f"{edition['setup']}.exe",
                f"{scope} installs a different setup than the one it publishes",
            )

    def test_unknown_scope_falls_back_to_the_menu_setup(self) -> None:
        self.assertEqual(
            updater.setup_asset_name("unknown"), updater.RELEASE_ASSETS["all"]
        )

    def test_find_setup_asset_ignores_other_editions(self) -> None:
        release = _release(
            datetime.now(timezone.utc),
            [
                {
                    "name": "DowFlow-Anime-Setup.exe",
                    "browser_download_url": "https://example.com/anime.exe",
                }
            ],
        )
        self.assertIsNotNone(updater.find_setup_asset(release, "anime"))
        self.assertIsNone(updater.find_setup_asset(release, "video"))


class UpdateDecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.installed = datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()

    def test_newer_release_is_available(self) -> None:
        released = datetime(2026, 2, 1, tzinfo=timezone.utc)
        result = updater.select_update(_release(released), "all", self.installed)
        self.assertTrue(result["available"])
        self.assertEqual(result["version"], "v17")
        self.assertEqual(result["name"], "DowFlow-Setup.exe")
        self.assertEqual(result["url"], "https://example.com/DowFlow-Setup.exe")
        self.assertIsNone(result["error"])

    def test_release_older_than_the_install_is_ignored(self) -> None:
        released = datetime(2025, 12, 1, tzinfo=timezone.utc)
        result = updater.select_update(_release(released), "all", self.installed)
        self.assertFalse(result["available"])
        self.assertIsNone(result["error"])

    def test_same_release_is_not_offered_again(self) -> None:
        same = datetime(2026, 1, 1, tzinfo=timezone.utc)
        result = updater.select_update(_release(same), "all", self.installed)
        self.assertFalse(result["available"])

    def test_missing_asset_explains_itself(self) -> None:
        release = _release(
            datetime(2026, 2, 1, tzinfo=timezone.utc),
            [{"name": "DowFlow-Video-Setup.exe", "browser_download_url": "x"}],
        )
        result = updater.select_update(release, "all", self.installed)
        self.assertFalse(result["available"])
        self.assertIn("DowFlow-Setup.exe", result["error"] or "")

    def test_check_without_an_install_does_not_contact_github(self) -> None:
        result = updater.check_for_update("all", installed_mtime=None)
        # installed_mtime=None asks for the real install; a source checkout has
        # none, so the call stops before any request.
        self.assertFalse(result["available"])
        self.assertIn("installed DowFlow", result["error"] or "")


class _FakeResponse:
    def __init__(self, payload: bytes, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status
        self.headers = {"Content-Length": str(len(payload))}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size: int = 65536):
        for start in range(0, len(self._payload), chunk_size):
            yield self._payload[start : start + chunk_size]

    def close(self) -> None:
        pass


class _FakeSession:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def get(self, *args, **kwargs) -> _FakeResponse:
        return _FakeResponse(self.payload)


class DownloadTests(unittest.TestCase):
    def test_download_writes_the_setup(self) -> None:
        payload = b"MZ" + b"\0" * (updater._MIN_SETUP_BYTES + 8)
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "DowFlow-Setup.exe"
            saved = updater.download_setup(
                "https://example.com/DowFlow-Setup.exe",
                target,
                session=_FakeSession(payload),
            )
            self.assertEqual(saved, target)
            self.assertEqual(target.read_bytes(), payload)
            self.assertFalse(target.with_suffix(".exe.part").exists())

    def test_a_truncated_download_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "DowFlow-Setup.exe"
            with self.assertRaises(RuntimeError):
                updater.download_setup(
                    "https://example.com/DowFlow-Setup.exe",
                    target,
                    session=_FakeSession(b"too small"),
                )
            self.assertFalse(target.exists())


class ReleaseTimestampTests(unittest.TestCase):
    def test_reads_github_timestamps(self) -> None:
        published = datetime(2026, 2, 1, tzinfo=timezone.utc)
        release = _release(published)
        self.assertAlmostEqual(
            updater.release_timestamp(release),
            published.timestamp(),
            delta=1,
        )

    def test_unreadable_timestamp_returns_none(self) -> None:
        self.assertIsNone(updater.release_timestamp({"published_at": "not a date"}))


if __name__ == "__main__":
    unittest.main()
