"""Regression checks for DowFlow branding and user-visible external links."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class BrandingIdentityTests(unittest.TestCase):
    def test_video_footers_keep_attribution_without_external_documentation_links(self) -> None:
        for relative_path in ("templates/menu.html", "templates/download.html"):
            with self.subTest(template=relative_path):
                contents = (ROOT / relative_path).read_text(encoding="utf-8")
                self.assertIn("Powered by yt-dlp", contents)
                self.assertNotRegex(contents, re.compile(r'href\s*=\s*["\']https?://', re.IGNORECASE))


if __name__ == "__main__":
    unittest.main()
