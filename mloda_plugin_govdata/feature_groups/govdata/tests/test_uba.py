"""Tests for the UBA Air Data reader: Level 1 (flatten / URL), Level 2 (recorded), Level 3 (live)."""

import json
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pyarrow as pa
import pytest
import respx
from hypothesis import given
from hypothesis import strategies as st
from mloda.user import Feature, mloda

from mloda_plugin_govdata.feature_groups.govdata.uba import (
    OPTION_UBA_COMPONENT,
    OPTION_UBA_DATE_FROM,
    OPTION_UBA_DATE_TO,
    OPTION_UBA_LANG,
    OPTION_UBA_SCOPE,
    OPTION_UBA_STATION,
    OPTION_UBA_TIME_FROM,
    OPTION_UBA_TIME_TO,
    UBA_AIR_BASE,
    UbaAirReader,
    parse_uba_measures_bytes,
    uba_measures_url,
)

MEASURE_COLUMNS = ["station_id", "date_start", "component_id", "scope_id", "value", "date_end", "index"]
INDICES = {"data": {"station id": {"date start": ["component id", "scope id", "value", "date end", "index"]}}}


def _demo_url() -> str:
    return uba_measures_url(station=143, component=3, scope=2, date_from="2025-01-01", date_to="2025-01-01")


def _demo_options() -> dict[str, Any]:
    return {
        UbaAirReader.__name__: True,
        OPTION_UBA_STATION: 143,
        OPTION_UBA_COMPONENT: 3,
        OPTION_UBA_SCOPE: 2,
        OPTION_UBA_DATE_FROM: "2025-01-01",
        OPTION_UBA_DATE_TO: "2025-01-01",
    }


# --- Level 1: URL builder ---------------------------------------------------------------


def test_uba_measures_url_is_exact_and_ordered() -> None:
    # Assert the full string: param order is fixed, which keeps the cache key stable.
    expected = (
        f"{UBA_AIR_BASE}/measures/json?"
        "date_from=2025-01-01&time_from=1&date_to=2025-01-01&time_to=24"
        "&station=143&component=3&scope=2&lang=en"
    )
    assert _demo_url() == expected


# --- Level 1: flatten -------------------------------------------------------------------


def test_flatten_real_fixture(fixtures_dir: Path) -> None:
    table = parse_uba_measures_bytes((fixtures_dir / "uba_measures.json").read_bytes())
    assert table.schema.names == MEASURE_COLUMNS
    assert table.num_rows == 24
    assert table.column("station_id").to_pylist()[0] == 143
    assert table.column("date_start").to_pylist()[0] == "2025-01-01 00:00:00"
    assert table.column("date_end").to_pylist()[0] == "2025-01-01 01:00:00"
    assert table.column("component_id").to_pylist()[0] == 3
    assert table.column("scope_id").to_pylist()[0] == 2
    assert table.column("value").to_pylist()[0] == 37.0
    assert table.column("index").to_pylist()[0] == 2
    assert table.schema.field("station_id").type == pa.int64()
    assert table.schema.field("value").type == pa.float64()


def test_flatten_multi_station() -> None:
    payload = {
        "indices": INDICES,
        "data": {
            "143": {"2025-01-01 00:00:00": [3, 2, 37, "2025-01-01 01:00:00", "2"]},
            "144": {"2025-01-01 00:00:00": [3, 2, 40, "2025-01-01 01:00:00", "3"]},
        },
    }
    table = parse_uba_measures_bytes(json.dumps(payload).encode())
    assert table.num_rows == 2
    assert set(table.column("station_id").to_pylist()) == {143, 144}


def test_flatten_handles_null_value_and_index() -> None:
    payload = {"indices": INDICES, "data": {"143": {"2025-01-01 00:00:00": [3, 2, None, "2025-01-01 01:00:00", None]}}}
    table = parse_uba_measures_bytes(json.dumps(payload).encode())
    assert table.column("value").to_pylist() == [None]
    assert table.column("index").to_pylist() == [None]


def test_flatten_without_indices_uses_canonical_schema() -> None:
    # The schema is canonical and does not depend on the response self-describing its layout.
    payload = {"data": {"143": {"2025-01-01 00:00:00": [3, 2, 37, "2025-01-01 01:00:00", "2"]}}}
    table = parse_uba_measures_bytes(json.dumps(payload).encode())
    assert table.schema.names == MEASURE_COLUMNS
    assert table.column("value").to_pylist() == [37.0]


