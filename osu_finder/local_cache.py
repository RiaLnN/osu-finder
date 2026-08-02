"""
LocalCache — scans the local osu!/Songs directory and extracts BeatmapSet IDs
from folder names, so search results can be deduplicated in O(1).

Standard folder naming used by the osu! client:
    "<BeatmapSetID> <Artist> - <Title>"
Example: "1234567 Camellia - Exit This Earth's Atomosphere"
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger("osu_finder.local_cache")

_SET_ID_PATTERN = re.compile(r"^(\d+)\s")


class LocalCache:
    """Set of BeatmapSet IDs to skip: already downloaded locally, or blacklisted."""

    def __init__(self, songs_folder: Path, blacklist: list[int] | None = None):
        self.songs_folder = songs_folder
        self._known_ids: set[int] = set(blacklist or [])

    def build(self) -> "LocalCache":
        """Scans the Songs directory once (non-recursive — beatmap folders are
        always top-level) and populates the ID set."""
        if not self.songs_folder.exists():
            logger.warning(
                "Songs folder not found (%s) — local dedup will not work.",
                self.songs_folder,
            )
            return self

        found = 0
        for entry in self.songs_folder.iterdir():
            if not entry.is_dir():
                continue
            match = _SET_ID_PATTERN.match(entry.name)
            if match:
                self._known_ids.add(int(match.group(1)))
                found += 1

        logger.info("Local cache built: %d map(s) found in %s", found, self.songs_folder)
        return self

    def __contains__(self, beatmapset_id: int) -> bool:
        return beatmapset_id in self._known_ids

    def __len__(self) -> int:
        return len(self._known_ids)

    def add(self, beatmapset_id: int) -> None:
        """Add an ID right after downloading, without rescanning the disk."""
        self._known_ids.add(beatmapset_id)