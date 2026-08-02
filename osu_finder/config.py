"""
ConfigManager — loads a global config.yaml (credentials, paths, mirror,
network, blacklist) plus a named preset (search filters) from a `presets/`
directory next to the global config, and merges them into one AppConfig.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml


class ConfigError(Exception):
    """Missing required field, bad value, or unreadable config file."""


# --------------------------------------------------------------------------- #
#  Config sections
# --------------------------------------------------------------------------- #

@dataclass
class NetworkConfig:
    # aiohttp's `proxy=` kwarg only supports HTTP/HTTPS proxies, not SOCKS.
    proxy_url: Optional[str] = None
    fallback_to_direct: bool = True


@dataclass
class Credentials:
    client_id: str
    client_secret: str


@dataclass
class Paths:
    songs_folder: Path
    download_folder: Path


@dataclass
class BaseFilters:
    mode: str = "osu"          # osu | taiko | fruits | mania
    status: str = "ranked"       # ranked | qualified | loved | pending | graveyard | any
    keywords: str = ""
    genre: Optional[int] = None
    language: Optional[int] = None
    sort: str = "ranked_desc"


@dataclass
class RangeFilter:
    """[min, max] inclusive; None on either side means unrestricted."""
    min: Optional[float] = None
    max: Optional[float] = None

    def contains(self, value: Optional[float]) -> bool:
        if value is None:
            return False
        if self.min is not None and value < self.min:
            return False
        if self.max is not None and value > self.max:
            return False
        return True

    @property
    def is_unrestricted(self) -> bool:
        return self.min is None and self.max is None


@dataclass
class PpRangeFilter(RangeFilter):
    accuracy: float = 100.0  # accuracy (%) the PP value is calculated at


@dataclass
class PlaystyleFilter:
    type: str = "any"       # jump | stream | hybrid | any
    threshold: float = 1.15  # speed_strain / aim_strain ratio threshold

    VALID_TYPES = ("jump", "stream", "hybrid", "any")

    def matches(self, playstyle: str) -> bool:
        return self.type == "any" or self.type == playstyle


@dataclass
class AdvancedFilters:
    """All fields here are evaluated per (difficulty, mod combo) — i.e. already
    mod-adjusted — see DiffAnalysis / PpAnalyzer."""
    length: RangeFilter = field(default_factory=RangeFilter)
    bpm: RangeFilter = field(default_factory=RangeFilter)
    pp: PpRangeFilter = field(default_factory=PpRangeFilter)
    star_rating: RangeFilter = field(default_factory=RangeFilter)
    playstyle: PlaystyleFilter = field(default_factory=PlaystyleFilter)
    ar: RangeFilter = field(default_factory=RangeFilter)
    cs: RangeFilter = field(default_factory=RangeFilter)
    od: RangeFilter = field(default_factory=RangeFilter)
    # nomod, set-level playcount — not mod-adjusted (it's a popularity metric)
    playcount: RangeFilter = field(default_factory=RangeFilter)


@dataclass
class ExecutionConfig:
    target_count: int = 20
    auto_open: bool = False
    max_pages: int = 50
    request_delay: float = 1.0


@dataclass
class MirrorConfig:
    base_url: str = "https://osu.direct"
    osu_file_path: str = "/api/osu/{id}"     # {id} = difficulty (beatmap) id
    osz_download_path: str = "/api/d/{id}"    # {id} = beatmapset id


@dataclass
class AppConfig:
    credentials: Credentials
    paths: Paths
    mods: list[list[str]]
    base_filters: BaseFilters
    advanced_filters: AdvancedFilters
    execution: ExecutionConfig
    mirror: MirrorConfig
    blacklist: list[int] = field(default_factory=list)
    network: NetworkConfig = field(default_factory=NetworkConfig)


# --------------------------------------------------------------------------- #
#  ConfigManager
# --------------------------------------------------------------------------- #

class ConfigManager:
    """Global config (`config.yaml`) + one preset (`presets/<name>.yaml`) -> AppConfig.

    The presets directory always lives next to the global config file
    (`<config.yaml's dir>/presets/`), not relative to the current working
    directory — important once this is installed as a `pip`/PyPI console
    script and invoked from arbitrary directories.
    """

    @staticmethod
    def presets_dir(global_config_path: str | Path) -> Path:
        return Path(global_config_path).resolve().parent / "presets"

    @staticmethod
    def get_active_preset(global_config_path: str | Path) -> str:
        path = Path(global_config_path)
        if not path.exists():
            return "default"
        name = ConfigManager.read_raw(path).get("active_preset", "default")
        return str(name).removesuffix(".yaml").removesuffix(".json")

    @staticmethod
    def set_active_preset(global_config_path: str | Path, preset_name: str) -> None:
        """Persists which preset `-p`/`--preset` defaults to when omitted.
        Does not check whether the preset file exists — callers (the CLI)
        should validate that first so the error message can be specific."""
        path = Path(global_config_path)
        if not path.exists():
            raise ConfigError(f"Config file not found: {path}")

        raw = ConfigManager.read_raw(path)
        raw["active_preset"] = str(preset_name).removesuffix(".yaml").removesuffix(".json")
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(raw, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

    @staticmethod
    def list_presets(global_config_path: str | Path) -> list[tuple[str, dict[str, Any]]]:
        """Returns (name, raw_preset_dict) for every preset file, without
        merging in global credentials/paths — cheap enough to use for a
        listing even if the global config itself has issues."""
        presets_dir = ConfigManager.presets_dir(global_config_path)
        if not presets_dir.exists():
            return []
        result = []
        for path in sorted(presets_dir.glob("*.yaml")):
            try:
                result.append((path.stem, ConfigManager.read_raw(path)))
            except ConfigError:
                result.append((path.stem, {}))
        return result

    @staticmethod
    def load(global_path: str | Path, override_preset: Optional[str] = None) -> AppConfig:
        global_path = Path(global_path)
        if not global_path.exists():
            raise ConfigError(
                f"Global config file not found: {global_path}. Run 'osu-finder --init' first."
            )
        global_raw = ConfigManager.read_raw(global_path)

        preset_name = override_preset or global_raw.get("active_preset", "default")
        preset_name = str(preset_name).removesuffix(".yaml").removesuffix(".json")

        presets_dir = ConfigManager.presets_dir(global_path)
        presets_dir.mkdir(parents=True, exist_ok=True)
        preset_path = presets_dir / f"{preset_name}.yaml"

        if preset_name == "default" and not preset_path.exists():
            ConfigManager._create_default_preset(preset_path)
        if not preset_path.exists():
            raise ConfigError(f"Preset file not found: {preset_path}")

        preset_raw = ConfigManager.read_raw(preset_path)

        # Shallow merge: global and preset files use disjoint top-level keys
        # (credentials/paths/mirror/network/blacklist vs. mods/base_filters/
        # advanced_filters/execution), so this is safe.
        combined_raw = {**global_raw, **preset_raw}
        return ConfigManager._build(combined_raw)

    @staticmethod
    def save_preset(
        global_config_path: str | Path,
        preset_name: str,
        mods: list[list[str]],
        base_filters: BaseFilters,
        advanced_filters: AdvancedFilters,
        execution: ExecutionConfig,
    ) -> Path:
        """Writes only the search-related settings (a preset) to its own file."""
        presets_dir = ConfigManager.presets_dir(global_config_path)
        presets_dir.mkdir(parents=True, exist_ok=True)

        preset_name = preset_name.removesuffix(".yaml").removesuffix(".json")
        path = presets_dir / f"{preset_name}.yaml"

        def rng(rf: RangeFilter) -> dict[str, Any]:
            return {"min": rf.min, "max": rf.max}

        raw_preset: dict[str, Any] = {
            "mods": mods,
            "base_filters": {
                "mode": base_filters.mode,
                "status": base_filters.status,
                "keywords": base_filters.keywords,
                "genre": base_filters.genre,
                "language": base_filters.language,
                "sort": base_filters.sort,
            },
            "advanced_filters": {
                "length": rng(advanced_filters.length),
                "bpm": rng(advanced_filters.bpm),
                "pp": {**rng(advanced_filters.pp), "accuracy": advanced_filters.pp.accuracy},
                "star_rating": rng(advanced_filters.star_rating),
                "playstyle": {
                    "type": advanced_filters.playstyle.type,
                    "threshold": advanced_filters.playstyle.threshold,
                },
                "ar": rng(advanced_filters.ar),
                "cs": rng(advanced_filters.cs),
                "od": rng(advanced_filters.od),
                "playcount": rng(advanced_filters.playcount),
            },
            "execution": {
                "target_count": execution.target_count,
                "auto_open": execution.auto_open,
                "max_pages": execution.max_pages,
                "request_delay": execution.request_delay,
            },
        }

        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(
                ConfigManager._drop_empty(raw_preset), f,
                allow_unicode=True, sort_keys=False, default_flow_style=False,
            )
        return path

    @staticmethod
    def ban_beatmapset(global_config_path: str | Path, beatmapset_id: int) -> None:
        """Appends a beatmapset ID to the global blacklist."""
        path = Path(global_config_path)
        if not path.exists():
            raise ConfigError(f"Config file not found: {path}")

        raw = ConfigManager.read_raw(path)
        blacklist = raw.get("blacklist", [])
        if not isinstance(blacklist, list):
            blacklist = []

        if beatmapset_id not in blacklist:
            blacklist.append(beatmapset_id)
            raw["blacklist"] = blacklist
            with path.open("w", encoding="utf-8") as f:
                yaml.safe_dump(raw, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

    @staticmethod
    def initialize_config(
        client_id: str,
        client_secret: str,
        songs_folder: str,
        download_folder: str = "./downloads",
        proxy_url: Optional[str] = None,
        fallback_to_direct: bool = True,
        config_path: str | Path = "config.yaml",
    ) -> Path:
        """Writes a fresh global config.yaml plus a default preset."""
        config_path = Path(config_path)
        default_mirror = MirrorConfig()

        default_preset_path = ConfigManager.presets_dir(config_path) / "default.yaml"
        default_preset_path.parent.mkdir(parents=True, exist_ok=True)
        if not default_preset_path.exists():
            ConfigManager._create_default_preset(default_preset_path)

        global_config_data = {
            "credentials": {"client_id": client_id, "client_secret": client_secret},
            "paths": {
                "songs_folder": str(Path(songs_folder).expanduser().resolve()),
                "download_folder": str(Path(download_folder).expanduser().resolve()),
            },
            "mirror": {
                "base_url": default_mirror.base_url,
                "osu_file_path": default_mirror.osu_file_path,
                "osz_download_path": default_mirror.osz_download_path,
            },
            "network": {"proxy_url": proxy_url, "fallback_to_direct": fallback_to_direct},
            "active_preset": "default",
            "blacklist": [],
        }

        with config_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(
                ConfigManager._drop_empty(global_config_data), f,
                allow_unicode=True, sort_keys=False, default_flow_style=False,
            )
        return config_path.resolve()

    @staticmethod
    def normalize_mods(mods_raw: list) -> list[list[str]]:
        """["DT"] -> [["DT"]]; "HDHR" -> [["HD", "HR"]]; ["HD","HR"] -> unchanged."""
        normalized: list[list[str]] = []
        for entry in mods_raw:
            if isinstance(entry, str):
                if entry.upper() == "NM":
                    normalized.append(["NM"])
                elif len(entry) % 2 == 0:
                    normalized.append([entry[i:i + 2].upper() for i in range(0, len(entry), 2)])
                else:
                    normalized.append([entry.upper()])
            elif isinstance(entry, list):
                normalized.append([str(m).upper() for m in entry])
            else:
                raise ConfigError(f"Invalid mod entry: {entry!r}")
        return normalized

    # ------------------------------------------------------------------ #
    #  Internal helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def read_raw(path: Path) -> dict[str, Any]:
        text = path.read_text(encoding="utf-8")
        try:
            if path.suffix.lower() == ".json":
                return json.loads(text) or {}
            return yaml.safe_load(text) or {}
        except (yaml.YAMLError, json.JSONDecodeError) as exc:
            raise ConfigError(f"Failed to parse {path}: {exc}") from exc

    @staticmethod
    def _drop_empty(d: dict[str, Any]) -> dict[str, Any]:
        cleaned = {}
        for k, v in d.items():
            if isinstance(v, dict):
                v = ConfigManager._drop_empty(v)
            if v is not None and v != {}:
                cleaned[k] = v
        return cleaned

    @staticmethod
    def _create_default_preset(path: Path) -> None:
        default_preset = {
            "mods": [["NM"]],
            "base_filters": {"mode": "osu", "status": "ranked", "sort": "ranked_desc"},
            "advanced_filters": {
                "pp": {"min": 100, "max": 200, "accuracy": 99.0},
                "star_rating": {"min": 4.5, "max": 5.5},
                "playstyle": {"type": "any", "threshold": 1.15},
            },
            "execution": {"target_count": 5, "auto_open": True, "max_pages": 30, "request_delay": 1.0},
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(default_preset, f, allow_unicode=True, sort_keys=False)

    @staticmethod
    def _build_base_filters(raw: dict[str, Any]) -> BaseFilters:
        return BaseFilters(
            mode=raw.get("mode", "osu"),
            status=raw.get("status", "ranked"),
            keywords=raw.get("keywords", ""),
            genre=raw.get("genre"),
            language=raw.get("language"),
            sort=raw.get("sort", "ranked_desc"),
        )

    @staticmethod
    def _build_advanced_filters(raw: dict[str, Any]) -> AdvancedFilters:
        def rng(key: str) -> RangeFilter:
            d = raw.get(key, {}) or {}
            return RangeFilter(min=d.get("min"), max=d.get("max"))

        pp_raw = raw.get("pp", {}) or {}
        pp_filter = PpRangeFilter(
            min=pp_raw.get("min"), max=pp_raw.get("max"), accuracy=pp_raw.get("accuracy", 100.0)
        )

        playstyle_raw = raw.get("playstyle", {}) or {}
        playstyle_filter = PlaystyleFilter(
            type=playstyle_raw.get("type", "any"),
            threshold=playstyle_raw.get("threshold", 1.15),
        )
        if playstyle_filter.type not in PlaystyleFilter.VALID_TYPES:
            raise ConfigError(
                f"advanced_filters.playstyle.type must be one of "
                f"{PlaystyleFilter.VALID_TYPES}, got {playstyle_filter.type!r}"
            )

        return AdvancedFilters(
            length=rng("length"),
            bpm=rng("bpm"),
            pp=pp_filter,
            star_rating=rng("star_rating"),
            playstyle=playstyle_filter,
            ar=rng("ar"),
            cs=rng("cs"),
            od=rng("od"),
            playcount=rng("playcount"),
        )

    @staticmethod
    def _build(raw: dict[str, Any]) -> AppConfig:
        creds_raw = ConfigManager._require(raw, "credentials")
        client_id = ConfigManager._require(creds_raw, "client_id")
        client_secret = ConfigManager._require(creds_raw, "client_secret")
        credentials = Credentials(client_id=str(client_id), client_secret=str(client_secret))

        paths_raw = ConfigManager._require(raw, "paths")
        songs_folder = Path(ConfigManager._require(paths_raw, "songs_folder")).expanduser()
        download_folder = Path(paths_raw.get("download_folder", "./downloads")).expanduser()
        paths = Paths(songs_folder=songs_folder, download_folder=download_folder)

        mods = ConfigManager.normalize_mods(raw.get("mods") or [["NM"]])
        base_filters = ConfigManager._build_base_filters(raw.get("base_filters", {}))
        advanced_filters = ConfigManager._build_advanced_filters(raw.get("advanced_filters", {}))
        execution = ExecutionConfig(**(raw.get("execution", {}) or {}))
        mirror = MirrorConfig(**(raw.get("mirror", {}) or {}))

        blacklist_raw = raw.get("blacklist", []) or []
        blacklist = [int(x) for x in blacklist_raw if str(x).lstrip("-").isdigit()]

        network_raw = raw.get("network", {}) or {}
        network = NetworkConfig(
            proxy_url=network_raw.get("proxy_url"),
            fallback_to_direct=network_raw.get("fallback_to_direct", True),
        )

        config = AppConfig(
            credentials=credentials, paths=paths, mods=mods,
            base_filters=base_filters, advanced_filters=advanced_filters,
            execution=execution, mirror=mirror, blacklist=blacklist, network=network,
        )
        ConfigManager._validate(config)
        return config

    @staticmethod
    def _validate(config: AppConfig) -> None:
        valid_modes = {"osu", "taiko", "fruits", "mania"}
        if config.base_filters.mode not in valid_modes:
            raise ConfigError(f"base_filters.mode must be one of {valid_modes}")

        valid_statuses = {"ranked", "qualified", "loved", "pending", "graveyard", "any"}
        if config.base_filters.status not in valid_statuses:
            raise ConfigError(f"base_filters.status must be one of {valid_statuses}")

        if config.execution.target_count <= 0:
            raise ConfigError("execution.target_count must be > 0")
        if not config.mods:
            raise ConfigError("mods list cannot be empty")

    @staticmethod
    def _require(d: dict[str, Any], key: str) -> Any:
        if key not in d or d[key] in (None, ""):
            raise ConfigError(f"Missing required config field: {key!r}")
        return d[key]