"""DestatisLocator.tablefile_fields (pinned and never-sent fields) and fetch_tablefile (the zip-kind check)."""

import dataclasses
from functools import partial
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from mloda_plugin_govdata.feature_groups.destatis.core.api import (
    PINNED_TABLEFILE_FIELDS,
    TABLEFILE_FIELDS,
    GenesisClient,
    fetch_tablefile,
)
from mloda_plugin_govdata.feature_groups.destatis.core.auth import DestatisCredentials
from mloda_plugin_govdata.feature_groups.destatis.core.cache import ParameterCache
from mloda_plugin_govdata.feature_groups.destatis.core.errors import GenesisUnknownEnvelope
from mloda_plugin_govdata.feature_groups.destatis.core.hosts import GENESIS_ONLINE
from mloda_plugin_govdata.feature_groups.destatis.locator import DestatisLocator

BASE = GENESIS_ONLINE.base_url
TOKEN = "t0kenAbCdEf0123456789abcdef012345"
ZIP_BODY = b"PK\x03\x04" + b"\x00" * 16 + b"ffcsv-payload"

NOT_CALLER_CONFIGURABLE = {"area", "compress", "transpose", "timeslices", "job", "stand"}
NEVER_SENT = {"area", "stand", "timeslices"}


def _client(tmp_path: Path) -> GenesisClient:
    return GenesisClient(GENESIS_ONLINE, DestatisCredentials(token=TOKEN), lock_dir=tmp_path)


def test_minimal_selection_sends_only_the_pinned_fields() -> None:
    assert DestatisLocator("12411-0015").tablefile_fields() == {
        "name": "12411-0015",
        "language": "de",
        "format": "ffcsv",
        "job": "false",
        "compress": "false",
        "transpose": "false",
        "quality": "off",
    }


def test_full_selection_field_set_and_pinned_values() -> None:
    fields = DestatisLocator(
        "12411-0015",
        regionalvariable="DLAND",
        regionalkey=("02", "01"),
        classifyingvariable1="GES",
        classifyingkey1=("W", "M"),
        classifyingvariable2="ALT",
        classifyingkey2=("U18",),
        classifyingvariable3="X3",
        classifyingkey3=("k3",),
        classifyingvariable4="X4",
        classifyingkey4=("k4",),
        classifyingvariable5="X5",
        classifyingkey5=("k5",),
        contents=("BEVSTD",),
        startyear=2015,
        endyear=2022,
        quality=True,
    ).tablefile_fields()
    assert fields == {
        "name": "12411-0015",
        "regionalvariable": "DLAND",
        "regionalkey": ("02", "01"),
        "classifyingvariable1": "GES",
        "classifyingkey1": ("W", "M"),
        "classifyingvariable2": "ALT",
        "classifyingkey2": ("U18",),
        "classifyingvariable3": "X3",
        "classifyingkey3": ("k3",),
        "classifyingvariable4": "X4",
        "classifyingkey4": ("k4",),
        "classifyingvariable5": "X5",
        "classifyingkey5": ("k5",),
        "contents": ("BEVSTD",),
        "startyear": 2015,
        "endyear": 2022,
        "language": "de",
        "format": "ffcsv",
        "job": "false",
        "compress": "false",
        "transpose": "false",
        "quality": "on",
    }
    assert set(fields) <= TABLEFILE_FIELDS  # never a name outside the spec's tablefile body
    assert NEVER_SENT.isdisjoint(fields)


def test_area_compress_transpose_timeslices_job_stand_are_not_locator_fields() -> None:
    # docs/destatis-options.md: a caller cannot send anything but the pinned value, or nothing, for these.
    names = {f.name for f in dataclasses.fields(DestatisLocator)}
    assert NOT_CALLER_CONFIGURABLE.isdisjoint(names)
    # tablefile_fields() sends every locator field but host, so each must be a tablefile field and none pinned.
    assert names - {"host"} <= TABLEFILE_FIELDS
    assert names.isdisjoint(PINNED_TABLEFILE_FIELDS)


@respx.mock
def test_fetch_tablefile_returns_the_zip_body(tmp_path: Path) -> None:
    respx.post(BASE + "data/tablefile").mock(
        return_value=httpx.Response(200, content=ZIP_BODY, headers={"content-type": "application/octet-stream"})
    )
    with _client(tmp_path) as client:
        body = fetch_tablefile(client, {"name": "12411-0015", "format": "ffcsv", "language": "de"})
    assert body == ZIP_BODY


@respx.mock
def test_fetch_tablefile_raises_on_a_non_zip_reply(tmp_path: Path) -> None:
    respx.post(BASE + "data/tablefile").mock(
        return_value=httpx.Response(
            200,
            json={
                "Ident": {"Service": "data", "Method": "tablefile"},
                "Status": {"Code": 0, "Content": "erfolgreich", "Type": "Information"},
            },
        )
    )
    with _client(tmp_path) as client, pytest.raises(GenesisUnknownEnvelope, match="did not answer with a zip"):
        fetch_tablefile(client, {"name": "12411-0015", "format": "ffcsv", "language": "de"})


@respx.mock
def test_tablefile_fields_round_trip_through_parameter_cache(tmp_path: Path) -> None:
    # The intended composition: tablefile_fields() builds `fields`, ParameterCache.get_or_fetch
    # canonicalizes them and calls `fetch` (fetch_tablefile bound to a client) only on a miss.
    route = respx.post(BASE + "data/tablefile").mock(
        return_value=httpx.Response(200, content=ZIP_BODY, headers={"content-type": "application/octet-stream"})
    )
    fields = DestatisLocator("12411-0015", regionalkey=("02", "01"), quality=True).tablefile_fields()
    cache = ParameterCache(tmp_path / "cache")
    with _client(tmp_path) as client:
        fetch = partial(fetch_tablefile, client)
        cached = cache.get_or_fetch(GENESIS_ONLINE, "data/tablefile", fields, fetch)
        cache.get_or_fetch(GENESIS_ONLINE, "data/tablefile", fields, fetch)  # cache hit, no second POST
    assert cached.path.read_bytes() == ZIP_BODY
    assert route.calls.call_count == 1
    sent = parse_qs(route.calls.last.request.content.decode("utf-8"))
    assert sent["regionalkey"] == ["01,02"]  # canonicalized: sorted, comma-joined
    assert sent["quality"] == ["on"]
