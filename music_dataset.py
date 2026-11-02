"""
DowFlow — Integration point for an optional local music dataset.

Import a local catalog (for example, a SQLite database) here to provide
search results and cover art offline.

Until a dataset is available, `get_dataset()` returns `None` and the music
service (`music.py`) uses YouTube and the Deezer API only. To add a dataset,
expose its path through the `DOWFLOW_MUSIC_DATASET` environment variable
(SQLite database) and return a `MusicDataset` instance from `get_dataset()`.
"""
from __future__ import annotations

import os
from typing import Any

DATASET_ENV_VAR = "DOWFLOW_MUSIC_DATASET"


class MusicDataset:
    """Interface for a local music catalog (implementation to be provided)."""

    def available(self) -> bool:
        """Return True if the catalog is readable."""
        return False

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search for tracks: [{title, artist, album, cover_url, ...}]."""
        raise NotImplementedError

    def popular(self, limit: int = 24) -> list[dict[str, Any]]:
        """Return a selection of popular tracks."""
        raise NotImplementedError

    def cover_url(self, artist: str, title: str) -> str | None:
        """Return the album cover URL for a track, or None."""
        return None


def get_dataset() -> MusicDataset | None:
    """Return the local dataset if available, otherwise None.

    See the module docstring for instructions on adding an implementation.
    """
    dataset_path = os.environ.get(DATASET_ENV_VAR, "").strip()
    if not dataset_path or not os.path.isfile(dataset_path):
        return None
    # No implementation is available yet: the file is detected but cannot be
    # queried. Returning None preserves the YouTube + Deezer behavior.
    return None
