"""Downloader — fetches full .osz archives from a mirror and (optionally)
opens them via the OS, which triggers beatmap import for an installed osu!
client (double-click behavior on Windows via os.startfile)."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path

import aiohttp

from .config import MirrorConfig, NetworkConfig

logger = logging.getLogger("osu_finder.downloader")


class DownloaderError(Exception):
    pass


class Downloader:
    def __init__(self, mirror: MirrorConfig, download_folder: Path, network: NetworkConfig):
        self._mirror = mirror
        self._download_folder = download_folder
        self._network = network
        self._download_folder.mkdir(parents=True, exist_ok=True)

    async def download_osz(
        self, session: aiohttp.ClientSession, beatmapset_id: int, filename_hint: str
    ) -> Path:
        url = f"{self._mirror.base_url}{self._mirror.osz_download_path.format(id=beatmapset_id)}"
        dest = self._download_folder / f"{beatmapset_id} {self._sanitize_filename(filename_hint)}.osz"

        if self._network.proxy_url:
            try:
                async with session.get(url, proxy=self._network.proxy_url) as resp:
                    if resp.status == 200:
                        dest.write_bytes(await resp.read())
                        logger.info("Downloaded via proxy: %s", dest.name)
                        return dest
                    logger.warning("Proxy returned %d for set %d, falling back to direct.", resp.status, beatmapset_id)
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                logger.warning("Proxy error for set %d: %s, falling back to direct.", beatmapset_id, exc)

            if not self._network.fallback_to_direct:
                raise DownloaderError(f"Proxy failed downloading set {beatmapset_id}, fallback disabled")

        async with session.get(url) as resp:
            if resp.status != 200:
                raise DownloaderError(f"Mirror returned {resp.status} for .osz (set_id={beatmapset_id})")
            dest.write_bytes(await resp.read())

        logger.info("Downloaded: %s", dest.name)
        return dest

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        for ch in '<>:"/\\|?*':
            name = name.replace(ch, "_")
        return name[:150].strip()

    @staticmethod
    def open_in_os(path: Path) -> None:
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # type: ignore[attr-defined]  # Windows-only
            elif sys.platform == "darwin":
                subprocess.run(["open", str(path)], check=False)
            else:
                subprocess.run(["xdg-open", str(path)], check=False)
        except OSError as exc:
            logger.warning("Could not open %s: %s", path, exc)