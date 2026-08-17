"""Umweltbundesamt (UBA) Air Data v4 ``measures`` endpoint: reader, URL builder, JSON flatten.

The environment dataset (M1 environment theme) is publisher-direct REST JSON, not a CSV
distribution, so it has a distinct shape from the GovData / Bundeswahlleiterin CSV readers.
The response is ``{request, indices, data}`` where ``data`` is keyed by station then by
measurement start datetime, and each leaf is ``[component id, scope id, value, date end, index]``.
The leaf order is fixed by the v4 contract, so the flatten maps it to a canonical schema by
position and uses the self-describing ``indices.data`` block only to detect a changed layout.
"""

from __future__ import annotations

import json
import numbers
import os
from datetime import date
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import urlencode

import pyarrow as pa
from mloda.provider import PropertySpec, is_positive_int
from mloda.user import Options

from .core.discovery import ResolvedDistribution
from .core.locator import GovDataLocator
from .core.parse import ColumnType
from .reader import BaseGovDataReader

UBA_AIR_BASE = "https://luftdaten.umweltbundesamt.de/api/air-data/v4"

# Feature-option keys for the measures query. station/component/scope/date_from/date_to have no
# sensible default (each query targets a specific station and window), so they are required.
OPTION_UBA_STATION = "govdata_uba_station"
OPTION_UBA_COMPONENT = "govdata_uba_component"
OPTION_UBA_SCOPE = "govdata_uba_scope"
OPTION_UBA_DATE_FROM = "govdata_uba_date_from"
OPTION_UBA_DATE_TO = "govdata_uba_date_to"
OPTION_UBA_TIME_FROM = "govdata_uba_time_from"
OPTION_UBA_TIME_TO = "govdata_uba_time_to"
OPTION_UBA_LANG = "govdata_uba_lang"


def _is_hour_slot(value: Any) -> bool:
    """Element validator for the v4 hour-slot params (1-24). Mirrors mloda's is_positive_int
    (rejects bool, accepts numpy integers and decimal strings) with an upper bound."""
    if isinstance(value, bool):
        return False
    if isinstance(value, numbers.Integral):
        return 1 <= int(value) <= 24
    return isinstance(value, str) and value.isdecimal() and 1 <= int(value) <= 24


def _is_iso_date(value: Any) -> bool:
    """Element validator for date_from/date_to: a real calendar date in YYYY-MM-DD."""
    if not isinstance(value, str):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


# Canonical, stable output schema. The v4 measures leaf array is fixed by the API contract as
# [component id, scope id, value, date end, index]; the outer keys prepend the station id and the
# measurement start datetime. Names are canonical (not read from the response) so feature selection
# and column typing never depend on server-side labels, which can be revised or localized. The
# response's self-describing ``indices.data`` block is used only to detect a changed leaf width.
MEASURE_COLUMNS: tuple[str, ...] = (
    "station_id",
    "date_start",
    "component_id",
    "scope_id",
    "value",
    "date_end",
    "index",
)

# Fields in each leaf array (the columns after the station id and start datetime).
_VALUE_FIELD_COUNT = len(MEASURE_COLUMNS) - 2

# Column types; value is a float so a component reporting fractional concentrations is not
# truncated, ids and the air-quality index are integers, and the datetimes stay ISO strings.
MEASURE_COLUMN_TYPES: dict[str, ColumnType] = {
    "station_id": ColumnType.INTEGER,
    "date_start": ColumnType.STRING,
    "component_id": ColumnType.INTEGER,
    "scope_id": ColumnType.INTEGER,
    "value": ColumnType.FLOAT,
    "date_end": ColumnType.STRING,
    "index": ColumnType.INTEGER,
}

_ARROW_TYPE: dict[ColumnType, pa.DataType] = {
    ColumnType.STRING: pa.string(),
    ColumnType.INTEGER: pa.int64(),
    ColumnType.FLOAT: pa.float64(),
}


