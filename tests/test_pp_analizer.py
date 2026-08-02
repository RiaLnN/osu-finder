import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from osu_finder.pp_analyzer import PpAnalyzer
from osu_finder.config import MirrorConfig, NetworkConfig


@pytest.fixture
def dummy_mirror():
    return MirrorConfig(base_url="https://mirror.test")


@pytest.fixture
def dummy_network():
    return NetworkConfig(proxy_url=None, fallback_to_direct=True)


@pytest.fixture
def analyzer(dummy_mirror, dummy_network):
    return PpAnalyzer(dummy_mirror, dummy_network)


@pytest.mark.parametrize(
    ("aim", "speed", "threshold", "expected"),
    [
        (10, 5, 1.15, "jump"),
        (5, 10, 1.15, "stream"),
        (10, 10, 1.15, "hybrid"),
        (0, 0, 1.15, "hybrid"),
        (0, 10, 1.15, "stream"),
        (10, 0, 1.15, "jump"),
    ],
)
def test_classify_playstyle(aim, speed, threshold, expected):
    assert PpAnalyzer._classify_playstyle(aim, speed, threshold) == expected


def test_threshold_boundary():
    assert PpAnalyzer._classify_playstyle(100, 115, 1.15) == "stream"
    assert PpAnalyzer._classify_playstyle(100, 114.9, 1.15) == "hybrid"


def test_estimate_ar_dt():
    assert PpAnalyzer.estimate_ar(9, ["DT"]) > 9


def test_estimate_ar_hr():
    assert PpAnalyzer.estimate_ar(9, ["HR"]) > 9


def test_estimate_ar_ez():
    assert PpAnalyzer.estimate_ar(9, ["EZ"]) < 9


def test_estimate_ar_nm():
    assert PpAnalyzer.estimate_ar(9, ["NM"]) == pytest.approx(9, abs=0.01)


def test_analyze_valid_beatmap(analyzer):
    map_path = (
        Path(__file__).parent
        / "data"
        / "beatmaps"
        / "MIMI feat. Hatsune Miku - Ai no Sukima (Log Off Now) [Light Insane].osu"
    )
    
    if not map_path.exists():
        pytest.skip(f"Test beatmap not found at {map_path}")

    content = map_path.read_text(encoding="utf8")
    
    nm = analyzer.analyze(
        osu_content=content,
        beatmap_id=1988751,
        version="Light Insane",
        api_bpm=204,
        api_hit_length=67,
        mods=["NM"],
        accuracy=99,
        playstyle_threshold=1.15,
    )
    
    assert nm is not None
    assert nm.star_rating > 0
    assert nm.pp > 0
    assert nm.ar > 0
    assert nm.clock_rate == 1

    dt = analyzer.analyze(
        osu_content=content,
        beatmap_id=1988751,
        version="Light Insane",
        api_bpm=204,
        api_hit_length=67,
        mods=["DT"],
        accuracy=99,
        playstyle_threshold=1.15,
    )
    
    assert dt is not None
    assert dt.clock_rate > nm.clock_rate
    assert dt.bpm > nm.bpm
    assert dt.length_seconds < nm.length_seconds


@patch("osu_finder.pp_analyzer.rosu.Beatmap")
def test_analyze_skips_suspicious(mock_beatmap, analyzer):
    fake = MagicMock()
    fake.is_suspicious.return_value = True
    mock_beatmap.return_value = fake

    result = analyzer.analyze(
        osu_content="dummy",
        beatmap_id=1,
        version="Test",
        api_bpm=180,
        api_hit_length=120,
        mods=["NM"],
        accuracy=99,
        playstyle_threshold=1.15,
    )

    assert result is None