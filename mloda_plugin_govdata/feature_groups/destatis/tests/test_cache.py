"""ParameterCache: request-keyed storage, credential-free keys and meta, staleness warning, corruption recovery."""

import hashlib
import json
import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from mloda_plugin_govdata.feature_groups.destatis.core.api import GenesisClient
from mloda_plugin_govdata.feature_groups.destatis.core.auth import DestatisCredentials
from mloda_plugin_govdata.feature_groups.destatis.core.cache import (
    STALE_AFTER,
    CachedPayload,
    ParameterCache,
    canonical_parameters,
)
from mloda_plugin_govdata.feature_groups.destatis.core.hosts import GENESIS_ONLINE, REGIONALSTATISTIK, GenesisHost
from mloda_plugin_govdata.feature_groups.govdata.core.cache import DownloadCache

ENDPOINT = "data/tablefile"
BASE = GENESIS_ONLINE.base_url
TOKEN = "t0kenAbCdEf0123456789abcdef012345"
PASSWORD = "p4ss w0rd?&="
ZIP = b"PK\x03\x04" + b"\x00" * 16 + b"ffcsv-payload"
PARAMS: dict[str, object] = {
    "name": "12411-0015",
    "regionalkey": ["01", "02", "03"],
    "startyear": 2020,
    "endyear": 2022,
    "quality": "off",
    "language": "de",
    "format": "ffcsv",
}
CANONICAL = {
    "name": "12411-0015",
    "regionalkey": "01,02,03",
    "startyear": "2020",
    "endyear": "2022",
    "quality": "off",
    "language": "de",
    "format": "ffcsv",
}
T0 = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self, now: datetime = T0) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class Fetcher:
    """Counts calls, records the wire mapping, and hands out the next body; stands in for the GENESIS POST."""

    def __init__(self, *bodies: bytes) -> None:
        self.bodies = list(bodies) or [ZIP]
        self.calls = 0
        self.wire: list[Mapping[str, str]] = []

    def __call__(self, wire: Mapping[str, str]) -> bytes:
        self.calls += 1
        self.wire.append(dict(wire))
        return self.bodies[min(self.calls, len(self.bodies)) - 1]


def _meta_text(cache: ParameterCache, params: dict[str, object] = PARAMS) -> str:
    return cache._meta_path(cache.key(GENESIS_ONLINE, ENDPOINT, params)).read_text(encoding="utf-8")


def test_canonical_parameters_are_the_wire_form() -> None:
    raw: dict[str, object] = {
        "name": " 12411-0015 ",
        "startyear": 2020,
        "endyear": "2022",
        "regionalkey": " 02, 01 ,",
        "classifyingkey1": {"B", "A"},
        "classifyingkey2": ["10", "09"],
        "contents": ["BEVSTD", "AAA"],
        "area": None,
        "regionalvariable": "01",
        "timeslices": 3,
        "stand": "",
        "language": "de",
        "username": TOKEN,
        "Password": PASSWORD,
    }
    assert canonical_parameters(ENDPOINT, raw) == {
        "name": "12411-0015",
        "startyear": "2020",
        "endyear": "2022",
        "regionalkey": "01,02",
        "classifyingkey1": "A,B",
        "classifyingkey2": "09,10",
        "contents": "BEVSTD,AAA",  # not a selection field: the caller's order stays
        "regionalvariable": "01",
        "timeslices": "3",
        "stand": "",
        "language": "de",
    }
    canonical = canonical_parameters(ENDPOINT, raw)
    assert canonical_parameters(ENDPOINT, canonical) == canonical  # idempotent


