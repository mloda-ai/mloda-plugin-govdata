"""ffcsv: zip handling, the layout guard, and the typed parser for GENESIS ``data/tablefile`` replies.

Shape pinned offline against Destatis' own example zip (``Aenderung_Struktur_Flatfile-CSV.zip``,
sha256 ``46c5bb2f...``): fixed prefix ``statistics_code; statistics_label; time_code; time_label; time``,
N repeated blocks ``{N}_variable_code; {N}_variable_label; {N}_variable_attribute_code;
{N}_variable_attribute_label``, then a value block ``value; value_unit; value_variable_code;
value_variable_label`` with an optional trailing ``value_q``. Long format; utf-8 with BOM, LF, semicolon,
decimal comma in ``de``. Width grows only with the number of classifying variables, so the guard checks
shape, not a literal name list.
"""

from __future__ import annotations

import io
import zipfile

import pandas as pd
import pyarrow as pa

from ...govdata.core.parse import NULL_MARKERS, ZERO_MARKERS, ColumnType, _typed_table, detect_encoding
from .period import parse_genesis_time

__all__ = [
    "MAX_DECOMPRESSED_BYTES",
    "extract_ffcsv_csv",
    "ffcsv_schema",
    "guard_ffcsv_layout",
    "parse_ffcsv_bytes",
    "parse_ffcsv_zip",
]

# GENESIS tables in scope here are small; this is a zip-bomb guard, not a real ceiling.
MAX_DECOMPRESSED_BYTES = 32 * 1024 * 1024

FFCSV_PREFIX: tuple[str, ...] = ("statistics_code", "statistics_label", "time_code", "time_label", "time")
_BLOCK_SUFFIXES: tuple[str, ...] = (
    "variable_code",
    "variable_label",
    "variable_attribute_code",
    "variable_attribute_label",
)
FFCSV_VALUE_BLOCK: tuple[str, ...] = ("value", "value_unit", "value_variable_code", "value_variable_label")
VALUE_QUALITY_COLUMN = "value_q"


