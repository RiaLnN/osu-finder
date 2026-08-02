"""
osu_finder — engine for automated osu! beatmap search, local PP/SR analysis,
and profile-based preset generation.

    config.py           ConfigManager: global config + presets/*.yaml
    local_cache.py       LocalCache: dedup against the local Songs folder
    api_client.py         OsuApiClient: osu! API v2 (OAuth2)
    pp_analyzer.py          PpAnalyzer: local PP/SR/AR/CS/OD via rosu-pp-py
    downloader.py             Downloader: fetch .osz + open it in the OS
    profile_analyzer.py        ProfileAnalyzer: build a preset from a user's top plays
    models.py                    DiffAnalysis / BeatmapCandidate
    cli.py                         command-line entry point (`osu-finder`)
"""

from .config import AppConfig, ConfigManager
from .local_cache import LocalCache
from .api_client import OsuApiClient
from .pp_analyzer import PpAnalyzer
from .downloader import Downloader
from .profile_analyzer import ProfileAnalyzer

__all__ = [
    "AppConfig",
    "ConfigManager",
    "LocalCache",
    "OsuApiClient",
    "PpAnalyzer",
    "Downloader",
    "ProfileAnalyzer",
]

__version__ = "0.1.0"