def test_undeclared_or_missing_fields_are_refused_by_name() -> None:
    with pytest.raises(ValueError, match="does not declare 'token'") as info:
        canonical_parameters(ENDPOINT, dict(PARAMS, token=TOKEN))
    assert TOKEN not in str(info.value)
    with pytest.raises(ValueError, match="does not declare 'user'"):
        canonical_parameters(ENDPOINT, dict(PARAMS, user="someone"))
    with pytest.raises(ValueError, match="'language' must be passed explicitly"):
        canonical_parameters(ENDPOINT, {k: v for k, v in PARAMS.items() if k != "language"})
    with pytest.raises(ValueError, match="Unknown GENESIS operation"):
        canonical_parameters("data/table", PARAMS)
    assert canonical_parameters("helloworld/whoami", {}) == {}


@pytest.mark.parametrize(
    ("name", "bad"),
    [
        *(("startyear", bad) for bad in (True, 2020.0, {"a": 1}, [["01"]], b"01")),
        # An int only fits the numeric fields; anywhere else it would drop a leading zero.
        ("regionalkey", 1234567),
        ("classifyingkey2", ["10", 1234567]),
        ("contents", [1234567]),
        ("name", 1234567),
    ],
)
def test_unsupported_values_are_refused_by_field_name(name: str, bad: object) -> None:
    with pytest.raises(TypeError) as info:
        canonical_parameters(ENDPOINT, dict(PARAMS, **{name: bad}))
    assert f"'{name}'" in str(info.value)
    assert "01" not in str(info.value) and "1234567" not in str(info.value)


def test_key_is_stable_under_reordering_and_changes_per_parameter(tmp_path: Path) -> None:
    cache = ParameterCache(tmp_path)
    key = cache.key(GENESIS_ONLINE, ENDPOINT, PARAMS)
    reordered = dict(reversed(list(PARAMS.items())))
    reordered["regionalkey"] = "03,01,02"
    stringly = dict(PARAMS, startyear="2020", endyear=" 2022 ")
    assert key.startswith("post-") and len(key) == len("post-") + 64
    assert cache.key("genesis", ENDPOINT, reordered) == key
    assert cache.key(GENESIS_ONLINE, ENDPOINT, stringly) == key
    assert cache.key(GENESIS_ONLINE, ENDPOINT, CANONICAL) == key
    assert cache.key(GENESIS_ONLINE, ENDPOINT, dict(PARAMS, endyear=2023)) != key
    assert cache.key(GENESIS_ONLINE, ENDPOINT, dict(PARAMS, regionalkey=["01", "02"])) != key
    assert cache.key(GENESIS_ONLINE, ENDPOINT, dict(PARAMS, quality="on")) != key
    assert cache.key(GENESIS_ONLINE, ENDPOINT, dict(PARAMS, language="en")) != key
    assert cache.key(GENESIS_ONLINE, ENDPOINT, dict(PARAMS, contents="B,A")) != cache.key(
        GENESIS_ONLINE, ENDPOINT, dict(PARAMS, contents="A,B")
    )
    assert cache.key(GENESIS_ONLINE, "metadata/table", {"name": "12411-0015", "language": "de"}) != key
    assert cache.key(REGIONALSTATISTIK, ENDPOINT, PARAMS) != key
    same_server = GenesisHost("other", GENESIS_ONLINE.base_url, "OTHER", "https://x.example/", "Other")
    assert cache.key(same_server, ENDPOINT, PARAMS) == key


def test_credentials_never_reach_key_or_meta(tmp_path: Path) -> None:
    cache = ParameterCache(tmp_path)
    with_secrets = dict(PARAMS, username=TOKEN, password=PASSWORD)
    assert cache.key(GENESIS_ONLINE, ENDPOINT, with_secrets) == cache.key(GENESIS_ONLINE, ENDPOINT, PARAMS)
    stored = cache.store(GENESIS_ONLINE, ENDPOINT, with_secrets, ZIP)
    meta = _meta_text(cache)
    for secret in (TOKEN, PASSWORD, "username", "password"):
        assert secret.lower() not in meta.lower()
        assert secret.lower() not in repr(stored).lower()
    assert json.loads(meta)["parameters"] == CANONICAL
    # A secret under any other name is refused before anything is written.
    with pytest.raises(ValueError):
        cache.store(GENESIS_ONLINE, ENDPOINT, dict(PARAMS, token=TOKEN), ZIP)
    assert len(list(tmp_path.iterdir())) == 2