def extract_ffcsv_csv(zip_bytes: bytes, *, max_decompressed_bytes: int = MAX_DECOMPRESSED_BYTES) -> bytes:
    """The one CSV member of a ``data/tablefile`` zip reply.

    Rejects an empty archive, an archive that does not hold exactly one CSV member, a member whose
    declared size is over ``max_decompressed_bytes``, and any read failure (corrupt CRC, an
    encrypted member, an unsupported compression method) once opened; all surface as ``ValueError``.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise ValueError(f"ffcsv zip: not a valid zip archive ({exc})") from exc
    members = [info for info in archive.infolist() if not info.is_dir()]
    if not members:
        raise ValueError("ffcsv zip: archive is empty")
    csv_members = [info for info in members if info.filename.lower().endswith(".csv")]
    if len(members) != 1 or len(csv_members) != 1:
        raise ValueError(f"ffcsv zip: expected exactly one CSV member, found {[m.filename for m in members]!r}")
    member = csv_members[0]
    if member.file_size > max_decompressed_bytes:
        raise ValueError(
            f"ffcsv zip: member {member.filename!r} declares {member.file_size} bytes, "
            f"over the {max_decompressed_bytes} cap"
        )
    try:
        with archive.open(member) as handle:
            data = handle.read(max_decompressed_bytes + 1)
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError) as exc:
        raise ValueError(f"ffcsv zip: member {member.filename!r} could not be read ({exc})") from exc
    if len(data) > max_decompressed_bytes:
        raise ValueError(f"ffcsv zip: member {member.filename!r} decompressed over the {max_decompressed_bytes} cap")
    return data


def guard_ffcsv_layout(header: list[str]) -> int:
    """Validates the ffcsv column shape and returns N, the number of variable blocks.

    Checks the fixed prefix, N well-formed variable blocks, the value block, and an optional
    trailing ``value_q``; raises ``ValueError`` naming what does not fit. This is a shape check, not
    a literal name list, so it rejects the pre-November-2024 German wide format (a layout-drift
    fixture) the same way it rejects a hand-edited copy with a dropped block.
    """
    if len(set(header)) != len(header):
        raise ValueError(f"ffcsv layout: duplicate column names in {header!r}")
    prefix = header[: len(FFCSV_PREFIX)]
    if prefix != list(FFCSV_PREFIX):
        raise ValueError(f"ffcsv layout: expected prefix {list(FFCSV_PREFIX)}, got {prefix!r}")
    rest = header[len(FFCSV_PREFIX) :]
    n = 0
    idx = 0
    while idx < len(rest) and rest[idx] == f"{n + 1}_variable_code":
        n += 1
        expected_block = [f"{n}_{suffix}" for suffix in _BLOCK_SUFFIXES]
        block = rest[idx : idx + len(_BLOCK_SUFFIXES)]
        if block != expected_block:
            raise ValueError(f"ffcsv layout: variable block {n} expected {expected_block}, got {block!r}")
        idx += len(_BLOCK_SUFFIXES)
    if n == 0:
        raise ValueError(f"ffcsv layout: no variable blocks found after the prefix, got {rest!r}")
    value_block = rest[idx : idx + len(FFCSV_VALUE_BLOCK)]
    if value_block != list(FFCSV_VALUE_BLOCK):
        raise ValueError(f"ffcsv layout: value block expected {list(FFCSV_VALUE_BLOCK)}, got {value_block!r}")
    idx += len(FFCSV_VALUE_BLOCK)
    trailing = rest[idx:]
    if trailing not in ([], [VALUE_QUALITY_COLUMN]):
        raise ValueError(f"ffcsv layout: unexpected trailing columns {trailing!r}")
    return n


def ffcsv_schema(header: list[str], n_blocks: int) -> dict[str, ColumnType]:
    """Declared Arrow types for a guarded ffcsv header.

    Excludes ``time`` (parsed through the period model, not ``_typed_table``); includes
    ``value_q`` only when the header carries it (``quality=off`` omits it on the wire).
    """
    schema: dict[str, ColumnType] = {
        "statistics_code": ColumnType.STRING,
        "statistics_label": ColumnType.STRING,
        "time_code": ColumnType.STRING,
        "time_label": ColumnType.STRING,
    }
    for i in range(1, n_blocks + 1):
        for suffix in _BLOCK_SUFFIXES:
            schema[f"{i}_{suffix}"] = ColumnType.STRING
    schema["value"] = ColumnType.FLOAT
    schema["value_unit"] = ColumnType.STRING
    schema["value_variable_code"] = ColumnType.STRING
    schema["value_variable_label"] = ColumnType.STRING
    if VALUE_QUALITY_COLUMN in header:
        schema[VALUE_QUALITY_COLUMN] = ColumnType.STRING
    return schema


def _parse_time_column(raw: list[str]) -> pa.Array:
    """Annual year per GENESIS ``time`` label (JAHR or STAG), via the period model."""
    years: list[int] = []
    for row, label in enumerate(raw):
        try:
            years.append(parse_genesis_time(label).start.year)
        except ValueError as exc:
            raise ValueError(f"column 'time', row {row}: {exc}") from exc
    return pa.array(years, type=pa.int64())


def _value_marker(raw: str, row: int) -> str:
    """The raw sign of a ``value`` cell (``-``, ``.``, ``...``, ``/``, ``x``, ``()``), or ``""`` for a number.

    A blank cell is neither: unlike the other reused markers, ``""`` is not a documented GENESIS
    sign, so treating it as a marker-less null would be indistinguishable from a plain number here.
    """
    text = raw.strip()
    if text == "":
        raise ValueError(f"column 'value', row {row}: blank cell is not a recognized sign or number")
    return text if text in ZERO_MARKERS or text in NULL_MARKERS else ""


def parse_ffcsv_bytes(data: bytes) -> pa.Table:
    """Parses ffcsv bytes (the CSV member already extracted from a ``data/tablefile`` zip).

    Reuses the encoding ladder, German number cleanup, and value markers from
    ``govdata/core/parse.py``. ``time`` is parsed through the period model into an annual int64
    year (both JAHR and STAG labels); ``value_marker`` carries the raw sign of the ``value`` cell,
    empty for a plain number, next to whatever ``value_q`` the table declares. A blank ``time`` or
    ``value`` cell, or any cell that cannot be typed, raises naming its column and row.
    """
    encoding = detect_encoding(data)
    try:
        frame = pd.read_csv(
            io.BytesIO(data), sep=";", dtype=str, keep_default_na=False, na_values=[], encoding=encoding
        )
    except pd.errors.EmptyDataError as exc:
        raise ValueError(f"ffcsv: empty CSV ({exc})") from exc
    frame.columns = pd.Index([str(name).strip() for name in frame.columns])
    header = list(frame.columns)
    n_blocks = guard_ffcsv_layout(header)
    schema = ffcsv_schema(header, n_blocks)

    row_count = len(frame.index)
    cells: dict[str, list[str]] = {
        col: ["" if v is None else str(v) for v in frame[col].tolist()] for col in frame.columns
    }
    keep = [i for i in range(row_count) if any(cells[col][i].strip() != "" for col in cells)]
    filtered: dict[str, list[str]] = {name: [col[i] for i in keep] for name, col in cells.items()}

    table = _typed_table(filtered, schema)
    table = table.append_column("time", _parse_time_column(filtered["time"]))
    markers = pa.array([_value_marker(v, i) for i, v in enumerate(filtered["value"])], type=pa.string())
    return table.append_column("value_marker", markers)


def parse_ffcsv_zip(zip_bytes: bytes, *, max_decompressed_bytes: int = MAX_DECOMPRESSED_BYTES) -> pa.Table:
    """Extracts the CSV member from a ``data/tablefile`` zip reply and parses it."""
    return parse_ffcsv_bytes(extract_ffcsv_csv(zip_bytes, max_decompressed_bytes=max_decompressed_bytes))