def test_flatten_keeps_canonical_names_for_localized_labels() -> None:
    # Even if the server sends localized labels, the public column names stay canonical.
    localized = {"data": {"Stationskennung": {"Startdatum": ["Komponente", "Bereich", "Wert", "Enddatum", "Index"]}}}
    payload = {"indices": localized, "data": {"143": {"2025-01-01 00:00:00": [3, 2, 37, "2025-01-01 01:00:00", "2"]}}}
    table = parse_uba_measures_bytes(json.dumps(payload).encode())
    assert table.schema.names == MEASURE_COLUMNS
    assert table.schema.field("value").type == pa.float64()


def test_flatten_rejects_changed_leaf_layout() -> None:
    # A different leaf width would shift columns under positional mapping; reject it loudly.
    changed = {"data": {"station id": {"date start": ["component id", "scope id", "value", "date end"]}}}
    payload = {"indices": changed, "data": {"143": {"2025-01-01 00:00:00": [3, 2, 37, "2025-01-01 01:00:00"]}}}
    with pytest.raises(ValueError):
        parse_uba_measures_bytes(json.dumps(payload).encode())


def test_flatten_rejects_payload_without_data() -> None:
    with pytest.raises(ValueError):
        parse_uba_measures_bytes(b'{"request": {}}')


def test_flatten_empty_data_yields_zero_rows() -> None:
    table = parse_uba_measures_bytes(json.dumps({"indices": INDICES, "data": {}}).encode())
    assert table.num_rows == 0
    assert table.schema.names == MEASURE_COLUMNS


def test_flatten_skips_non_dict_station() -> None:
    payload = {
        "indices": INDICES,
        "data": {"143": {"2025-01-01 00:00:00": [3, 2, 37, "2025-01-01 01:00:00", "2"]}, "999": None},
    }
    table = parse_uba_measures_bytes(json.dumps(payload).encode())
    assert table.column("station_id").to_pylist() == [143]


def test_flatten_pads_short_leaf() -> None:
    payload = {"data": {"143": {"2025-01-01 00:00:00": [3, 2, 37]}}}
    table = parse_uba_measures_bytes(json.dumps(payload).encode())
    assert table.column("value").to_pylist() == [37.0]
    assert table.column("date_end").to_pylist() == [None]
    assert table.column("index").to_pylist() == [None]


def test_flatten_rejects_non_numeric_station_id() -> None:
    # station_id is typed integer; a non-numeric key fails loudly rather than silently mistyping.
    payload = {"data": {"DEBW118": {"2025-01-01 00:00:00": [3, 2, 37, "2025-01-01 01:00:00", "2"]}}}
    with pytest.raises(ValueError):
        parse_uba_measures_bytes(json.dumps(payload).encode())


_LEAF = st.just([3, 2, 10, "2025-01-01 01:00:00", "1"])
_SERIES = st.dictionaries(
    keys=st.integers(min_value=0, max_value=23).map(lambda h: f"2025-01-01 {h:02d}:00:00"),
    values=_LEAF,
    max_size=24,
)
_STATIONS = st.dictionaries(keys=st.integers(min_value=1, max_value=999).map(str), values=_SERIES, max_size=4)


@given(stations=_STATIONS)
def test_flatten_row_count_matches_leaves(stations: dict[str, dict[str, list[Any]]]) -> None:
    payload = {"indices": INDICES, "data": stations}
    table = parse_uba_measures_bytes(json.dumps(payload).encode())
    assert table.num_rows == sum(len(series) for series in stations.values())


# --- Level 2: recorded reader (no network) ----------------------------------------------


