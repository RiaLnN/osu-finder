"""Data models passed between pipeline stages."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DiffAnalysis:
    """Result of a local rosu-pp-py calculation for one difficulty + one mod combo.

    All stat fields (ar/cs/od/hp/bpm/length) are already mod-adjusted — they
    reflect what the map actually plays like with `mods` applied, not the
    nomod (base) values.
    """

    beatmap_id: int
    version: str
    mods: list[str]
    star_rating: float
    aim_strain: float
    speed_strain: float
    pp: float
    clock_rate: float
    bpm: float
    length_seconds: float
    ar: float
    cs: float
    od: float
    hp: float
    playstyle: str  # "jump" | "stream" | "hybrid"

    @property
    def mods_label(self) -> str:
        return "".join(self.mods) if self.mods else "NM"


@dataclass
class BeatmapCandidate:
    """A beatmapset that passed filtering — a candidate for download."""

    beatmapset_id: int
    artist: str
    title: str
    creator: str
    status: str
    matched_diffs: list[DiffAnalysis]

    @property
    def best_match(self) -> DiffAnalysis:
        """Highest-PP difficulty/mod combo among the matches — used for the
        one-line console summary."""
        return max(self.matched_diffs, key=lambda d: d.pp)