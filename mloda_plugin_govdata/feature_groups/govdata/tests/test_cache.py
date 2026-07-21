"""Level 1: content-addressed download cache and conditional GET."""

import hashlib
from pathlib import Path

import httpx
import respx

from mloda_plugin_govdata.feature_groups.govdata.core.cache import DownloadCache

URL = "https://example.org/data.csv"
BODY = b"Stichtag;Wert\r\n30.06.2020;1\r\n"
ETAG = '"v1"'


@respx.mock
def test_download_and_store(tmp_path: Path) -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, content=BODY, headers={"ETag": ETAG}))
    with DownloadCache(tmp_path) as cache:
        cached = cache.get_or_download(URL)
    assert cached.path.read_bytes() == BODY
    assert cached.sha256 == hashlib.sha256(BODY).hexdigest()
    assert cached.etag == ETAG


@respx.mock
def test_conditional_get_reuses_on_304(tmp_path: Path) -> None:
    calls: dict[str, int] = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if request.headers.get("If-None-Match") == ETAG:
            return httpx.Response(304)
        return httpx.Response(200, content=BODY, headers={"ETag": ETAG})

    respx.get(URL).mock(side_effect=handler)
    with DownloadCache(tmp_path) as cache:
        first = cache.get_or_download(URL)
        second = cache.get_or_download(URL)
    assert calls["n"] == 2  # second call revalidated and got a 304
    assert first.sha256 == second.sha256
    assert second.path.read_bytes() == BODY


@respx.mock
def test_corrupted_cache_redownloads(tmp_path: Path) -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, content=BODY, headers={"ETag": ETAG}))
    with DownloadCache(tmp_path) as cache:
        first = cache.get_or_download(URL)
        first.path.write_bytes(b"corrupted")  # tamper the stored body
        second = cache.get_or_download(URL)
    assert second.path.read_bytes() == BODY


@respx.mock
def test_unreadable_metadata_redownloads(tmp_path: Path) -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, content=BODY, headers={"ETag": ETAG}))
    with DownloadCache(tmp_path) as cache:
        cache.get_or_download(URL)
        cache._meta_path(URL).write_text("{ not valid json", encoding="utf-8")  # truncated write
        second = cache.get_or_download(URL)
    assert second.path.read_bytes() == BODY
