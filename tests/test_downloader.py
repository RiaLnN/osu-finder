from pathlib import Path

import aiohttp
import pytest

from osu_finder.config import MirrorConfig, NetworkConfig
from osu_finder.downloader import Downloader, DownloaderError
from aioresponses import aioresponses

@pytest.fixture
def mirror():
    return MirrorConfig(
        base_url="https://mirror.test",
        osu_file_path="/osu/{id}",
        osz_download_path="/download/{id}",
    )


@pytest.fixture
def network():
    return NetworkConfig(
        proxy_url=None,
        fallback_to_direct=True,
    )


@pytest.fixture
def downloader(tmp_path, mirror, network):
    return Downloader(
        mirror=mirror,
        download_folder=tmp_path,
        network=network,
    )

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Normal Song", "Normal Song"),
        ("A<B>C", "A_B_C"),
        ('A"B"', "A_B_"),
        ("a:b", "a_b"),
        ("a/b", "a_b"),
        ("a\\b", "a_b"),
        ("a|b", "a_b"),
        ("a?b", "a_b"),
        ("a*b", "a_b"),
    ],
)
def test_sanitize_filename(raw, expected):
    assert Downloader._sanitize_filename(raw) == expected

def test_filename_truncated():
    text = "a" * 500

    result = Downloader._sanitize_filename(text)

    assert len(result) == 150


@pytest.mark.asyncio
async def test_download_osz_success(downloader):
    with aioresponses() as mocked:

        mocked.get(
            "https://mirror.test/download/123",
            body=b"dummy beatmap",
        )

        async with aiohttp.ClientSession() as session:

            path = await downloader.download_osz(
                session,
                beatmapset_id=123,
                filename_hint="Test Song",
            )

    assert path.exists()
    assert path.read_bytes() == b"dummy beatmap"


@pytest.mark.asyncio
async def test_download_filename(downloader):

    with aioresponses() as mocked:

        mocked.get(
            "https://mirror.test/download/15",
            body=b"abc",
        )

        async with aiohttp.ClientSession() as session:

            path = await downloader.download_osz(
                session,
                15,
                'A:B<C>',
            )

    assert path.name == "15 A_B_C_.osz"

@pytest.mark.asyncio
async def test_download_404(downloader):

    with aioresponses() as mocked:

        mocked.get(
            "https://mirror.test/download/99",
            status=404,
        )

        async with aiohttp.ClientSession() as session:

            with pytest.raises(DownloaderError):
                await downloader.download_osz(
                    session,
                    99,
                    "test",
                )


def test_open_windows(monkeypatch, tmp_path):

    called = {}

    def fake_startfile(path):
        called["path"] = path

    monkeypatch.setattr(
        "os.startfile",
        fake_startfile,
        raising=False,
    )

    monkeypatch.setattr(
        "sys.platform",
        "win32",
    )

    file = tmp_path / "a.osz"
    file.touch()

    Downloader.open_in_os(file)

    assert called["path"] == file

def test_open_linux(monkeypatch, tmp_path):

    calls = []

    def fake_run(cmd, check=False):
        calls.append(cmd)

    monkeypatch.setattr(
        "subprocess.run",
        fake_run,
    )

    monkeypatch.setattr(
        "sys.platform",
        "linux",
    )

    file = tmp_path / "map.osz"
    file.touch()

    Downloader.open_in_os(file)

    assert calls[0][0] == "xdg-open"

def test_open_mac(monkeypatch, tmp_path):

    calls = []

    def fake_run(cmd, check=False):
        calls.append(cmd)

    monkeypatch.setattr(
        "subprocess.run",
        fake_run,
    )

    monkeypatch.setattr(
        "sys.platform",
        "darwin",
    )

    file = tmp_path / "map.osz"
    file.touch()

    Downloader.open_in_os(file)

    assert calls[0][0] == "open"