"""ProfileAnalyzer — derives a search preset from a user's top plays.

Focus modes: balanced, stream, jump, push, farm.
"""

from __future__ import annotations

import asyncio
import logging
import statistics
from dataclasses import dataclass
from typing import Any, Optional

import aiohttp

from .api_client import OsuApiClient
from .config import RangeFilter
from .pp_analyzer import PpAnalyzer, PpAnalyzerError

logger = logging.getLogger("osu_finder.profile_analyzer")


@dataclass
class AutoProfile:
    target_pp_min: float
    target_pp_max: float
    star_min: float
    star_max: float
    favored_playstyle: str
    preferred_mods: list[list[str]]
    ar_min: Optional[float] = None
    ar_max: Optional[float] = None
    target_length_min: Optional[float] = None
    target_length_max: Optional[float] = None


class ProfileAnalyzer:
    def __init__(self, api_client: OsuApiClient, pp_analyzer: PpAnalyzer):
        self.api = api_client
        self.pp_analyzer = pp_analyzer

    async def analyze_user(
        self,
        session: aiohttp.ClientSession,
        user: str,
        limit: int = 100,
        focus: str = "balanced",
        mode: str = "osu",
    ) -> AutoProfile:
        user_str = str(user).strip()
        user_id = int(user_str) if user_str.isdigit() else await self.api.get_user_id_by_username(user_str)

        scores = await self.api.get_user_best_scores(user_id, mode=mode, limit=limit)
        if not scores:
            raise ValueError(f"No scores found for user {user}.")

        logger.info("Analyzing %d top plays for focus '%s'...", len(scores), focus)

        analyzed_plays: list[dict[str, Any]] = []
        mods_freq: dict[tuple[str, ...], int] = {}

        for score in scores:
            beatmap = score.get("beatmap")
            if not isinstance(beatmap, dict):
                continue
            beatmap_id = beatmap.get("id")
            if not beatmap_id:
                continue

            mods = self._extract_mods(score.get("mods", []))
            mods_freq[tuple(sorted(mods))] = mods_freq.get(tuple(sorted(mods)), 0) + 1

            pp = score.get("pp")
            if pp is None:
                continue

            raw_acc = score.get("accuracy", 1.0)
            accuracy = raw_acc * 100.0 if raw_acc <= 1.0 else raw_acc

            try:
                osu_content = await self.pp_analyzer.fetch_osu_file(session, beatmap_id)
            except PpAnalyzerError:
                continue
            await asyncio.sleep(0.3)

            analysis = self.pp_analyzer.analyze(
                osu_content=osu_content,
                beatmap_id=beatmap_id,
                version=str(beatmap.get("version", "")),
                api_bpm=float(beatmap.get("bpm", 0.0)),
                api_hit_length=float(beatmap.get("hit_length", 0.0)),
                mods=mods,
                accuracy=accuracy,
                playstyle_threshold=1.15,
            )
            if analysis:
                analyzed_plays.append({"pp": float(pp), "analysis": analysis})

        if not analyzed_plays:
            raise ValueError("Could not analyze any beatmap from top plays.")

        best_mods = list(max(mods_freq.items(), key=lambda x: x[1])[0]) if mods_freq else []
        best_mods = best_mods or ["NM"]

        return self._build_profile(analyzed_plays, best_mods, focus)

    @staticmethod
    def _extract_mods(raw_mods: list) -> list[str]:
        mods: list[str] = []
        for m in raw_mods:
            if isinstance(m, dict) and "acronym" in m:
                mods.append(str(m["acronym"]))
            elif isinstance(m, str):
                mods.append(m)
        return mods

    def _build_profile(self, plays: list[dict], best_mods: list[str], focus: str) -> AutoProfile:
        all_pps = [p["pp"] for p in plays]
        all_stars = [p["analysis"].star_rating for p in plays]
        all_ars = [p["analysis"].ar for p in plays]

        avg_pp = statistics.median(all_pps)
        avg_star = statistics.median(all_stars)
        median_ar = round(statistics.median(all_ars), 1)
        ar_min = max(0.0, median_ar - 0.3)
        ar_max = min(11.0, median_ar + 0.6)

        def profile(**kwargs) -> AutoProfile:
            return AutoProfile(preferred_mods=[best_mods], ar_min=ar_min, ar_max=ar_max, **kwargs)

        if focus == "stream":
            pool = [p for p in plays if p["analysis"].playstyle == "stream"]
            pps = [p["pp"] for p in pool] if pool else all_pps
            stars = [p["analysis"].star_rating for p in pool] if pool else all_stars
            scale = (0.9, 1.2) if pool else (0.7, 0.95)
            star_pad = (-0.1, 0.3) if pool else (-0.15 * avg_star, -0.05 * avg_star)
            return profile(
                target_pp_min=round(statistics.median(pps) * scale[0], 1),
                target_pp_max=round(statistics.median(pps) * scale[1], 1),
                star_min=round(statistics.median(stars) + star_pad[0], 2),
                star_max=round(statistics.median(stars) + star_pad[1], 2),
                favored_playstyle="stream",
                target_length_min=90.0,  # streams are better practiced on longer maps
                target_length_max=None,
            )

        if focus == "jump":
            pool = [p for p in plays if p["analysis"].playstyle == "jump"]
            pps = [p["pp"] for p in pool] if pool else all_pps
            stars = [p["analysis"].star_rating for p in pool] if pool else all_stars
            scale = (0.9, 1.25) if pool else (0.85, 1.15)
            star_pad = (-0.1, 0.35) if pool else (-0.1 * avg_star, 0.1 * avg_star)
            return profile(
                target_pp_min=round(statistics.median(pps) * scale[0], 1),
                target_pp_max=round(statistics.median(pps) * scale[1], 1),
                star_min=round(statistics.median(stars) + star_pad[0], 2),
                star_max=round(statistics.median(stars) + star_pad[1], 2),
                favored_playstyle="jump",
            )

        if focus == "push":
            # Top 10% of plays by PP/stars — chase a rank-up, not comfort farm.
            sorted_pps = sorted(all_pps)
            sorted_stars = sorted(all_stars)
            idx = int(len(sorted_pps) * 0.9)
            push_pp = sorted_pps[idx] if len(sorted_pps) >= 10 else max(all_pps)
            push_star = sorted_stars[idx] if len(sorted_stars) >= 10 else max(all_stars)
            return profile(
                target_pp_min=round(push_pp * 0.95, 1),
                target_pp_max=round(push_pp * 1.35, 1),
                star_min=round(push_star - 0.1, 2),
                star_max=round(push_star + 0.5, 2),
                favored_playstyle="any",
            )

        if focus == "farm":
            # TV-size jump maps, top-25th-percentile difficulty.
            pool = [p for p in plays if p["analysis"].playstyle == "jump"] or plays
            pps = sorted(p["pp"] for p in pool)
            stars = [p["analysis"].star_rating for p in pool]
            target_pp = pps[int(len(pps) * 0.75)]
            return AutoProfile(
                preferred_mods=[best_mods], ar_min=ar_min, ar_max=ar_max,
                target_pp_min=round(target_pp * 0.9, 1),
                target_pp_max=round(target_pp * 1.25, 1),
                star_min=round(statistics.median(stars) - 0.1, 2),
                star_max=round(max(stars) + 0.2, 2),
                favored_playstyle="jump",
                target_length_max=140.0,
            )

        # "balanced" (default)
        ratios = [
            p["analysis"].aim_strain / p["analysis"].speed_strain
            for p in plays if p["analysis"].speed_strain > 0 and p["analysis"].aim_strain > 0
        ]
        avg_ratio = statistics.median(ratios) if ratios else 1.0
        style = "jump" if avg_ratio > 1.15 else "stream" if avg_ratio < 0.85 else "hybrid"
        return profile(
            target_pp_min=round(avg_pp * 0.9, 1),
            target_pp_max=round(avg_pp * 1.25, 1),
            star_min=round(avg_star - 0.2, 2),
            star_max=round(avg_star + 0.35, 2),
            favored_playstyle=style,
        )