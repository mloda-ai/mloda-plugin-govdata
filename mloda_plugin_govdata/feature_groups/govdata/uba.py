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
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pyarrow as pa

from .core.discovery import ResolvedDistribution
from .core.locator import GovDataLocator
from .core.parse import ColumnType
from .reader import BaseGovDataReader

UBA_AIR_BASE = "https://luftdaten.umweltbundesamt.de/api/air-data/v4"

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
    """Reads the UBA Air Data v4 ``measures`` JSON endpoint into a typed Arrow table.

    The option value is a full ``measures`` URL (build one with :func:`uba_measures_url`);
    the response is flattened to one row per station and measurement timestamp. Reuses the
    client, cache, retry, and direct-URL resolution; only the parse seam differs from the
    CSV readers.
    """

    @classmethod
    def suffix(cls) -> tuple[str, ...]:
        return (".json",)

    @classmethod
    def _parse(cls, path: Path, locator: GovDataLocator, distribution: ResolvedDistribution) -> pa.Table:
        return parse_uba_measures(path)
