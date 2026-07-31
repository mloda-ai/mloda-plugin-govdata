"""Deterministic parser for German public-authority CSVs into a typed Arrow table.

Handles the traits that break a naive ``pyarrow.csv`` read: cp1252/latin
encodings, semicolon delimiters, German number formatting (``.`` thousands,
``,`` decimal), German dates, and statistical value markers where ``-`` means
zero (not missing). Parsing into the wrong type fails loudly rather than
silently leaving a column as strings.
"""

from __future__ import annotations

import csv
import io
import os
from datetime import date, datetime
from enum import Enum

import pandas as pd
import pyarrow as pa

# Strict-decode first, latin-1 last because it never raises (guaranteed fallback).
ENCODING_LADDER: tuple[str, ...] = ("utf-8-sig", "cp1252", "iso-8859-15", "latin-1")

GERMAN_DATE_FORMAT = "%d.%m.%Y"

# German statistical value markers (Destatis / Genesis convention).
ZERO_MARKERS: frozenset[str] = frozenset({"-"})  # exactly zero, never null
NULL_MARKERS: frozenset[str] = frozenset({".", "...", "/", "x", "()", ""})  # unknown / blocked


class ColumnType(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    DATE = "date"


_ARROW_TYPE: dict[ColumnType, pa.DataType] = {
    ColumnType.STRING: pa.string(),
    ColumnType.INTEGER: pa.int64(),
    ColumnType.FLOAT: pa.float64(),
    ColumnType.DATE: pa.date32(),
}


def detect_encoding(data: bytes, ladder: tuple[str, ...] = ENCODING_LADDER) -> str:
    """First encoding in the ladder that decodes the bytes without error."""
    for enc in ladder:
        try:
            data.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    return ladder[-1]


def _clean_number(raw: str) -> str | None:
    """Apply value markers, then de-Germanize the number, or None for null markers."""
    value = raw.strip()
    if value in ZERO_MARKERS:
        return "0"
    if value in NULL_MARKERS:
        return None
    # German formatting: '.' is the thousands separator, ',' the decimal mark.
    return value.replace(".", "").replace(",", ".")


def _to_int(raw: str) -> int | None:
    cleaned = _clean_number(raw)
    if cleaned is None:
        return None
    try:
        # int() directly, never through float, so large values are not rounded.
        return int(cleaned)
    except ValueError:
        raise ValueError(f"expected an integer, got {raw!r}") from None


def _to_float(raw: str) -> float | None:
    cleaned = _clean_number(raw)
    if cleaned is None:
        return None
    return float(cleaned)


def _to_date(raw: str) -> date | None:
    value = raw.strip()
    if value in NULL_MARKERS:
        return None
    # Publisher columns are calendar dates (Stichtag), not instants; .date() drops the time,
    # so attaching a timezone would invent precision the source does not have.
    return datetime.strptime(value, GERMAN_DATE_FORMAT).date()  # noqa: DTZ007


def _to_string(raw: str) -> str | None:
    value = raw.strip()
    return None if value == "" else value


def _typed_table(cells: dict[str, list[str]], spec: dict[str, ColumnType]) -> pa.Table:
    """Build a typed Arrow table from raw string columns and a name to type spec."""
    arrays: dict[str, pa.Array] = {}
    fields: list[pa.Field] = []
    for name, ctype in spec.items():
        if name not in cells:
            raise KeyError(f"column {name!r} not found; available: {list(cells)}")
        raw = cells[name]
        if ctype is ColumnType.STRING:
            values: list[object] = [_to_string(v) for v in raw]
        elif ctype is ColumnType.INTEGER:
            values = [_to_int(v) for v in raw]
        elif ctype is ColumnType.FLOAT:
            values = [_to_float(v) for v in raw]
        else:
            values = [_to_date(v) for v in raw]
        arrays[name] = pa.array(values, type=_ARROW_TYPE[ctype])
        fields.append(pa.field(name, _ARROW_TYPE[ctype]))
    return pa.table(arrays, schema=pa.schema(fields))


def parse_german_csv_bytes(
    data: bytes,
    columns: dict[str, ColumnType] | None = None,
    *,
    sep: str = ";",
    skiprows: int = 0,
    encoding: str | None = None,
) -> pa.Table:
    """Parse single-header German-CSV ``data`` into a typed Arrow table.

    ``columns`` maps column name to type; when omitted every column is read as a
    string. Unknown column names in ``columns`` raise ``KeyError``.
    """
    enc = encoding or detect_encoding(data)
    frame = pd.read_csv(
        io.BytesIO(data),
        sep=sep,
        dtype=str,
        keep_default_na=False,
        na_values=[],
        skiprows=skiprows,
        encoding=enc,
    )
    frame.columns = pd.Index([str(name).strip() for name in frame.columns])
    cells: dict[str, list[str]] = {
        col: ["" if v is None else str(v) for v in frame[col].tolist()] for col in frame.columns
    }
    row_count = len(frame.index)

    # Drop fully-empty trailing rows (a trailing newline can yield one).
    keep = [i for i in range(row_count) if any(cells[col][i].strip() != "" for col in cells)]
    filtered = {name: [col[i] for i in keep] for name, col in cells.items()}

    spec = columns if columns is not None else {name: ColumnType.STRING for name in filtered}
    return _typed_table(filtered, spec)


def parse_german_csv(
    path: str | os.PathLike[str],
    columns: dict[str, ColumnType] | None = None,
    *,
    sep: str = ";",
    skiprows: int = 0,
    encoding: str | None = None,
) -> pa.Table:
    """Read ``path`` and parse it with :func:`parse_german_csv_bytes`."""
    with open(path, "rb") as handle:
        data = handle.read()
    return parse_german_csv_bytes(data, columns, sep=sep, skiprows=skiprows, encoding=encoding)


def _ffill_header_row(row: list[str]) -> list[str]:
    """Forward-fill a header row so merged (empty) cells inherit the value to their left."""
    out: list[str] = []
    last = ""
    for cell in row:
        text = cell.strip()
        if text:
            last = text
        out.append(last)
    return out


def _flatten_header(header_rows: list[list[str]]) -> list[str]:
    """Combine multi-row merged headers into one unique name per column.

    Trailing columns with no header cell in any row are dropped, so a universal
    trailing delimiter does not add a phantom all-null column.
    """
    ncols = 0
    for row in header_rows:
        for j, cell in enumerate(row):
            if cell.strip():
                ncols = max(ncols, j + 1)
    # Forward-fill merged cells within each row, then pad/truncate to ncols so a
    # writer's omitted trailing cells do not inherit a label.
    filled = [(_ffill_header_row(row) + [""] * ncols)[:ncols] for row in header_rows]
    names: list[str] = []
    used: set[str] = set()
    for j in range(ncols):
        parts: list[str] = []
        for row in filled:
            part = row[j]
            if part and (not parts or parts[-1] != part):
                parts.append(part)
        base = " ".join(parts) if parts else f"column_{j}"
        name = base
        suffix = 1
        while name in used:  # guarantee uniqueness even against pre-suffixed names
            suffix += 1
            name = f"{base} ({suffix})"
        used.add(name)
        names.append(name)
    return names


def parse_multi_header_csv_bytes(
    data: bytes,
    *,
    sep: str = ";",
    skiprows: int = 0,
    header_rows: int = 1,
    label_columns: int = 0,
    value_type: ColumnType = ColumnType.INTEGER,
    encoding: str | None = None,
) -> pa.Table:
    """Parse a publisher CSV with a multi-row merged header into a typed Arrow table.

    Skips ``skiprows`` preamble lines, flattens the next ``header_rows`` rows into
    unique column names, drops blank/separator rows, and types the first
    ``label_columns`` columns as strings with the rest as ``value_type``. Parsing
    goes through the csv module, so quoted fields and line endings are handled.
    """
    enc = encoding or detect_encoding(data)
    rows = list(csv.reader(io.StringIO(data.decode(enc)), delimiter=sep))
    header_block = rows[skiprows : skiprows + header_rows]
    if header_rows < 1 or len(header_block) < header_rows:
        raise ValueError("not enough header rows for the requested header_rows")
    names = _flatten_header(header_block)
    ncols = len(names)

    cells: dict[str, list[str]] = {name: [] for name in names}
    for row in rows[skiprows + header_rows :]:
        if not any(cell.strip() for cell in row):
            continue  # blank or separator row (e.g. a lone ';')
        fields = (row + [""] * ncols)[:ncols]
        for name, value in zip(names, fields):
            cells[name].append(value)

    spec = {name: (ColumnType.STRING if i < label_columns else value_type) for i, name in enumerate(names)}
    return _typed_table(cells, spec)


def parse_multi_header_csv(
    path: str | os.PathLike[str],
    *,
    sep: str = ";",
    skiprows: int = 0,
    header_rows: int = 1,
    label_columns: int = 0,
    value_type: ColumnType = ColumnType.INTEGER,
    encoding: str | None = None,
) -> pa.Table:
    """Read ``path`` and parse it with :func:`parse_multi_header_csv_bytes`."""
    with open(path, "rb") as handle:
        data = handle.read()
    return parse_multi_header_csv_bytes(
        data,
        sep=sep,
        skiprows=skiprows,
        header_rows=header_rows,
        label_columns=label_columns,
        value_type=value_type,
        encoding=encoding,
    )