def uba_measures_url(
    *,
    station: int | str,
    component: int | str,
    scope: int | str,
    date_from: str,
    date_to: str,
    time_from: int = 1,
    time_to: int = 24,
    lang: str = "en",
    base: str = UBA_AIR_BASE,
) -> str:
    """Build a UBA Air Data v4 ``measures`` URL.

    Dates are ``YYYY-MM-DD``; ``time_from``/``time_to`` are hour slots 1-24. Parameter
    order is fixed so the same query always yields the same URL (a stable cache key).
    """
    params = {
        "date_from": date_from,
        "time_from": time_from,
        "date_to": date_to,
        "time_to": time_to,
        "station": station,
        "component": component,
        "scope": scope,
        "lang": lang,
    }
    return f"{base}/measures/json?{urlencode(params)}"


def _check_layout(payload: dict[str, Any]) -> None:
    """Fail loud if the response self-describes a leaf width other than the fixed one.

    ``indices.data`` is ``{<station label>: {<datetime label>: [<value labels...>]}}``. Leaves are
    mapped by position, so a changed field count would silently shift columns; detect it instead.
    A same-width reordering is not detected; the v4 leaf order is treated as a stable contract.
    """
    indices = payload.get("indices")
    if not isinstance(indices, dict):
        return
    outer = indices.get("data")
    if not isinstance(outer, dict) or not outer:
        return
    inner = outer[next(iter(outer))]
    if not isinstance(inner, dict) or not inner:
        return
    value_labels = inner[next(iter(inner))]
    if isinstance(value_labels, list) and len(value_labels) != _VALUE_FIELD_COUNT:
        raise ValueError(
            f"UBA measures leaf layout changed: expected {_VALUE_FIELD_COUNT} value fields, "
            f"got {len(value_labels)}: {value_labels}"
        )


def _to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"expected an integer, got {value!r}") from None


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"expected a float, got {value!r}") from None


def _to_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _typed_table(columns: dict[str, list[Any]], names: list[str]) -> pa.Table:
    arrays: dict[str, pa.Array] = {}
    fields: list[pa.Field] = []
    for name in names:
        ctype = MEASURE_COLUMN_TYPES.get(name, ColumnType.STRING)
        raw = columns[name]
        if ctype is ColumnType.INTEGER:
            values: list[object] = [_to_int(v) for v in raw]
        elif ctype is ColumnType.FLOAT:
            values = [_to_float(v) for v in raw]
        else:
            values = [_to_string(v) for v in raw]
        arrays[name] = pa.array(values, type=_ARROW_TYPE[ctype])
        fields.append(pa.field(name, _ARROW_TYPE[ctype]))
    return pa.table(arrays, schema=pa.schema(fields))


def parse_uba_measures_bytes(data: bytes) -> pa.Table:
    """Flatten a UBA ``measures`` JSON response into a typed Arrow table (one row per reading).

    One row per (station, measurement start) pair. Missing leaf cells and ``null`` values become
    nulls. Raises ``ValueError`` if the payload has no ``data`` object or self-describes a leaf
    width other than the expected one.
    """
    # A malformed response body is bad data, not a caller type error, so TRY004 is suppressed
    # below: the documented contract (and the tests) is that parse failures surface as ValueError.
    payload = json.loads(data)
    if not isinstance(payload, dict):
        raise ValueError("UBA measures payload is not a JSON object")  # noqa: TRY004
    series_by_station = payload.get("data")
    if not isinstance(series_by_station, dict):
        raise ValueError("UBA measures payload has no 'data' object")  # noqa: TRY004
    _check_layout(payload)

    station_col, datetime_col = MEASURE_COLUMNS[0], MEASURE_COLUMNS[1]
    value_cols = MEASURE_COLUMNS[2:]
    columns: dict[str, list[Any]] = {name: [] for name in MEASURE_COLUMNS}

    for station_id, series in series_by_station.items():
        if not isinstance(series, dict):
            continue
        for date_start, leaf in series.items():
            cells = list(leaf) if isinstance(leaf, list) else []
            columns[station_col].append(station_id)
            columns[datetime_col].append(date_start)
            for i, col in enumerate(value_cols):
                columns[col].append(cells[i] if i < len(cells) else None)

    return _typed_table(columns, list(MEASURE_COLUMNS))


