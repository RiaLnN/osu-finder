# osu-finder

<p align="center">
  <strong>Asynchronous beatmap discovery powered by local performance analysis.</strong>
</p>

<p align="center">
  Search • Analyze • Filter • Download
</p>

<p align="center">

[![PyPI](https://img.shields.io/pypi/v/osu-finder.svg)](https://pypi.org/project/osu-finder/)
[![License](https://img.shields.io/github/license/RiaLnN/osu-finder)](LICENSE)

</p>

---

## Overview

**osu-finder** is an asynchronous command-line utility for discovering osu! beatmaps using **local difficulty and performance analysis** instead of relying solely on metadata provided by the official osu! API.

Unlike conventional beatmap search tools, **osu-finder** downloads only lightweight `.osu` difficulty files, analyzes them locally using **rosu-pp-py**, evaluates every configured mod combination, and keeps only beatmaps that satisfy your own performance criteria.

The project combines:

- official osu! API v2
- local star rating calculation
- local PP calculation
- automatic player profile analysis
- configurable search presets
- advanced difficulty filtering
- automatic beatmap downloading

into a single automated workflow.

---

## Why osu-finder?

The official osu! API provides excellent search capabilities, but it cannot answer questions such as:

- *Which ranked maps give around 240 PP with HDHR?*
- *Find DT stream maps around 300 BPM.*
- *Search only jump maps between 6.2★ and 6.8★.*
- *Download maps matching my own top plays.*
- *Ignore maps I already have installed.*
- *Evaluate multiple mod combinations before downloading.*

osu-finder fills this gap.

Instead of trusting API metadata alone, every candidate beatmap is validated locally before being accepted.

This makes searches significantly more accurate while avoiding unnecessary downloads.

---

# Features

## Local difficulty analysis

Instead of using the API's server-side difficulty attributes, osu-finder calculates everything locally with **rosu-pp-py**.

For every difficulty it can calculate:

- Star Rating
- Performance Points (PP)
- Aim strain
- Speed strain
- AR
- CS
- OD
- HP
- BPM (after mods)
- Length (after mods)
- Clock rate

All calculations are performed locally.

---

## Multi-mod analysis

Each difficulty can be evaluated using multiple mod combinations.

Example:

```yaml
mods:
  - ["NM"]
  - ["DT"]
  - ["HD", "HR"]
```

A beatmap is accepted if **any configured mod combination** satisfies all advanced filters.

This allows searching for maps that are only suitable with specific mods without running multiple searches.

---

## Automatic profile analysis

Generate search presets directly from a player's top plays.

```bash
osu-finder -u WhiteCat --focus jump
```

The generated preset automatically estimates:

- preferred PP range
- star rating range
- AR range
- preferred mods
- dominant playstyle
- recommended map length

making it easy to discover maps matching a player's skill level.

---

## Advanced filtering

Filter beatmaps using any combination of:

- PP
- Star Rating
- BPM
- Length
- AR
- CS
- OD
- Playcount
- Playstyle

Unlike API search filters, these values are calculated after applying the selected mods whenever possible.

---

## Playstyle detection

osu-finder classifies beatmaps into three categories:

- Jump
- Stream
- Hybrid

The classification is based on the ratio between aim strain and speed strain calculated by **rosu-pp-py**, allowing presets to target specific mechanical skills rather than relying on star rating alone.

---

## Smart local cache

Before searching, osu-finder scans the local `Songs` directory and remembers every installed BeatmapSet ID.

Already installed maps are skipped automatically.

A configurable blacklist provides an additional permanent exclusion list for unwanted beatmaps.

---

## Automatic downloads

Accepted beatmaps can be downloaded immediately as `.osz` archives.

Optionally, downloaded files may be opened automatically, allowing the osu! client to import them without additional user interaction.

---

## Fully asynchronous

Network operations are implemented with **aiohttp** and **asyncio**.

The application asynchronously:

- communicates with the official osu! API
- downloads `.osu` files
- downloads `.osz` archives
- performs profile analysis

while respecting configurable request delays and API rate limits.

---

# Design Goals

osu-finder was designed around several principles.

## Accuracy over metadata

Every beatmap is verified locally before being accepted.

Search results depend on actual calculated difficulty attributes rather than incomplete API metadata.

---

## Automation

Common workflows should require as little manual work as possible.

Searching, analyzing, filtering and downloading beatmaps should happen in a single command whenever possible.

---

## Reproducibility

Searches are stored as YAML presets.

Once a preset is created, the same search can be reproduced at any time.

---

## Extensibility

The project separates:

- global configuration
- search presets
- profile analysis
- API communication
- local PP analysis
- downloading

making it straightforward to extend individual components independently.

---

# Installation

## Requirements

Before installing **osu-finder**, make sure you have:

- Python **3.10** or newer
- An **osu! API v2 OAuth application**
- An installed osu! client (optional, for automatic beatmap importing)
- Internet access to the osu! API and the configured beatmap mirror

Supported operating systems:

- Windows
- Linux
- macOS

---

## Install from PyPI

```bash
pipx install osu-finder
```

Verify the installation:

```bash
osu-finder --help
```

---

## Install from source

Clone the repository:

```bash
git clone https://github.com/RiaLnN/osu-finder.git
cd osu-finder
```

Install the package:

```bash
pipx install .
```

For development:

```bash
pipx install -e .
```

---

# Getting Started

The recommended first-time setup consists of four simple steps:

1. Create an osu! OAuth application.
2. Initialize the global configuration.
3. Create a search preset.
4. Run your first search.

The following sections explain each step.

---

# Step 1 — Create an OAuth Application

osu-finder communicates with the official **osu! API v2** using the **Client Credentials Grant** flow.

Only public API access is required.

Open:

https://osu.ppy.sh/home/account/edit#oauth

Create a new OAuth application.

Example:

```
Application Name:
osu-finder

Callback URL:
(empty)
```

After creating the application you will receive:

- Client ID
- Client Secret

These credentials will later be stored inside your global configuration file.

> **Note**
>
> osu-finder never performs user authentication.
>
> No browser login flow is required.
>
> Only public API endpoints are accessed.

---

# Step 2 — Initialize Configuration

Run:

```bash
osu-finder --init
```

The interactive wizard creates a new configuration file and guides you through all required settings.

Typical questions include:

- osu! Client ID
- osu! Client Secret
- Songs directory
- Download directory
- Beatmap mirror
- Network configuration

After completion your project directory will contain:

```
config.yaml
presets/
```

---

# Global Configuration

The global configuration stores settings shared by every preset.

Typical structure:

```
config.yaml
```

Responsibilities include:

- OAuth credentials
- filesystem paths
- download directory
- beatmap mirror
- proxy configuration
- blacklist
- default preset

Unlike search presets, these values rarely change.

---

# Directory Layout

A typical working directory looks like:

```text
osu-finder/

├── config.yaml
├── presets/
│   ├── default.yaml
│   ├── stream.yaml
│   ├── farm.yaml
│   └── tournament.yaml
|   └── user_mrekk_push.yaml
│
├── downloads/
│   ├── ...
│
└── logs/
```

Only **config.yaml** is global.

Every search configuration lives inside the **presets/** directory.

---

# Step 3 — Create a Preset

A preset describes **what kinds of beatmaps should be searched for**.

There are two ways to create one.

## Interactive

```bash
osu-finder --create-preset
```

The CLI asks for all required parameters and writes a ready-to-use YAML preset.

---

## Automatic

A preset can also be generated directly from a player's top plays.

Example:

```bash
osu-finder -u WhiteCat
```

Or specify a particular training focus:

```bash
osu-finder -u WhiteCat --focus stream
```

Available focus modes include:

- balanced
- jump
- stream
- push
- farm

The generated preset estimates:

- preferred PP range
- star range
- AR range
- preferred mods
- dominant playstyle
- recommended map length

based on the analyzed profile.

---

# Step 4 — Run Your First Search

If you have a default preset configured:

```bash
osu-finder
```

or

```bash
osu-finder --run-search
```

To use a specific preset:

```bash
osu-finder --preset stream
```

The application will:

1. Load the global configuration.
2. Load the selected preset.
3. Authenticate with the osu! API.
4. Scan the local Songs directory.
5. Search beatmapsets.
6. Download candidate `.osu` files.
7. Perform local difficulty analysis.
8. Apply advanced filters.
9. Download matching beatmaps.
10. Optionally open every downloaded `.osz` file.

No manual interaction is required after the search starts.

---

# Search Pipeline

A simplified overview of the complete workflow:

```text
  Load Configuration
          │
          ▼
    Authenticate
          │
          ▼
  Scan Local Songs Folder
          │
          ▼
  Search Beatmapsets
          │
          ▼
  Download .osu Files
          │
          ▼
  Calculate Difficulty
          │
          ▼
  Apply Advanced Filters
          │
          ▼
      Accepted?
    │            │
    │ No         │ Yes
    ▼            ▼
  Skip       Download.osz
                 │
                 ▼
        Optionally Open in osu!
```

Every difficulty is analyzed locally before any beatmap archive is downloaded.

This minimizes unnecessary downloads while ensuring that search results satisfy the configured filters.

---

# Typical Workflows

## Find comfortable maps

```bash
osu-finder --preset comfort
```

Searches for beatmaps matching an existing preset.

---

## Practice streams

```bash
osu-finder --preset stream
```

Returns beatmaps matching stream-oriented filters.

---

## Improve aim

```bash
osu-finder --preset jump
```

Searches primarily for jump-heavy maps.

---

## Build a preset from your profile

```bash
osu-finder -u YourUsername
```

Automatically creates a preset based on your top plays.

---

## Generate a push preset

```bash
osu-finder -u YourUsername --focus push
```

Creates a preset targeting more difficult maps than your current comfort range.

---

## Download maps only once

Already installed BeatmapSet IDs are detected automatically.

Duplicate downloads are skipped without requiring any user action.

# Configuration

osu-finder separates configuration into two independent layers:

| File | Purpose |
|------|----------|
| `config.yaml` | Global application settings |
| `presets/<name>.yaml` | Individual search configuration |

This separation allows multiple search presets to reuse the same credentials, filesystem paths, mirror configuration and network settings.

---

# Global Configuration (`config.yaml`)

The global configuration contains settings that are shared by every search preset.

A minimal configuration looks like this:

```yaml
credentials:
  client_id: "12345"
  client_secret: YOUR_CLIENT_SECRET

paths:
  songs_folder: C:\osu!\Songs
  download_folder: downloads

mirror:
  base_url: https://osu.direct
  osu_file_path: /api/osu/{id}
  osz_download_path: /api/d/{id}

blacklist: []

network:
  proxy_url: null
  fallback_to_direct: true

active_preset: default
```

---

# credentials

```yaml
credentials:
  client_id: "12345"
  client_secret: YOUR_CLIENT_SECRET
```

OAuth credentials used to authenticate with the official osu! API.

Both values are obtained by creating an OAuth application in your osu! account.

These credentials are required before any search can be performed.

---

# paths

```yaml
paths:
  songs_folder: C:\osu!\Songs
  download_folder: downloads
```

## songs_folder

Path to your local osu! Songs directory.

Before every search, osu-finder scans this directory and extracts BeatmapSet IDs from folder names.

Already installed beatmaps are skipped automatically.

If the directory does not exist, searching still works, but duplicate detection is disabled.

---

## download_folder

Destination directory for downloaded `.osz` archives.

The directory is created automatically if it does not already exist.

---

# mirror

```yaml
mirror:
  base_url: https://osu.direct
  osu_file_path: /api/osu/{id}
  osz_download_path: /api/d/{id}
```

The official osu! API does not provide anonymous beatmap file downloads.

Instead, osu-finder downloads beatmap files from a configurable mirror.

The mirror configuration consists of three parts.

---

## base_url

Example:

```yaml
base_url: https://osu.direct
```

Root URL of the mirror.

---

## osu_file_path

Example:

```yaml
osu_file_path: /api/osu/{id}
```

Path used when downloading individual `.osu` difficulty files.

`{id}` is automatically replaced with the beatmap difficulty ID.

These files are used only for local difficulty analysis.

---

## osz_download_path

Example:

```yaml
osz_download_path: /api/d/{id}
```

Path used when downloading complete `.osz` beatmap archives.

`{id}` is replaced with the BeatmapSet ID.

---

# blacklist

```yaml
blacklist:
  - 123456
  - 654321
```

A list of BeatmapSet IDs that should never be downloaded.

Blacklisted maps are skipped before any analysis is performed.

The blacklist works together with the local Songs cache.

A beatmap is skipped if it is:

- already installed locally;
- explicitly blacklisted.

---

# network

```yaml
network:
  proxy_url: null
  fallback_to_direct: true
```

Network-related options.

---

## proxy_url

Example:

```yaml
proxy_url: http://user:password@host:port
```

Optional HTTP/HTTPS proxy used for:

- API requests
- `.osu` downloads
- `.osz` downloads

SOCKS proxies are currently not supported.

---

## fallback_to_direct

```yaml
fallback_to_direct: true
```

When enabled, failed proxy requests are retried without using the proxy.

This provides improved reliability when using unstable proxy servers.

---

# active_preset

```yaml
active_preset: default
```

Specifies which preset should be used when `--preset` is not supplied.

Example:

```bash
osu-finder
```

is equivalent to

```bash
osu-finder --preset default
```

---

# Search Presets

Unlike `config.yaml`, presets define **how beatmaps are searched**.

Each preset is completely independent.

Example directory:

```text
presets/

default.yaml
stream.yaml
farm.yaml
jump.yaml
tournament.yaml
```

Switching between presets does not require modifying the global configuration.

---

# Preset Structure

A preset consists of four independent sections.

```yaml
mods:

base_filters:

advanced_filters:

execution:
```

Each section controls a different stage of the search pipeline.

---

# mods

Example:

```yaml
mods:
  - ["NM"]
  - ["DT"]
  - ["HD", "HR"]
```

This is one of the most important parts of the configuration.

Every beatmap difficulty is analyzed once **for each configured mod combination**.

Example:

```
NM
DT
HDHR
```

produces three independent analyses.

A beatmap is accepted if **at least one** mod combination satisfies all advanced filters.

This allows a single search to simultaneously evaluate multiple play styles.

---

# base_filters

Base filters are sent directly to the official osu! API.

They reduce the number of beatmaps that must be analyzed locally.

Unlike advanced filters, these values are evaluated before downloading any `.osu` files.

---

## mode

```yaml
mode: osu
```

Supported values:

- osu
- taiko
- fruits
- mania

---

## status

```yaml
status: ranked
```

Available values:

- ranked
- qualified
- loved
- pending
- graveyard
- any

---

## keywords

```yaml
keywords: camellia
```

Performs a text search against beatmap metadata.

Typical use cases include:

- artist
- title
- mapper
- tags

Leave empty to disable keyword filtering.

---

## genre

```yaml
genre: 3
```

Optional numeric genre identifier used by the osu! website.

Set to `null` to disable.

---

## language

```yaml
language: 2
```

Optional language identifier.

Set to `null` to search all languages.

---

## sort

Example:

```yaml
sort: ranked_desc
```

Determines the order in which beatmaps are returned by the API.

Common choices include:

- ranked_desc
- ranked_asc
- difficulty_desc
- difficulty_asc

The selected order can significantly affect how quickly suitable maps are found.

# Advanced Filters

Unlike **base filters**, advanced filters are evaluated **after** downloading and analyzing each individual beatmap difficulty.

This is where osu-finder differs from conventional beatmap search tools.

Instead of filtering using API metadata, osu-finder performs a complete local difficulty analysis using **rosu-pp-py**, calculates all requested attributes for every configured mod combination, and only then decides whether a beatmap should be accepted.

Because of this, filters such as PP, AR, BPM and map length always reflect the selected mods.

---

# Evaluation Pipeline

For every beatmap difficulty the following steps are performed:

```
Download .osu
      │
      ▼
Parse beatmap
      │
      ▼
Apply mod combination
      │
      ▼
Calculate difficulty
      │
      ▼
Calculate PP
      │
      ▼
Calculate beatmap attributes
      │
      ▼
Apply Advanced Filters
      │
      ▼
Accept or Reject
```

If several mod combinations are configured, the entire pipeline is repeated for each one.

A difficulty is accepted if **any** configuration satisfies every enabled filter.

---

# PP Filter

```yaml
pp:
  min: 220
  max: 320
  accuracy: 99.0
```

The PP filter limits beatmaps by the calculated performance value.

Unlike the osu! website, PP is not taken from the API.

Instead, it is calculated locally for every difficulty using **rosu-pp-py**.

This guarantees that the result always matches the configured mod combination.

---

## accuracy

```yaml
accuracy: 99.0
```

PP depends on player accuracy.

osu-finder therefore requires a reference accuracy when calculating performance.

Examples:

| Accuracy | Interpretation |
|-----------|---------------|
| 95% | Low consistency |
| 98% | Typical score |
| 99% | Stable full combo |
| 100% | Perfect play |

Changing this value affects only PP calculations.

It does **not** influence any other filters.

---

# Star Rating

```yaml
star_rating:
  min: 5.8
  max: 6.5
```

Limits beatmaps by calculated star rating.

Stars are computed locally after applying the selected mods.

For example:

- DT usually increases star rating.
- HR often increases star rating.
- EZ generally decreases star rating.

The calculated value is therefore more accurate than relying on metadata alone.

---

# BPM

```yaml
bpm:
  min: 180
  max: 260
```

Filters beatmaps by effective BPM.

Clock-changing mods are fully supported.

Examples:

| Mods | Result |
|------|--------|
| NM | Original BPM |
| DT | Increased BPM |
| HT | Reduced BPM |

Example:

```
Original BPM: 180

DT

Effective BPM: 270
```

The BPM filter always evaluates the effective gameplay speed.

---

# Length

```yaml
length:
  min: 90
  max: 180
```

Filters beatmaps by playable drain time.

Clock-changing mods affect map duration.

For example:

| Mods | Effective Length |
|------|------------------|
| NM | Original length |
| DT | Shorter |
| HT | Longer |

Example:

```
Original length

180 seconds

DT

120 seconds
```

This makes it possible to search specifically for short practice maps or longer endurance maps.

---

# AR

```yaml
ar:
  min: 9.4
  max: 10.3
```

Approach Rate is calculated locally after applying mods.

Examples:

| Mods | Effect |
|------|---------|
| HR | Higher AR |
| EZ | Lower AR |
| DT | Faster approach timing |
| HT | Slower approach timing |

Because osu-finder evaluates AR after applying mods, searches remain accurate even for mixed mod configurations.

---

# CS

```yaml
cs:
  min: 4
  max: 5
```

Circle Size filtering is also performed after mod adjustments.

Examples:

- HR increases CS.
- EZ decreases CS.

No manual calculations are required.

---

# OD

```yaml
od:
  min: 8
  max: 10
```

Overall Difficulty is calculated after applying mods.

This allows searches such as:

> Find DT maps with OD between 9.5 and 10.3.

without relying on approximate API values.

---

# Playcount

```yaml
playcount:
  min: 5000
```

Unlike most advanced filters, playcount comes directly from the beatmap metadata.

It represents overall popularity rather than difficulty.

Common uses include:

- avoiding obscure maps
- finding hidden gems
- searching only widely played beatmaps

Playcount is evaluated per BeatmapSet.

---

# Playstyle Detection

```yaml
playstyle:
  type: jump
  threshold: 1.15
```

osu-finder automatically classifies every analyzed difficulty into one of three playstyles.

- Jump
- Stream
- Hybrid

The classification is based on the relationship between **aim strain** and **speed strain** calculated by **rosu-pp-py**.

---

## Classification Formula

```
ratio = speed_strain / aim_strain
```

Using the configured threshold:

```
ratio >= threshold
```

↓

```
Stream
```

```
ratio <= 1 / threshold
```

↓

```
Jump
```

Otherwise:

```
Hybrid
```

---

## Why This Matters

Traditional beatmap searches usually rely on star rating alone.

However, two beatmaps with identical star ratings may require completely different mechanical skills.

For example:

```
6.3★

Fast streams
```

and

```
6.3★

Wide jumps
```

are fundamentally different despite sharing the same star rating.

Playstyle filtering enables searches based on mechanical characteristics instead of overall difficulty.

---

# execution

The final section of every preset controls search execution itself.

Unlike previous sections, these values do **not** influence beatmap selection.

Instead, they define how the search process behaves.

Example:

```yaml
execution:
  target_count: 20
  auto_open: true
  max_pages: 50
  request_delay: 1.0
```

---

## target_count

```yaml
target_count: 20
```

Stops searching after the requested number of matching beatmaps has been found.

Larger values increase search time.

---

## auto_open

```yaml
auto_open: true
```

When enabled, downloaded `.osz` files are opened automatically using the operating system.

This triggers normal beatmap importing in an installed osu! client.

---

## max_pages

```yaml
max_pages: 50
```

Limits how many pages are requested from the official osu! API.

This prevents extremely broad searches from running indefinitely.

Increasing the value improves search coverage at the cost of additional API requests.

---

## request_delay

```yaml
request_delay: 1.0
```

Delay between consecutive requests to the official API.

This value helps avoid unnecessary rate limiting while remaining respectful to the osu! API infrastructure.

Most users should leave the default unchanged.

---

# Recommended Preset Examples

## Comfortable Practice

```yaml
pp:
  min: 180
  max: 240

star_rating:
  min: 5.5
  max: 6.2
```

Suitable for consistent practice sessions.

---

## Rank Push

```yaml
pp:
  min: 260
  max: 340

star_rating:
  min: 6.4
  max: 7.2
```

Targets maps slightly above the current comfort zone.

---

## Stream Practice

```yaml
playstyle:
  type: stream

length:
  min: 120

bpm:
  min: 190
```

Focuses on longer stream-oriented beatmaps.

---

## Farm Maps

```yaml
playstyle:
  type: jump

length:
  max: 140
```

Optimized for shorter jump-heavy maps that are commonly used for PP farming.

# Command Line Interface

osu-finder is designed around a small number of commands that cover the entire workflow.

Most users will only need a few of them during regular usage.

The typical lifecycle is:

```

Initialize → Create Preset → Search → Download

```

Advanced users can additionally generate presets from player profiles, manage blacklists, or switch between multiple search configurations.

---

# Command Overview

| Command | Description |
|----------|-------------|
| `osu-finder` | Run a search using the active preset |
| `osu-finder --run-search` | Explicitly start a search |
| `osu-finder --preset <name>` | Use a specific preset |
| `osu-finder --init` | Create the global configuration |
| `osu-finder --create-preset` | Create a preset interactively |
| `osu-finder -u <user>` | Generate a preset from a player's profile |
| `osu-finder --ban <beatmapset_id>` | Add a BeatmapSet to the blacklist |
| `osu-finder --help` | Display command help |

---

# Running Searches

## Default preset

If an active preset is configured:

```bash
osu-finder
```

or

```bash
osu-finder --run-search
```

Both commands perform exactly the same search.

The active preset is loaded from:

```yaml
active_preset: default
```

inside `config.yaml`.

---

## Using another preset

```bash
osu-finder --preset stream
```

Loads:

```
presets/stream.yaml
```

instead of the active preset.

This allows multiple search profiles without modifying the global configuration.

Example:

```bash
osu-finder --preset tournament
```

```bash
osu-finder --preset dt
```

```bash
osu-finder --preset farm
```

---

# Initial Setup

## Interactive initialization

```bash
osu-finder --init
```

Creates the initial configuration and guides the user through:

- OAuth credentials
- osu! Songs directory
- download directory
- mirror configuration
- network options

This command usually only needs to be executed once.

---

# Preset Management

## Create a new preset

```bash
osu-finder --create-preset
```

The interactive wizard asks for:

- base filters
- advanced filters
- execution settings
- mod combinations

A new YAML file is then created inside:

```
presets/
```

---

## Edit an existing preset

Presets are ordinary YAML files.

They can be edited using any text editor.

For example:

```
presets/default.yaml
```

```
presets/stream.yaml
```

```
presets/farm.yaml
```

No special command is required.

---

# Profile Analysis

One of osu-finder's most powerful features is automatic preset generation from player profiles.

Example:

```bash
osu-finder -u WhiteCat
```

The application will:

1. Resolve the player's user ID.
2. Download their top plays.
3. Analyze every beatmap locally.
4. Calculate statistical ranges.
5. Generate a new search preset.

The resulting preset can immediately be used for future searches.

---

## Using Numeric User IDs

Instead of a username, a numeric user ID may also be provided.

Example:

```bash
osu-finder -u 7562902
```

Both forms are supported.

---

# Focus Modes

The generated preset depends on the selected focus mode.

## balanced

```bash
osu-finder -u WhiteCat --focus balanced
```

Creates a general-purpose preset centered around the player's typical performance.

Recommended for most users.

---

## jump

```bash
osu-finder -u WhiteCat --focus jump
```

Prioritizes jump-oriented maps.

Typical characteristics include:

- wider spacing
- lower stream density
- balanced map length

---

## stream

```bash
osu-finder -u WhiteCat --focus stream
```

Generates filters favoring stream-heavy beatmaps.

The resulting preset generally prefers:

- higher BPM
- longer drain time
- stream-dominant maps

---

## push

```bash
osu-finder -u WhiteCat --focus push
```

Builds a preset slightly above the player's current comfort zone.

Useful for improving rank or mechanical skill.

---

## farm

```bash
osu-finder -u WhiteCat --focus farm
```

Attempts to generate a preset similar to commonly farmed beatmaps.

Typically favors:

- jump maps
- moderate length
- efficient PP gain

---

# Blacklist Management

Sometimes certain beatmaps should never appear in search results.

Example:

```bash
osu-finder --ban 1234567
```

The BeatmapSet ID is added to the global blacklist.

Future searches automatically skip it.

---

# Typical Examples

## Search using the default preset

```bash
osu-finder
```

---

## Search using a custom preset

```bash
osu-finder --preset stream
```

---

## Create a new preset

```bash
osu-finder --create-preset
```

---

## Analyze a player's profile

```bash
osu-finder -u mrekk
```

---

## Generate a stream practice preset

```bash
osu-finder -u mrekk --focus stream
```

---

## Generate a rank push preset

```bash
osu-finder -u mrekk --focus push
```

---

## Blacklist a BeatmapSet

```bash
osu-finder --ban 987654
```

---

# Exit Status

A successful search returns exit code:

```
0
```

Unexpected failures return a non-zero exit code.

Typical reasons include:

- invalid OAuth credentials
- network failures
- inaccessible beatmap mirror
- malformed configuration
- API authentication errors

---

# Logging

osu-finder provides informative console output throughout the search process.

Typical messages include:

- authentication
- page progress
- beatmaps analyzed
- local cache statistics
- downloads
- skipped beatmaps
- profile analysis progress

This output is intended to provide visibility into every stage of the search pipeline without overwhelming the user with unnecessary information.