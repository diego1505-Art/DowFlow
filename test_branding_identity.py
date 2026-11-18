"""Regression checks for DowFlow branding and user-visible external links."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class BrandingIdentityTests(unittest.TestCase):
    def test_electron_identity_uses_dowflow_product_name_and_icon(self) -> None:
        package = json.loads((ROOT / "desktop/electron/package.json").read_text(encoding="utf-8"))
        main_source = (ROOT / "desktop/electron/main.cjs").read_text(encoding="utf-8")

        self.assertEqual(package.get("productName"), "DowFlow")
        self.assertIn('const APP_NAME = "DowFlow";', main_source)
        self.assertIn("app.setName(APP_NAME);", main_source)
        self.assertIn('const WINDOWS_APP_ID = "DowFlow.DowFlow";', main_source)
        self.assertIn("app.setAppUserModelId(WINDOWS_APP_ID)", main_source)
        self.assertIn('path.join(PROJECT_ROOT, "static", "dowflow.ico")', main_source)
        self.assertTrue((ROOT / "static/dowflow.ico").is_file())

    def test_video_footers_keep_attribution_without_external_documentation_links(self) -> None:
        for relative_path in ("templates/menu.html", "templates/download.html"):
            with self.subTest(template=relative_path):
                contents = (ROOT / relative_path).read_text(encoding="utf-8")
                self.assertIn("Powered by yt-dlp", contents)
                self.assertNotRegex(contents, re.compile(r'href\s*=\s*["\']https?://', re.IGNORECASE))

    def test_electron_has_no_discord_or_auto_updater_dependency(self) -> None:
        package = json.loads((ROOT / "desktop/electron/package.json").read_text(encoding="utf-8"))
        dependencies = set(package.get("dependencies", {})) | set(package.get("devDependencies", {}))
        self.assertFalse(any(re.search(r"discord|electron-updater|auto.?updater", name, re.IGNORECASE) for name in dependencies))


if __name__ == "__main__":
    unittest.main()