def parse_uba_measures(path: str | os.PathLike[str]) -> pa.Table:
    """Read ``path`` and flatten it with :func:`parse_uba_measures_bytes`."""
    with open(path, "rb") as handle:
        data = handle.read()
    return parse_uba_measures_bytes(data)


class UbaAirReader(BaseGovDataReader):
    """Reads the UBA Air Data v4 ``measures`` endpoint into a typed Arrow table.

    Query parameters are per-feature options, not a pre-built URL: point a feature at this
    reader with a truthy class-name key, then supply ``OPTION_UBA_STATION``,
    ``OPTION_UBA_COMPONENT``, ``OPTION_UBA_SCOPE``, ``OPTION_UBA_DATE_FROM``, and
    ``OPTION_UBA_DATE_TO`` (``OPTION_UBA_TIME_FROM``/``_TIME_TO``/``_LANG`` are optional, matching
    :func:`uba_measures_url`'s defaults). A bad value is rejected during feature resolution,
    before any network call::

        Feature("value", options={
            UbaAirReader: True,
            OPTION_UBA_STATION: 143,
            OPTION_UBA_COMPONENT: 3,
            OPTION_UBA_SCOPE: 2,
            OPTION_UBA_DATE_FROM: "2025-01-01",
            OPTION_UBA_DATE_TO: "2025-01-01",
        })

    The response is flattened to one row per station and measurement timestamp. Reuses the
    client, cache, retry, and direct-URL resolution; only the parse seam and locator building
    differ from the CSV readers.
    """

    READER_OPTIONS: ClassVar[dict[str, PropertySpec]] = {
        OPTION_UBA_STATION: PropertySpec("UBA station id.", strict_validation=True, element_validator=is_positive_int),
        OPTION_UBA_COMPONENT: PropertySpec(
            "UBA component id (see the UBA components endpoint).",
            strict_validation=True,
            element_validator=is_positive_int,
        ),
        OPTION_UBA_SCOPE: PropertySpec(
            "UBA scope id (see the UBA scopes endpoint).",
            strict_validation=True,
            element_validator=is_positive_int,
        ),
        OPTION_UBA_DATE_FROM: PropertySpec(
            "Query window start, YYYY-MM-DD.", strict_validation=True, element_validator=_is_iso_date
        ),
        OPTION_UBA_DATE_TO: PropertySpec(
            "Query window end, YYYY-MM-DD.", strict_validation=True, element_validator=_is_iso_date
        ),
        OPTION_UBA_TIME_FROM: PropertySpec(
            "Start hour slot (1-24).", default=1, strict_validation=True, element_validator=_is_hour_slot
        ),
        OPTION_UBA_TIME_TO: PropertySpec(
            "End hour slot (1-24).", default=24, strict_validation=True, element_validator=_is_hour_slot
        ),
        OPTION_UBA_LANG: PropertySpec("UBA API response language.", default="en"),
    }

    @classmethod
    def suffix(cls) -> tuple[str, ...]:
        return (".json",)

    @classmethod
    def match_subclass_data_access(cls, data_access: Any, feature_names: list[str], options: Any) -> Any:
        if not data_access:
            return None
        url = uba_measures_url(
            station=cls.reader_option(OPTION_UBA_STATION, options),
            component=cls.reader_option(OPTION_UBA_COMPONENT, options),
            scope=cls.reader_option(OPTION_UBA_SCOPE, options),
            date_from=cls.reader_option(OPTION_UBA_DATE_FROM, options),
            date_to=cls.reader_option(OPTION_UBA_DATE_TO, options),
            time_from=cls.reader_option(OPTION_UBA_TIME_FROM, options),
            time_to=cls.reader_option(OPTION_UBA_TIME_TO, options),
            lang=cls.reader_option(OPTION_UBA_LANG, options),
        )
        return GovDataLocator(distribution_url=url)

    @classmethod
    def _parse(
        cls, path: Path, locator: GovDataLocator, distribution: ResolvedDistribution, options: Options | None = None
    ) -> pa.Table:
        return parse_uba_measures(path)