def test_store_and_lookup_round_trip(tmp_path: Path) -> None:
    cache = ParameterCache(tmp_path, clock=Clock())
    assert cache.lookup(GENESIS_ONLINE, ENDPOINT, PARAMS) is None
    stored = cache.store(GENESIS_ONLINE, ENDPOINT, PARAMS, ZIP)
    found = cache.lookup("genesis", ENDPOINT, PARAMS)
    assert isinstance(found, CachedPayload) and found == stored and hash(found) == hash(stored)
    assert found.path.read_bytes() == ZIP and found.path.name == f"post-{hashlib.sha256(ZIP).hexdigest()}.bin"
    assert found.sha256 == hashlib.sha256(ZIP).hexdigest()
    assert found.retrieved_at == T0 and found.host is GENESIS_ONLINE and found.endpoint == ENDPOINT
    assert found.parameters == CANONICAL
    meta = json.loads(_meta_text(cache))
    assert meta["retrieved_at"] == T0.isoformat() and meta["host"] == "genesis" and meta["endpoint"] == ENDPOINT
    assert meta["data_file"] == found.path.name and meta["sha256"] == found.sha256 and meta["parameters"] == CANONICAL
    assert not list(tmp_path.glob("*.tmp"))
    # A second instance over the same directory sees the entry.
    assert ParameterCache(tmp_path, clock=Clock()).lookup(GENESIS_ONLINE, ENDPOINT, CANONICAL) == stored


def test_entries_do_not_mix_and_non_ascii_values_round_trip(tmp_path: Path) -> None:
    cache = ParameterCache(tmp_path)
    umlaut = dict(PARAMS, contents="Bevölkerung ü", stand="")
    a = cache.store(GENESIS_ONLINE, ENDPOINT, PARAMS, ZIP)
    b = cache.store(GENESIS_ONLINE, ENDPOINT, umlaut, ZIP + b"-b")
    assert cache.lookup(GENESIS_ONLINE, ENDPOINT, PARAMS) == a
    assert cache.lookup(GENESIS_ONLINE, ENDPOINT, umlaut) == b
    assert b.parameters["contents"] == "Bevölkerung ü" and b.parameters["stand"] == ""
    assert cache.key(GENESIS_ONLINE, ENDPOINT, dict(PARAMS, stand="")) != cache.key(GENESIS_ONLINE, ENDPOINT, PARAMS)


def test_hit_wins_without_fetch_and_refresh_bypasses(tmp_path: Path) -> None:
    cache = ParameterCache(tmp_path)
    fetch = Fetcher(ZIP, ZIP + b"-v2")
    first = cache.get_or_fetch(GENESIS_ONLINE, ENDPOINT, PARAMS, fetch)
    second = cache.get_or_fetch(GENESIS_ONLINE, ENDPOINT, PARAMS, fetch)
    assert fetch.calls == 1 and second == first
    assert fetch.wire == [CANONICAL]  # fetch receives the mapping that keyed the entry
    third = cache.get_or_fetch(GENESIS_ONLINE, ENDPOINT, PARAMS, fetch, refresh=True)
    assert fetch.calls == 2 and third.path.read_bytes() == ZIP + b"-v2" and third.sha256 != first.sha256
    fourth = cache.get_or_fetch(GENESIS_ONLINE, ENDPOINT, PARAMS, fetch)
    assert fetch.calls == 2 and fourth == third
    fresh = Fetcher()
    assert ParameterCache(tmp_path).get_or_fetch(REGIONALSTATISTIK, ENDPOINT, PARAMS, fresh, refresh=True).path.exists()
    assert fresh.calls == 1


