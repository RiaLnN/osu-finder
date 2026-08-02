from pathlib import Path
import pytest
from osu_finder.local_cache import LocalCache
from osu_finder.local_cache import _SET_ID_PATTERN

def test_build_reads_valid_set_ids(tmp_path: Path):
    songs = tmp_path / "Songs"
    songs.mkdir()

    (songs / "123456 Artist - Song").mkdir()
    (songs / "654321 Camellia - Exit").mkdir()

    cache = LocalCache(songs).build()

    assert 123456 in cache
    assert 654321 in cache
    assert len(cache) == 2

def test_build_ignores_invalid_folders(tmp_path: Path):
    songs = tmp_path / "Songs"
    songs.mkdir()

    (songs / "hello").mkdir()
    (songs / "test").mkdir()
    (songs / "Artist - Song").mkdir()
    (songs / "123abc").mkdir()

    cache = LocalCache(songs).build()

    assert len(cache) == 0

def test_build_reads_only_valid_ids(tmp_path: Path):
    songs = tmp_path / "Songs"
    songs.mkdir()

    (songs / "123456 Artist").mkdir()
    (songs / "wrong").mkdir()
    (songs / "999999 Another").mkdir()

    cache = LocalCache(songs).build()

    assert len(cache) == 2
    assert 123456 in cache
    assert 999999 in cache

def test_blacklist_added_before_scan(tmp_path: Path):
    songs = tmp_path / "Songs"
    songs.mkdir()

    cache = LocalCache(songs, blacklist=[1, 2, 3]).build()

    assert 1 in cache
    assert 2 in cache
    assert 3 in cache

    assert len(cache) == 3

def test_add():
    cache = LocalCache(Path("."))

    cache.add(555)

    assert 555 in cache
    assert len(cache) == 1

def test_missing_folder():
    cache = LocalCache(Path("/this/path/does/not/exist")).build()

    assert len(cache) == 0


@pytest.mark.parametrize(
    ("folder", "expected"),
    [
        ("123456 Artist", 123456),
        ("1 A", 1),
        ("999999 Camellia", 999999),
        ("abc", None),
        ("123abc", None),
        ("abc123", None),
        ("123", None),
        ("", None),
    ],
)
def test_set_id_pattern(folder, expected):
    match = _SET_ID_PATTERN.match(folder)

    if expected is None:
        assert match is None
    else:
        assert int(match.group(1)) == expected # type: ignore