"""
PpAnalyzer — local difficulty/PP calculation via rosu-pp-py, so we never need
osu! API's server-side /attributes endpoints (saves rate-limit budget).

Pipeline: download one lightweight .osu file per difficulty from a mirror ->
parse into rosu_pp_py.Beatmap -> for each mod combo, compute stars/aim/speed
(Difficulty), pp (Performance), and mod-adjusted ar/cs/od/hp/clock_rate
(BeatmapAttributesBuilder — this correctly handles HR/EZ's stat changes too,
not just DT/HT's clock scaling, so it replaces any hand-rolled AR-scaling math).

Verified against rosu-pp-py 4.0.2:
- `Beatmap(content=<str>)` is the reliable constructor; `bytes=<bytearray>`
  currently raises a spurious TypeError in this version.
- `mods=None` raises a TypeError from the Rust binding despite the type stub
  claiming `GameMods | None` — always pass a list (`[]` for nomod).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import aiohttp
import rosu_pp_py as rosu

from .config import MirrorConfig, NetworkConfig
from .models import DiffAnalysis

logger = logging.getLogger("osu_finder.pp_analyzer")


class PpAnalyzerError(Exception):
    pass


class PpAnalyzer:
    def __init__(self, mirror: MirrorConfig, network: NetworkConfig):
        self._mirror = mirror
        self._network = network

    # ------------------------------------------------------------------ #
    #  Fetching .osu file
    # ------------------------------------------------------------------ #

    async def fetch_osu_file(self, session: aiohttp.ClientSession, beatmap_id: int) -> str:
        """Downloads one difficulty's .osu file, via proxy first if configured."""
        path = self._mirror.osu_file_path.format(id=beatmap_id)
        url = f"{self._mirror.base_url}{path}"

        if self._network.proxy_url:
            try:
                async with session.get(url, proxy=self._network.proxy_url) as resp:
                    if resp.status == 200:
                        raw = await resp.read()
                        return raw.decode("utf-8-sig", errors="replace")
                    logger.debug("Proxy returned %d for .osu id=%s, falling back.", resp.status, beatmap_id)
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                logger.debug("Proxy error for .osu id=%s: %s, falling back.", beatmap_id, exc)

            if not self._network.fallback_to_direct:
                raise PpAnalyzerError(f"Proxy failed downloading .osu (id={beatmap_id}), fallback disabled")

        async with session.get(url) as resp:
            if resp.status != 200:
                raise PpAnalyzerError(f"Mirror returned {resp.status} for .osu (id={beatmap_id})")
            raw = await resp.read()
        return raw.decode("utf-8-sig", errors="replace")

    # ------------------------------------------------------------------ #
    #  Calculation
    # ------------------------------------------------------------------ #

    def analyze(
        self,
        osu_content: str,
        beatmap_id: int,
        version: str,
        api_bpm: float,
        api_hit_length: float,
        mods: list[str],
        accuracy: float,
        playstyle_threshold: float,
    ) -> Optional[DiffAnalysis]:
        """Returns None for unparseable or `is_suspicious()` maps (rosu-pp-py's
        own heuristic for broken/test maps where PP has no meaning)."""
        try:
            beatmap = rosu.Beatmap(content=osu_content)
        except Exception as exc:  # rosu_pp_py raises its own ParseError variants
            logger.warning("Failed to parse .osu file (id=%s): %s", beatmap_id, exc)
            return None

        if beatmap.is_suspicious():
            logger.debug("Beatmap id=%s flagged as suspicious, skipping.", beatmap_id)
            return None

        mods_arg = [str(m).upper() for m in mods if str(m).upper() != "NM"]

        try:
            diff_attrs = rosu.Difficulty(mods=mods_arg).calculate(beatmap)
            perf_attrs = rosu.Performance(mods=mods_arg, accuracy=accuracy).calculate(diff_attrs)

            attr_builder = rosu.BeatmapAttributesBuilder(mods=mods_arg)
            attr_builder.set_map(beatmap)
            mod_attrs = attr_builder.build()

            # The map's official/nomod star rating — what osu!'s own client and
            # website show for this difficulty. `star_rating` below is
            # mod-adjusted (matches `mods`) and is what matched the filters,
            # but it won't match what you see when you open the map without
            # applying that mod, which makes the map hard to recognize later.
            # Keep both: this is cheap since `beatmap` is already parsed.
            nomod_stars = diff_attrs.stars if not mods_arg else rosu.Difficulty(mods=[]).calculate(beatmap).stars
        except Exception as exc:
            logger.error("rosu-pp-py calculation failed for id=%s: %s", beatmap_id, exc)
            return None

        aim = diff_attrs.aim or 0.0
        speed = diff_attrs.speed or 0.0

        return DiffAnalysis(
            beatmap_id=beatmap_id,
            version=version,
            mods=list(mods),
            star_rating=diff_attrs.stars,
            nomod_star_rating=nomod_stars,
            aim_strain=aim,
            speed_strain=speed,
            pp=perf_attrs.pp,
            clock_rate=mod_attrs.clock_rate,
            bpm=api_bpm * mod_attrs.clock_rate,
            length_seconds=api_hit_length / mod_attrs.clock_rate,
            ar=mod_attrs.ar,
            cs=mod_attrs.cs,
            od=mod_attrs.od,
            hp=mod_attrs.hp,
            playstyle=self._classify_playstyle(aim, speed, playstyle_threshold),
        )

    @staticmethod
    def estimate_ar(base_ar: float, mods: list[str]) -> float:
        """Cheap AR estimate from the API's nomod value, without downloading
        or parsing the .osu file — used as a pre-filter in main.py to skip
        obviously-non-matching difficulties before spending a download on them."""
        mods_arg = [str(m).upper() for m in mods if str(m).upper() != "NM"]
        return rosu.BeatmapAttributesBuilder(mods=mods_arg, ar=base_ar).build().ar

    @staticmethod
    def _classify_playstyle(aim: float, speed: float, threshold: float) -> str:
        """ratio = speed_strain / aim_strain:
        ratio >= threshold   -> "stream" (Speed dominates)
        ratio <= 1/threshold -> "jump"   (Aim dominates)
        otherwise            -> "hybrid"
        """
        if aim <= 0 and speed <= 0:
            return "hybrid"
        if aim <= 0:
            return "stream"
        ratio = speed / aim
        if ratio >= threshold:
            return "stream"
        if ratio <= 1 / threshold:
            return "jump"
        return "hybrid"