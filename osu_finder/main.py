#!/usr/bin/env python3
"""
osu! Map Finder — automated beatmap search, deep local PP/SR analysis, and
downloading, driven by config presets.

Examples:
    osu-finder --init                             # one-time setup
    osu-finder --create-preset                    # interactive preset builder
    osu-finder -u SomeUsername --focus stream      # build a preset from a profile
    osu-finder -u SomeUsername --focus jump --run-search
    osu-finder -p jump_farm                        # run a specific preset
    osu-finder -p jump_farm --show-preset           # inspect a preset
    osu-finder -p jump_farm --set-pp 150:250        # edit a preset
    osu-finder --ban 123456                          # blacklist a beatmapset
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

import aiohttp
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn
from rich.table import Table

from . import AppConfig, ConfigManager, Downloader, LocalCache, OsuApiClient, PpAnalyzer, ProfileAnalyzer
from .api_client import OsuApiError
from .config import (
    AdvancedFilters,
    BaseFilters,
    ConfigError,
    ExecutionConfig,
    PlaystyleFilter,
    PpRangeFilter,
    RangeFilter,
)
from .downloader import DownloaderError
from .models import BeatmapCandidate, DiffAnalysis
from .pp_analyzer import PpAnalyzerError

console = Console()

# Separate from execution.request_delay (osu! API) — this paces requests to
# the beatmap mirror, a different server with its own limits.
MIRROR_REQUEST_DELAY = 0.3


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, show_path=False, rich_tracebacks=True)],
    )
    logging.getLogger("aiohttp").setLevel(logging.WARNING)


# =============================================================================
#  Filtering
# =============================================================================

def passes_advanced_filters(analysis: DiffAnalysis, filters: AdvancedFilters) -> bool:
    return (
        filters.length.contains(analysis.length_seconds)
        and filters.bpm.contains(analysis.bpm)
        and filters.pp.contains(analysis.pp)
        and filters.star_rating.contains(analysis.star_rating)
        and filters.ar.contains(analysis.ar)
        and filters.cs.contains(analysis.cs)
        and filters.od.contains(analysis.od)
        and filters.playstyle.matches(analysis.playstyle)
    )


def any_mod_combo_could_match_ar(
    base_ar: float, mods_list: list[list[str]], ar_filter: RangeFilter
) -> bool:
    """Cheap pre-check using the API's nomod AR (no download needed) across
    every configured mod combo, so a difficulty isn't skipped just because
    its *first* mod combo misses the AR filter."""
    if ar_filter.is_unrestricted:
        return True
    for mods in mods_list:
        mods_clean = [] if mods == ["NM"] else mods
        if ar_filter.contains(PpAnalyzer.estimate_ar(base_ar, mods_clean)):
            return True
    return False


# =============================================================================
#  Rendering
# =============================================================================

def render_candidate_row(candidate: BeatmapCandidate) -> None:
    best = candidate.best_match
    console.print(
        f"  [bold green]\u2713[/bold green] [bold]{candidate.artist} - {candidate.title}[/bold] "
        f"[dim](id {candidate.beatmapset_id}, {candidate.status})[/dim]\n"
        f"      [{best.mods_label}] {best.version} \u2014 "
        f"\u2605{best.star_rating:.2f}  {best.pp:.0f}pp  {best.bpm:.0f} BPM  {best.length_seconds:.0f}s  "
        f"AR{best.ar:.1f} CS{best.cs:.1f} OD{best.od:.1f}  style: {best.playstyle}"
    )
    if len(candidate.matched_diffs) > 1:
        console.print(f"      [dim]+ {len(candidate.matched_diffs) - 1} more matching combination(s)[/dim]")


def render_summary(candidates: list[BeatmapCandidate]) -> None:
    if not candidates:
        console.print("\n[yellow]No maps matching the current filters were found.[/yellow]")
        return

    table = Table(title=f"Summary: {len(candidates)} map(s) downloaded")
    for col, justify in [("Set ID", "right"), ("Artist - Title", "left"), ("Mods", "left"),
                        ("\u2605", "right"), ("PP", "right"), ("BPM", "right"), ("Style", "left")]:
        table.add_column(col, justify=justify) # type: ignore
        

    for c in candidates:
        best = c.best_match
        table.add_row(
            str(c.beatmapset_id), f"{c.artist} - {c.title}", best.mods_label,
            f"{best.star_rating:.2f}", f"{best.pp:.0f}", f"{best.bpm:.0f}", best.playstyle,
        )
    console.print(table)


def render_preset_info(preset_name: str, config: AppConfig) -> None:
    adv, base = config.advanced_filters, config.base_filters
    table = Table(title=f"Preset: [bold cyan]{preset_name}[/bold cyan]", border_style="cyan")
    table.add_column("Parameter", style="bold white")
    table.add_column("Value", style="green")

    def fmt(rf: RangeFilter, unit: str = "") -> str:
        if rf.is_unrestricted:
            return "Unrestricted"
        if rf.max is None:
            return f"from {rf.min}{unit}"
        if rf.min is None:
            return f"up to {rf.max}{unit}"
        return f"{rf.min} \u2013 {rf.max}{unit}"

    mod_str = ", ".join("".join(m) for m in config.mods) if config.mods else "NM"

    table.add_row("Mode / Status", f"{base.mode} / {base.status}")
    table.add_row("Mods", mod_str)
    table.add_row("PP", f"{fmt(adv.pp)} (acc {adv.pp.accuracy}%)")
    table.add_row("Star rating", fmt(adv.star_rating, "\u2605"))
    table.add_row("Playstyle", f"{adv.playstyle.type} (threshold {adv.playstyle.threshold})")
    table.add_row("AR", fmt(adv.ar))
    table.add_row("CS", fmt(adv.cs))
    table.add_row("OD", fmt(adv.od))
    table.add_row("BPM", fmt(adv.bpm))
    table.add_row("Length", fmt(adv.length, "s"))
    table.add_row("Min. playcount", fmt(adv.playcount))
    table.add_row("Target count", str(config.execution.target_count))
    table.add_row("Auto-open", str(config.execution.auto_open))
    console.print(table)


# =============================================================================
#  Search pipeline
# =============================================================================

async def run(config: AppConfig) -> list[BeatmapCandidate]:
    local_cache = LocalCache(config.paths.songs_folder, blacklist=config.blacklist).build()
    pp_analyzer = PpAnalyzer(config.mirror, config.network)
    downloader = Downloader(config.mirror, config.paths.download_folder, config.network)

    candidates: list[BeatmapCandidate] = []
    headers = {"User-Agent": "osu-finder/1.0 (+https://github.com/)"}

    async with OsuApiClient(
        config.credentials.client_id, config.credentials.client_secret,
        request_delay=config.execution.request_delay,
    ) as api_client, aiohttp.ClientSession(headers=headers) as mirror_session:

        progress = Progress(
            TextColumn("[progress.description]{task.description}"), BarColumn(),
            TextColumn("{task.completed}/{task.total}"), TimeElapsedColumn(), console=console,
        )

        with progress:
            task_id = progress.add_task("Searching and analyzing maps", total=config.execution.target_count)
            checked_sets = skipped_local = 0

            async for bset in api_client.iter_beatmapsets(config.base_filters, max_pages=config.execution.max_pages):
                if len(candidates) >= config.execution.target_count:
                    break

                set_id = bset["id"]
                if set_id in local_cache:
                    skipped_local += 1
                    continue

                if not config.advanced_filters.playcount.contains(bset.get("playcount", 0)):
                    continue

                checked_sets += 1
                matched_diffs: list[DiffAnalysis] = []

                for diff in bset.get("beatmaps", []):
                    diff_id = diff["id"]
                    api_bpm = diff.get("bpm") or bset.get("bpm") or 0.0
                    api_hit_length = diff.get("hit_length") or bset.get("hit_length") or 0.0
                    api_ar = float(diff.get("ar", 0.0))

                    if not any_mod_combo_could_match_ar(api_ar, config.mods, config.advanced_filters.ar):
                        continue

                    try:
                        osu_content = await pp_analyzer.fetch_osu_file(mirror_session, diff_id)
                    except PpAnalyzerError as exc:
                        logging.debug("Skipping difficulty id=%s: %s", diff_id, exc)
                        continue
                    await asyncio.sleep(MIRROR_REQUEST_DELAY)

                    for mods in config.mods:
                        mods_clean = [] if mods == ["NM"] else mods
                        analysis = pp_analyzer.analyze(
                            osu_content, beatmap_id=diff_id, version=diff.get("version", ""),
                            api_bpm=api_bpm, api_hit_length=api_hit_length, mods=mods_clean,
                            accuracy=config.advanced_filters.pp.accuracy,
                            playstyle_threshold=config.advanced_filters.playstyle.threshold,
                        )
                        if analysis and passes_advanced_filters(analysis, config.advanced_filters):
                            matched_diffs.append(analysis)

                if not matched_diffs:
                    continue

                candidate = BeatmapCandidate(
                    beatmapset_id=set_id, artist=bset.get("artist", "?"), title=bset.get("title", "?"),
                    creator=bset.get("creator", "?"), status=bset.get("status", "?"), matched_diffs=matched_diffs,
                )
                candidates.append(candidate)
                local_cache.add(set_id)
                progress.advance(task_id)
                render_candidate_row(candidate)

                try:
                    dest = await downloader.download_osz(mirror_session, set_id, f"{candidate.artist} - {candidate.title}")
                    if config.execution.auto_open:
                        downloader.open_in_os(dest)
                except DownloaderError as exc:
                    console.print(f"      [red]Download error: {exc}[/red]")

                await asyncio.sleep(MIRROR_REQUEST_DELAY)

            console.print(f"\n[dim]New sets checked: {checked_sets}, skipped (local/blacklisted): {skipped_local}[/dim]")

    return candidates


# =============================================================================
#  Interactive preset wizard (--create-preset)
# =============================================================================

def _ask_range(label: str, unit: str = "") -> RangeFilter:
    suffix = f" ({unit})" if unit else ""
    raw = console.input(
        f"[bold]{label}{suffix}[/bold] [dim]e.g. '150:250', '150:', ':250' \u2014 Enter to skip[/dim]\n> "
    ).strip()
    if not raw:
        return RangeFilter()
    min_s, _, max_s = raw.partition(":")
    return RangeFilter(
        min=float(min_s) if min_s.strip() else None,
        max=float(max_s) if max_s.strip() else None,
    )


def _ask_choice(label: str, choices: list[str], default: str) -> str:
    raw = console.input(f"[bold]{label}[/bold] ({'/'.join(choices)}) [dim]default: {default}[/dim]\n> ").strip().lower()
    return raw if raw in choices else default


def _ask_text(label: str, default: str = "") -> str:
    raw = console.input(f"[bold]{label}[/bold] [dim]default: {default!r}[/dim]\n> ").strip()
    return raw or default


def _ask_bool(label: str, default: bool) -> bool:
    hint = "Y/n" if default else "y/N"
    raw = console.input(f"[bold]{label}[/bold] [{hint}]\n> ").strip().lower()
    return default if not raw else raw.startswith("y")


def run_preset_wizard(config_path: str) -> None:
    console.print(Panel.fit("[bold cyan]New Preset Wizard[/bold cyan]", border_style="cyan"))
    console.print("[dim]Enter skips a field (unrestricted / default).[/dim]\n")

    name = ""
    while not name:
        name = console.input("[bold green]Preset name:[/bold green] ").strip()

    presets_dir = ConfigManager.presets_dir(config_path)
    if (presets_dir / f"{name}.yaml").exists() and not _ask_bool(f"'{name}' already exists \u2014 overwrite?", False):
        console.print("[yellow]Cancelled.[/yellow]")
        return

    mode = _ask_choice("Game mode", ["osu", "taiko", "fruits", "mania"], "osu")
    status = _ask_choice("Beatmap status", ["ranked", "qualified", "loved", "pending", "graveyard", "any"], "ranked")
    keywords = _ask_text("Search keywords (artist/title/tags)", "")
    sort = _ask_text("Sort order", "ranked_desc")

    mods_raw = _ask_text("Mods, comma-separated (e.g. 'NM, DT, HDHR')", "NM")
    mods = ConfigManager.normalize_mods([m.strip() for m in mods_raw.split(",") if m.strip()])

    pp_range = _ask_range("PP")
    accuracy = float(_ask_text("Accuracy % for PP calculation", "99.0"))
    star_range = _ask_range("Star rating", "\u2605")
    bpm_range = _ask_range("BPM")
    length_range = _ask_range("Length", "sec")
    ar_range = _ask_range("AR")
    cs_range = _ask_range("CS")
    od_range = _ask_range("OD")
    playcount_range = _ask_range("Minimum playcount")

    playstyle_type = _ask_choice("Playstyle", ["jump", "stream", "hybrid", "any"], "any")
    playstyle_threshold = float(_ask_text("Playstyle strain-ratio threshold", "1.15"))

    target_count = int(_ask_text("How many maps to find per run", "5"))
    auto_open = _ask_bool("Auto-open downloaded .osz files", True)

    base_filters = BaseFilters(mode=mode, status=status, keywords=keywords, sort=sort)
    advanced_filters = AdvancedFilters(
        length=length_range, bpm=bpm_range,
        pp=PpRangeFilter(min=pp_range.min, max=pp_range.max, accuracy=accuracy),
        star_rating=star_range, ar=ar_range, cs=cs_range, od=od_range, playcount=playcount_range,
        playstyle=PlaystyleFilter(type=playstyle_type, threshold=playstyle_threshold),
    )
    execution = ExecutionConfig(target_count=target_count, auto_open=auto_open)

    path = ConfigManager.save_preset(config_path, name, mods, base_filters, advanced_filters, execution)
    console.print(f"\n[bold green]Preset saved:[/bold green] {path}")
    console.print(f"[dim]Run it with: osu-finder -p {name}[/dim]")


# =============================================================================
#  --init / --ban
# =============================================================================

def handle_init(args: argparse.Namespace) -> None:
    console.print(Panel.fit("[bold cyan]osu! Map Finder \u2014 Setup[/bold cyan]", border_style="cyan"))

    client_id = args.client_id or console.input("[bold green]osu! Client ID:[/bold green] ").strip()
    client_secret = args.client_secret or console.input("[bold green]osu! Client Secret:[/bold green] ").strip()
    songs_folder = args.songs_folder or console.input("[bold green]Path to osu!/Songs folder:[/bold green] ").strip()
    proxy_url = args.proxy_url or console.input("[bold yellow]Proxy URL (Enter to skip):[/bold yellow] ").strip() or None

    try:
        saved_path = ConfigManager.initialize_config(
            client_id=client_id, client_secret=client_secret, songs_folder=songs_folder,
            download_folder=args.download_folder, proxy_url=proxy_url,
            fallback_to_direct=not args.no_fallback, config_path=args.config,
        )
    except Exception as exc:
        console.print(f"[bold red]Setup error:[/bold red] {exc}")
        sys.exit(1)

    console.print(
        f"\n[bold green]Configuration created:[/bold green] {saved_path}\n\n"
        "[bold cyan]Next steps:[/bold cyan]\n"
        " 1. Build a preset from your profile:  [yellow]osu-finder -u YourName --focus stream[/yellow]\n"
        "    ...or build one by hand:            [yellow]osu-finder --create-preset[/yellow]\n"
        " 2. Inspect it:                          [yellow]osu-finder -p <name> --show-preset[/yellow]\n"
        " 3. Run it:                               [yellow]osu-finder -p <name>[/yellow]"
    )


def handle_ban(args: argparse.Namespace) -> None:
    try:
        ConfigManager.ban_beatmapset(args.config, args.ban)
    except ConfigError as exc:
        console.print(f"[bold red]Failed to update blacklist:[/bold red] {exc}")
        sys.exit(1)
    console.print(f"[bold green]\u2713[/bold green] Set [bold]{args.ban}[/bold] added to the blacklist.")


# =============================================================================
#  CLI
# =============================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="osu-finder",
        description="Automated osu! beatmap finder with local PP/SR analysis.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  osu-finder --init\n"
            "  osu-finder --create-preset\n"
            "  osu-finder -u SomeUser --focus stream\n"
            "  osu-finder -p jump_farm --show-preset\n"
            "  osu-finder -p jump_farm --set-ar 9:9.5\n"
        ),
    )
    main_group = parser.add_argument_group("Main commands")
    main_group.add_argument("--init", action="store_true", help="Interactive first-time setup")
    main_group.add_argument("--create-preset", action="store_true", help="Interactively build a new preset")
    main_group.add_argument("-p", "--preset", type=str, help="Preset to load (default: active_preset from config)")
    main_group.add_argument("-u", "--analyze-user", type=str, help="Build a preset from a player's top plays")
    main_group.add_argument("--focus", choices=["balanced", "stream", "jump", "push", "farm"], default="balanced")
    main_group.add_argument("--run-search", action="store_true", help="Run the search right after --analyze-user")
    main_group.add_argument("--show-preset", "--show", action="store_true", help="Print the selected preset")
    main_group.add_argument("--ban", type=int, metavar="SET_ID", help="Blacklist a beatmapset ID")

    edit_group = parser.add_argument_group("Edit a preset (range format: 'MIN:MAX', 'MIN:' or ':MAX')")
    edit_group.add_argument("--set-ar", type=str)
    edit_group.add_argument("--set-cs", type=str)
    edit_group.add_argument("--set-od", type=str)
    edit_group.add_argument("--set-pp", type=str)
    edit_group.add_argument("--set-star", type=str)
    edit_group.add_argument("--set-bpm", type=str)
    edit_group.add_argument("--set-length", type=str)
    edit_group.add_argument("--set-playcount", type=str)
    edit_group.add_argument("--set-acc", type=float, help="Accuracy %% for PP calculation")
    edit_group.add_argument("--set-mods", type=str, help="e.g. 'HDHR', 'DT', 'NM' (comma-separated for multiple)")
    edit_group.add_argument("--set-style", choices=["jump", "stream", "hybrid", "any"])
    edit_group.add_argument("--set-auto-open", choices=["true", "false"])
    edit_group.add_argument("--set-target", type=int, help="Maps to download per run")

    sys_group = parser.add_argument_group("System")
    sys_group.add_argument("--config", default="config.yaml", help="Path to the global config file")
    sys_group.add_argument("--client-id", help="For --init")
    sys_group.add_argument("--client-secret", help="For --init")
    sys_group.add_argument("--songs-folder", help="For --init")
    sys_group.add_argument("--download-folder", default="./downloads", help="For --init")
    sys_group.add_argument("--proxy-url", help="For --init")
    sys_group.add_argument("--no-fallback", action="store_true", help="Disable direct-connection fallback")
    sys_group.add_argument("-v", "--verbose", action="store_true")

    return parser.parse_args()


def _parse_range_arg(val: str) -> RangeFilter:
    min_s, _, max_s = val.partition(":")
    return RangeFilter(
        min=float(min_s) if min_s.strip() else None,
        max=float(max_s) if max_s.strip() else None,
    )


def _apply_edit_flags(args: argparse.Namespace, config: AppConfig) -> bool:
    """Applies any --set-* flags to `config` in place. Returns True if anything changed."""
    adv = config.advanced_filters
    edits = {
        "set_ar": lambda v: setattr(adv, "ar", _parse_range_arg(v)),
        "set_cs": lambda v: setattr(adv, "cs", _parse_range_arg(v)),
        "set_od": lambda v: setattr(adv, "od", _parse_range_arg(v)),
        "set_star": lambda v: setattr(adv, "star_rating", _parse_range_arg(v)),
        "set_bpm": lambda v: setattr(adv, "bpm", _parse_range_arg(v)),
        "set_length": lambda v: setattr(adv, "length", _parse_range_arg(v)),
        "set_playcount": lambda v: setattr(adv, "playcount", _parse_range_arg(v)),
        "set_style": lambda v: setattr(adv.playstyle, "type", v),
    }
    modified = False
    for attr, apply in edits.items():
        val = getattr(args, attr)
        if val is not None:
            apply(val)
            modified = True

    if args.set_pp is not None:
        rf = _parse_range_arg(args.set_pp)
        adv.pp.min, adv.pp.max = rf.min, rf.max
        modified = True
    if args.set_acc is not None:
        adv.pp.accuracy = args.set_acc
        modified = True
    if args.set_mods is not None:
        config.mods = ConfigManager.normalize_mods([m.strip() for m in args.set_mods.split(",") if m.strip()])
        modified = True
    if args.set_auto_open is not None:
        config.execution.auto_open = args.set_auto_open == "true"
        modified = True
    if args.set_target is not None:
        config.execution.target_count = args.set_target
        modified = True

    return modified


async def _handle_analyze_user(args: argparse.Namespace, config: AppConfig) -> str:
    """Returns the generated preset name."""
    console.print(f"\n[bold blue]Analyzing profile: {args.analyze_user} (focus: {args.focus})...[/bold blue]")
    headers = {"User-Agent": "osu-finder/1.0 (+https://github.com/)"}

    async with OsuApiClient(config.credentials.client_id, config.credentials.client_secret) as api_client, \
            aiohttp.ClientSession(headers=headers) as session:
        analyzer = ProfileAnalyzer(api_client, PpAnalyzer(config.mirror, config.network))
        profile = await analyzer.analyze_user(
            session, args.analyze_user, limit=100, focus=args.focus, mode=config.base_filters.mode
        )

    adv = config.advanced_filters
    adv.pp.min, adv.pp.max = profile.target_pp_min, profile.target_pp_max
    adv.star_rating.min, adv.star_rating.max = profile.star_min, profile.star_max
    adv.ar.min, adv.ar.max = profile.ar_min, profile.ar_max
    adv.length.min, adv.length.max = profile.target_length_min, profile.target_length_max
    adv.playstyle.type = profile.favored_playstyle
    config.mods = profile.preferred_mods

    safe_username = args.analyze_user.replace(" ", "_")
    preset_name = f"user_{safe_username}" if args.focus == "balanced" else f"user_{safe_username}_{args.focus}"
    ConfigManager.save_preset(args.config, preset_name, config.mods, config.base_filters, adv, config.execution)

    mod_str = "".join(profile.preferred_mods[0]) if profile.preferred_mods[0] != ["NM"] else "NM"
    console.print(
        f"\n[bold green]Profile analyzed.[/bold green]\n"
        f"  PP: {profile.target_pp_min:.0f}-{profile.target_pp_max:.0f}   "
        f"Stars: {profile.star_min:.2f}-{profile.star_max:.2f}   "
        f"AR: {profile.ar_min:.1f}-{profile.ar_max:.1f}\n"
        f"  Playstyle: {profile.favored_playstyle}   Mods: {mod_str}\n"
        f"[yellow]Saved preset: {preset_name}[/yellow]"
    )
    return preset_name


async def async_main() -> None:
    args = parse_args()
    setup_logging(args.verbose)

    if args.init:
        handle_init(args)
        return
    if args.ban is not None:
        handle_ban(args)
        return
    if args.create_preset:
        run_preset_wizard(args.config)
        return

    console.print(Panel.fit("[bold cyan]osu! Map Finder[/bold cyan]", border_style="cyan"))

    try:
        config = ConfigManager.load(args.config, override_preset=args.preset)
    except ConfigError as exc:
        console.print(f"[bold red]Configuration error:[/bold red] {exc}")
        sys.exit(1)

    if args.analyze_user:
        try:
            preset_name = await _handle_analyze_user(args, config)
        except Exception as exc:
            console.print(f"[bold red]Profile analysis error:[/bold red] {exc}")
            sys.exit(1)
        if not args.run_search:
            console.print(f"[dim]Run it later with: osu-finder -p {preset_name}[/dim]")
            return

    current_preset = args.preset or "default"
    if _apply_edit_flags(args, config):
        ConfigManager.save_preset(
            args.config, current_preset, config.mods, config.base_filters, config.advanced_filters, config.execution
        )
        console.print(f"[bold green]\u2713 Preset '{current_preset}' updated.[/bold green]")
        return

    if args.show_preset:
        render_preset_info(current_preset, config)
        return

    try:
        candidates = await run(config)
    except OsuApiError as exc:
        console.print(f"[bold red]osu! API error:[/bold red] {exc}")
        sys.exit(1)
    render_summary(candidates)


def main() -> None:
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        sys.exit(130)


if __name__ == "__main__":
    main()