@respx.mock
def test_uba_reader_level2(fixtures_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(UbaAirReader, "cache_dir", str(tmp_path))
    measures_bytes = (fixtures_dir / "uba_measures.json").read_bytes()
    respx.get(_demo_url()).mock(return_value=httpx.Response(200, content=measures_bytes))

    result = mloda.run_all(
        [
            Feature("value", options=dict(_demo_options())),
            Feature("date_start", options=dict(_demo_options())),
        ],
        compute_frameworks=["PyArrowTable"],
    )
    table = result[0]
    assert set(table.schema.names) == {"value", "date_start"}
    assert table.num_rows == 24
    assert table.schema.field("value").type == pa.float64()
    assert table.column("value").to_pylist()[0] == 37.0


@respx.mock
def test_uba_reader_level2_with_non_default_time_and_lang(
    fixtures_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(UbaAirReader, "cache_dir", str(tmp_path))
    measures_bytes = (fixtures_dir / "uba_measures.json").read_bytes()
    url = uba_measures_url(
        station=143, component=3, scope=2, date_from="2025-01-01", date_to="2025-01-01", time_from=6, lang="de"
    )
    respx.get(url).mock(return_value=httpx.Response(200, content=measures_bytes))

    options = dict(_demo_options())
    options[OPTION_UBA_TIME_FROM] = 6
    options[OPTION_UBA_LANG] = "de"
    result = mloda.run_all([Feature("value", options=options)], compute_frameworks=["PyArrowTable"])
    assert result[0].num_rows == 24


# --- Level 2: strict validation at resolution time (no network) -------------------------


@pytest.mark.parametrize(
    ("bad_option", "bad_value"),
    [
        (OPTION_UBA_STATION, -1),
        (OPTION_UBA_COMPONENT, 0),
        (OPTION_UBA_SCOPE, "not-a-number"),
        (OPTION_UBA_DATE_FROM, "2025-13-40"),
        (OPTION_UBA_DATE_FROM, "20250101"),  # basic ISO form; date.fromisoformat also accepts it on 3.11+
        (OPTION_UBA_DATE_FROM, "2025-W01-1"),  # week-date ISO form; same
        (OPTION_UBA_DATE_TO, "not-a-date"),
        (OPTION_UBA_DATE_TO, date(2025, 1, 1)),  # a real date object, not the required str
        (OPTION_UBA_TIME_FROM, 0),
        (OPTION_UBA_TIME_TO, 25),
    ],
)
@respx.mock
def test_invalid_uba_option_rejected_before_any_network_call(bad_option: str, bad_value: Any) -> None:
    # strict_validation on READER_OPTIONS (mloda >=0.11.0 PropertySpec) rejects a bad query
    # parameter during feature resolution, before building the URL or calling the live API;
    # @respx.mock with no routes registered turns any attempted request into a respx error, so a
    # regression that skips validation fails loudly here instead of quietly reaching the network.
    options = dict(_demo_options())
    options[bad_option] = bad_value
    with pytest.raises(ValueError, match=f"reader option '{bad_option}' value .* is rejected"):
        mloda.run_all([Feature("value", options=options)], compute_frameworks=["PyArrowTable"])


@respx.mock
def test_missing_required_uba_option_rejected_before_any_network_call() -> None:
    options = dict(_demo_options())
    del options[OPTION_UBA_DATE_FROM]
    with pytest.raises(ValueError, match="required reader option 'govdata_uba_date_from' is absent"):
        mloda.run_all([Feature("value", options=options)], compute_frameworks=["PyArrowTable"])


@respx.mock
def test_station_collection_value_rejected_before_any_network_call() -> None:
    # _reader_options_admit validates list/tuple/set/frozenset element-wise, so a collection
    # passes per-element validation; match_subclass_data_access must still reject it as a whole,
    # since uba_measures_url takes one station per query.
    options = dict(_demo_options())
    options[OPTION_UBA_STATION] = [143, 144]
    with pytest.raises(ValueError, match="takes a single value"):
        mloda.run_all([Feature("value", options=options)], compute_frameworks=["PyArrowTable"])


@respx.mock
def test_inverted_date_window_rejected_before_any_network_call() -> None:
    options = dict(_demo_options())
    options[OPTION_UBA_DATE_FROM] = "2025-12-31"
    with pytest.raises(ValueError, match="date_from .* is after date_to"):
        mloda.run_all([Feature("value", options=options)], compute_frameworks=["PyArrowTable"])


@respx.mock
def test_inverted_time_window_rejected_before_any_network_call() -> None:
    options = dict(_demo_options())
    options[OPTION_UBA_TIME_FROM] = 20
    options[OPTION_UBA_TIME_TO] = 5
    with pytest.raises(ValueError, match="time_from .* is after time_to"):
        mloda.run_all([Feature("value", options=options)], compute_frameworks=["PyArrowTable"])


@respx.mock
def test_explicit_time_boundaries_accepted(fixtures_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The default (time_from=1, time_to=24) never runs through _is_hour_slot, since
    # _reader_options_admit validates only present values; pin the boundaries when explicit.
    monkeypatch.setattr(UbaAirReader, "cache_dir", str(tmp_path))
    measures_bytes = (fixtures_dir / "uba_measures.json").read_bytes()
    respx.get(_demo_url()).mock(return_value=httpx.Response(200, content=measures_bytes))

    options = dict(_demo_options())
    options[OPTION_UBA_TIME_FROM] = 1
    options[OPTION_UBA_TIME_TO] = 24
    result = mloda.run_all([Feature("value", options=options)], compute_frameworks=["PyArrowTable"])
    assert result[0].num_rows == 24


# --- Level 3: live (deselected by default) ----------------------------------------------


@pytest.mark.live
def test_uba_live_end_to_end() -> None:
    result = mloda.run_all(
        [Feature("value", options=dict(_demo_options()))],
        compute_frameworks=["PyArrowTable"],
    )
    table = result[0]
    assert table.num_rows >= 20
    assert table.schema.field("value").type == pa.float64()
