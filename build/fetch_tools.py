"""Prepare the native tools bundled with the DowFlow installers.

The download is cached in build/tools, so rebuilding an edition does not
download FFmpeg, Node, Chromium and the WebView2 bootstrapper again.

Usage:
    python build/fetch_tools.py [--force]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from build_export import prepare_tools  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Delete build/tools and download everything again.")
    args = parser.parse_args()
    try:
        tools = prepare_tools(
            ROOT,
            force=args.force,
            progress_callback=lambda percent, stage: print(f"{percent:3d}%  {stage}", flush=True),
        )
    except Exception as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1
    print(f"Tools ready in {tools}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