def test_failed_or_empty_fetch_keeps_the_entry(tmp_path: Path) -> None:
    cache = ParameterCache(tmp_path)
    first = cache.get_or_fetch(GENESIS_ONLINE, ENDPOINT, PARAMS, Fetcher())

    def broken(wire: Mapping[str, str]) -> bytes:
        raise httpx.ConnectError("down")

    with pytest.raises(httpx.ConnectError):
        cache.get_or_fetch(GENESIS_ONLINE, ENDPOINT, PARAMS, broken, refresh=True)
    with pytest.raises(ValueError, match="empty"):
        cache.get_or_fetch(GENESIS_ONLINE, ENDPOINT, PARAMS, Fetcher(b""), refresh=True)
    assert cache.lookup(GENESIS_ONLINE, ENDPOINT, PARAMS) == first


def test_stale_hit_warns_naming_table_and_age(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    clock = Clock()
    cache = ParameterCache(tmp_path, clock=clock)
    fetch = Fetcher()
    with caplog.at_level(logging.WARNING):
        cache.get_or_fetch(GENESIS_ONLINE, ENDPOINT, PARAMS, fetch)
        clock.now = T0 + STALE_AFTER
        cache.get_or_fetch(GENESIS_ONLINE, ENDPOINT, PARAMS, fetch)
    assert caplog.records == [] and fetch.calls == 1

    clock.now = T0 + STALE_AFTER + timedelta(days=3, hours=1)
    with caplog.at_level(logging.WARNING):
        cache.get_or_fetch(GENESIS_ONLINE, ENDPOINT, PARAMS, fetch)
    assert fetch.calls == 1
    (record,) = caplog.records
    message = record.getMessage()
    assert "table 12411-0015" in message and "33 days" in message and "refresh=True" in message

    caplog.clear()
    with caplog.at_level(logging.WARNING):
        cache.get_or_fetch(GENESIS_ONLINE, ENDPOINT, PARAMS, fetch, refresh=True)
    assert fetch.calls == 2 and caplog.records == []


def test_stale_warning_names_endpoint_without_a_table(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    clock = Clock()
    cache = ParameterCache(tmp_path, clock=clock)
    cache.store(GENESIS_ONLINE, "catalogue/qualitysigns", {"language": "de"}, b"{}")
    clock.now = T0 + timedelta(days=40)
    with caplog.at_level(logging.WARNING):
        assert cache.lookup(GENESIS_ONLINE, "catalogue/qualitysigns", {"language": "de"}) is not None
    assert "catalogue/qualitysigns reply is 40 days old" in caplog.text


def test_naive_clock_is_refused(tmp_path: Path) -> None:
    cache = ParameterCache(tmp_path, clock=lambda: T0.replace(tzinfo=None))
    with pytest.raises(ValueError, match="naive"):
        cache.store(GENESIS_ONLINE, ENDPOINT, PARAMS, ZIP)


def test_corrupted_or_unreadable_body_is_fetched_again(tmp_path: Path) -> None:
    cache = ParameterCache(tmp_path)
    fetch = Fetcher()
    first = cache.get_or_fetch(GENESIS_ONLINE, ENDPOINT, PARAMS, fetch)
    first.path.write_bytes(b"corrupted")
    assert cache.lookup(GENESIS_ONLINE, ENDPOINT, PARAMS) is None
    second = cache.get_or_fetch(GENESIS_ONLINE, ENDPOINT, PARAMS, fetch)
    assert fetch.calls == 2 and second.path.read_bytes() == ZIP
    second.path.unlink()
    assert cache.lookup(GENESIS_ONLINE, ENDPOINT, PARAMS) is None
    second.path.mkdir()  # a directory where the body should be
    assert cache.lookup(GENESIS_ONLINE, ENDPOINT, PARAMS) is None
    second.path.rmdir()
    cache.get_or_fetch(GENESIS_ONLINE, ENDPOINT, PARAMS, fetch)
    assert fetch.calls == 3


@pytest.mark.parametrize(
    "damage",
    [
        lambda meta: b"{ not valid json",
        lambda meta: b"\xff\xfe not utf-8",
        lambda meta: json.dumps([meta]).encode(),
        lambda meta: json.dumps({k: v for k, v in meta.items() if k != "retrieved_at"}).encode(),
        lambda meta: json.dumps(dict(meta, retrieved_at="2026-01-01T00:00:00")).encode(),
        lambda meta: json.dumps(dict(meta, sha256="not-a-hash")).encode(),
    ],
    ids=["unreadable", "not-utf8", "not-an-object", "no-timestamp", "naive-timestamp", "bad-hash"],
)
def test_damaged_meta_is_a_miss(tmp_path: Path, damage: Callable[[dict[str, Any]], bytes]) -> None:
    cache = ParameterCache(tmp_path)
    fetch = Fetcher()
    cache.get_or_fetch(GENESIS_ONLINE, ENDPOINT, PARAMS, fetch)
    meta_path = cache._meta_path(cache.key(GENESIS_ONLINE, ENDPOINT, PARAMS))
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta_path.write_bytes(damage(meta))
    assert cache.lookup(GENESIS_ONLINE, ENDPOINT, PARAMS) is None
    second = cache.get_or_fetch(GENESIS_ONLINE, ENDPOINT, PARAMS, fetch)
    assert fetch.calls == 2 and second.path.read_bytes() == ZIP


def test_meta_data_file_is_not_trusted(tmp_path: Path) -> None:
    cache = ParameterCache(tmp_path)
    stored = cache.store(GENESIS_ONLINE, ENDPOINT, PARAMS, ZIP)
    meta_path = cache._meta_path(stored.key)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["data_file"] = "../outside.bin"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    found = cache.lookup(GENESIS_ONLINE, ENDPOINT, PARAMS)
    assert found is not None and found.path == stored.path and found.path.parent == tmp_path


@respx.mock
def test_shares_the_directory_with_the_get_cache_without_collisions(tmp_path: Path) -> None:
    url = "https://example.org/data.bin"
    respx.get(url).mock(return_value=httpx.Response(200, content=ZIP))
    with DownloadCache(tmp_path) as get_cache:
        got = get_cache.get_or_download(url)
        get_meta = get_cache._meta_path(url).name
    posted = ParameterCache(tmp_path).store(GENESIS_ONLINE, ENDPOINT, PARAMS, ZIP)
    assert got.sha256 == posted.sha256 and got.path != posted.path
    names = {p.name for p in tmp_path.iterdir()}
    post_files = {posted.path.name, f"{posted.key}.meta.json"}
    assert names == {got.path.name, get_meta} | post_files
    assert {n for n in names if n.startswith("post-")} == post_files


def test_hit_makes_zero_http_calls_and_needs_no_credentials(tmp_path: Path) -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.post(BASE + ENDPOINT).mock(return_value=httpx.Response(200, content=ZIP))
        cache = ParameterCache(tmp_path)
        with GenesisClient(GENESIS_ONLINE, DestatisCredentials(token=TOKEN), lock_dir=tmp_path, environ={}) as client:
            first = cache.get_or_fetch(GENESIS_ONLINE, ENDPOINT, PARAMS, lambda wire: client.call(ENDPOINT, wire).body)
            second = cache.get_or_fetch(GENESIS_ONLINE, ENDPOINT, PARAMS, lambda wire: client.call(ENDPOINT, wire).body)
        assert route.call_count == 1 and second == first and first.path.read_bytes() == ZIP
        sent = httpx.QueryParams(route.calls.last.request.content.decode())
        assert dict(sent) == CANONICAL  # what was keyed is what went over the wire
        # A hit never resolves credentials: the client below has none and would raise on any request.
        with GenesisClient(GENESIS_ONLINE, lock_dir=tmp_path, environ={}) as anonymous:
            third = cache.get_or_fetch(
                GENESIS_ONLINE, ENDPOINT, PARAMS, lambda wire: anonymous.call(ENDPOINT, wire).body
            )
        assert route.call_count == 1 and third == first
