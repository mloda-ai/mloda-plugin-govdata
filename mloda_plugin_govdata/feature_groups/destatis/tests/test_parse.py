"""ffcsv: zip handling, the layout guard, and the typed parser, pinned to the Destatis example files and one live reply."""

import io
import json
import zipfile
from pathlib import Path

import pyarrow as pa
import pytest

from mloda_plugin_govdata.feature_groups.destatis.core.parse import (
    extract_ffcsv_csv,
    ffcsv_schema,
    guard_ffcsv_layout,
    parse_ffcsv_bytes,
    parse_ffcsv_zip,
)
from mloda_plugin_govdata.feature_groups.govdata.core.parse import NULL_MARKERS, ZERO_MARKERS, ColumnType

ONE_BLOCK_HEADER = [
    "statistics_code",
    "statistics_label",
    "time_code",
    "time_label",
    "time",
    "1_variable_code",
    "1_variable_label",
    "1_variable_attribute_code",
    "1_variable_attribute_label",
    "value",
    "value_unit",
    "value_variable_code",
    "value_variable_label",
]

TWO_BLOCK_HEADER = (
    ONE_BLOCK_HEADER[:9]
    + ["2_variable_code", "2_variable_label", "2_variable_attribute_code", "2_variable_attribute_label"]
    + ONE_BLOCK_HEADER[9:]
)


def _zip_of(name: str, data: bytes, *extra: tuple[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, data)
        for extra_name, extra_data in extra:
            archive.writestr(extra_name, extra_data)
    return buffer.getvalue()


# --- extract_ffcsv_csv ---------------------------------------------------------------------------


def test_extract_ffcsv_csv_returns_the_single_member() -> None:
    assert extract_ffcsv_csv(_zip_of("12411-0015_de_flat.csv", b"a;b\n1;2\n")) == b"a;b\n1;2\n"


def test_extract_ffcsv_csv_rejects_an_empty_archive() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w"):
        pass
    with pytest.raises(ValueError, match="archive is empty"):
        extract_ffcsv_csv(buffer.getvalue())


def test_extract_ffcsv_csv_rejects_more_than_one_member() -> None:
    with pytest.raises(ValueError, match="expected exactly one CSV member"):
        extract_ffcsv_csv(_zip_of("a.csv", b"x", ("b.csv", b"y")))


def test_extract_ffcsv_csv_rejects_a_non_csv_member() -> None:
    with pytest.raises(ValueError, match="expected exactly one CSV member"):
        extract_ffcsv_csv(_zip_of("readme.txt", b"not a csv"))


def test_extract_ffcsv_csv_rejects_not_a_zip() -> None:
    with pytest.raises(ValueError, match="not a valid zip archive"):
        extract_ffcsv_csv(b"not a zip at all")


def test_extract_ffcsv_csv_rejects_over_the_declared_size_cap() -> None:
    with pytest.raises(ValueError, match="declares .* over the .* cap"):
        extract_ffcsv_csv(_zip_of("t.csv", b"x" * 100), max_decompressed_bytes=10)


# --- guard_ffcsv_layout ----------------------------------------------------------------------------


def test_guard_accepts_one_block() -> None:
    assert guard_ffcsv_layout(ONE_BLOCK_HEADER) == 1


def test_guard_accepts_two_blocks() -> None:
    assert guard_ffcsv_layout(TWO_BLOCK_HEADER) == 2


def test_guard_accepts_an_optional_trailing_value_q() -> None:
    assert guard_ffcsv_layout([*ONE_BLOCK_HEADER, "value_q"]) == 1


def test_guard_rejects_wrong_prefix() -> None:
    with pytest.raises(ValueError, match="expected prefix"):
        guard_ffcsv_layout(["Statistik_Code", *ONE_BLOCK_HEADER[1:]])


def test_guard_rejects_a_dropped_block_field() -> None:
    dropped = [c for c in ONE_BLOCK_HEADER if c != "1_variable_attribute_label"]
    with pytest.raises(ValueError, match="variable block 1 expected"):
        guard_ffcsv_layout(dropped)


def test_guard_rejects_no_variable_blocks() -> None:
    with pytest.raises(ValueError, match="no variable blocks"):
        guard_ffcsv_layout(list(ONE_BLOCK_HEADER[:5]) + ONE_BLOCK_HEADER[9:])


def test_guard_rejects_an_unexpected_trailing_column() -> None:
    with pytest.raises(ValueError, match="unexpected trailing columns"):
        guard_ffcsv_layout([*ONE_BLOCK_HEADER, "surprise"])


def test_guard_rejects_duplicate_column_names() -> None:
    with pytest.raises(ValueError, match="duplicate column names"):
        guard_ffcsv_layout([*ONE_BLOCK_HEADER, "value"])


# --- ffcsv_schema ------------------------------------------------------------------------------


def test_schema_excludes_time_and_types_value_as_float() -> None:
    schema = ffcsv_schema(ONE_BLOCK_HEADER, 1)
    assert "time" not in schema
    assert schema["value"] is ColumnType.FLOAT
    assert schema["1_variable_code"] is ColumnType.STRING
    assert "value_q" not in schema


def test_schema_includes_value_q_only_when_declared() -> None:
    schema = ffcsv_schema([*ONE_BLOCK_HEADER, "value_q"], 1)
    assert schema["value_q"] is ColumnType.STRING


def test_schema_covers_every_block_for_two_blocks() -> None:
    schema = ffcsv_schema(TWO_BLOCK_HEADER, 2)
    for i in (1, 2):
        for suffix in ("variable_code", "variable_label", "variable_attribute_code", "variable_attribute_label"):
            assert schema[f"{i}_{suffix}"] is ColumnType.STRING


# --- parse_ffcsv_bytes / parse_ffcsv_zip on the real Destatis examples --------------------------


def _new_format_csv(fixtures_dir: Path, zip_name: str) -> bytes:
    return extract_ffcsv_csv((fixtures_dir / "ffcsv" / zip_name).read_bytes())


def test_parse_new_format_one_block_kulturstatistik(fixtures_dir: Path) -> None:
    data = _new_format_csv(fixtures_dir, "21611-0002_de_flat.zip")
    table = parse_ffcsv_bytes(data)
    assert table.num_rows == 207  # minus the header line
    assert set(table.schema.names) >= {
        "statistics_code",
        "time",
        "1_variable_code",
        "value",
        "value_unit",
        "value_marker",
    }
    assert table.schema.field("time").type == pa.int64()
    assert table.schema.field("value").type == pa.float64()
    assert table.schema.field("value_marker").type == pa.string()
    first = table.slice(0, 1).to_pylist()[0]
    assert first["statistics_code"] == "21611"
    assert first["time"] == 2004
    assert first["value_variable_code"] == "FILM02"
    assert first["value"] == pytest.approx(4870.0)
    assert first["value_marker"] == ""
    # no marker cells in this fixture (see the NOTICE)
    assert table.column("value_marker").to_pylist() == [""] * table.num_rows


def test_parse_new_format_dot_marker_is_null_and_recorded(fixtures_dir: Path) -> None:
    data = _new_format_csv(fixtures_dir, "61111-0001_de_flat.zip")
    table = parse_ffcsv_bytes(data)
    assert table.num_rows == 66
    rows = table.to_pylist()
    dot_rows = [r for r in rows if r["value_marker"] == "."]
    assert len(dot_rows) == 1
    assert dot_rows[0]["value"] is None
    assert dot_rows[0]["time"] == 1991
    # PREIS1 appears twice per year with two different units; both survive as distinct rows.
    units_2016 = {r["value_unit"] for r in rows if r["time"] == 2016 and r["value_variable_code"] == "PREIS1"}
    assert units_2016 == {"%", "2020=100"}


def test_parse_new_format_two_blocks_dash_and_dot_markers(fixtures_dir: Path) -> None:
    data = _new_format_csv(fixtures_dir, "61111-0003_de_flat.zip")
    table = parse_ffcsv_bytes(data)
    assert table.num_rows == 2205
    markers = table.column("value_marker").to_pylist()
    values = table.column("value").to_pylist()
    dash_count = sum(1 for m in markers if m == "-")
    dot_count = sum(1 for m in markers if m == ".")
    assert (dash_count, dot_count) == (5, 8)  # as recorded in the ffcsv NOTICE
    for marker, value in zip(markers, values):
        if marker == "-":
            assert value == 0.0  # a dash still parses to zero, nothing is lost
        elif marker:  # any other non-empty marker is a null sign
            assert marker in NULL_MARKERS
            assert value is None
        else:
            assert value is not None


@pytest.mark.parametrize("name", ["21611-0002_de_flat.csv", "61111-0001_de_flat.csv", "61111-0003_de_flat.csv"])
def test_parse_rejects_the_old_format_as_layout_drift(fixtures_dir: Path, name: str) -> None:
    # The old-format file next to each new-format example: same table, pre-November-2024 shape.
    old_format_path = fixtures_dir / "ffcsv" / name
    data = old_format_path.read_bytes()
    assert data[:4] != b"PK\x03\x04"
    with pytest.raises(ValueError, match="ffcsv layout"):
        parse_ffcsv_bytes(data)


@pytest.mark.parametrize("name", ["21611-0002_de_flat.zip", "61111-0001_de_flat.zip", "61111-0003_de_flat.zip"])
def test_parse_ffcsv_zip_end_to_end(fixtures_dir: Path, name: str) -> None:
    zip_bytes = (fixtures_dir / "ffcsv" / name).read_bytes()
    table = parse_ffcsv_zip(zip_bytes)
    assert table.num_rows > 0
    assert "value_marker" in table.schema.names


def test_parse_captured_land_table(fixtures_dir: Path) -> None:
    # First real GENESIS-Online tablefile reply in the fixtures: 12411-0010, one STAG, all 16 Länder.
    table = parse_ffcsv_zip((fixtures_dir / "ffcsv" / "12411-0010_2024_de_flat.zip").read_bytes())
    assert table.num_rows == 16
    assert table.column("time_code").to_pylist() == ["STAG"] * 16
    assert table.column("time").to_pylist() == [2024] * 16
    assert table.column("1_variable_code").to_pylist() == ["DLAND"] * 16
    assert set(table.column("1_variable_attribute_code").to_pylist()) == {f"{n:02d}" for n in range(1, 17)}
    assert table.column("value_marker").to_pylist() == [""] * 16
    assert "value_q" not in table.schema.names
    saarland = next(row for row in table.to_pylist() if row["1_variable_attribute_code"] == "10")
    assert saarland["1_variable_attribute_label"] == "Saarland"
    assert saarland["value"] == 1012141.0
    assert saarland["value_unit"] == "Anzahl"
    assert saarland["value_variable_code"] == "BEVSTD"


def test_parse_ffcsv_zip_rejects_over_the_size_cap(fixtures_dir: Path) -> None:
    zip_bytes = (fixtures_dir / "ffcsv" / "61111-0003_de_flat.zip").read_bytes()
    with pytest.raises(ValueError, match="cap"):
        parse_ffcsv_zip(zip_bytes, max_decompressed_bytes=10)


def test_stag_time_label_parses_through_the_period_model() -> None:
    # Live GENESIS-Online replies send ISO (the 12411-0010 capture: 2024-12-31); both forms parse through
    # core.period.parse_genesis_time, so pin the ffcsv wiring for each.
    header = ";".join(ONE_BLOCK_HEADER) + "\n"
    row_iso = "12411;Bevoelkerung;STAG;Stichtag;2015-12-31;DINSG;Deutschland insgesamt;DG;Deutschland;100;Anzahl;BEVSTD;Bevoelkerung\n"
    row_de = "12411;Bevoelkerung;STAG;Stichtag;31.12.2015;DINSG;Deutschland insgesamt;DG;Deutschland;100;Anzahl;BEVSTD;Bevoelkerung\n"
    for row in (row_iso, row_de):
        table = parse_ffcsv_bytes((header + row).encode("utf-8-sig"))
        assert table.column("time").to_pylist() == [2015]


@pytest.mark.parametrize(
    ("time", "value", "match"),
    [("not-a-year", "1", "column 'time', row 0"), ("2015", "abc", "column 'value', row 0: could not convert")],
)
def test_a_cell_that_cannot_be_typed_names_the_offending_row(time: str, value: str, match: str) -> None:
    header = ";".join(ONE_BLOCK_HEADER) + "\n"
    row = f"12411;Bevoelkerung;JAHR;Jahr;{time};DINSG;Deutschland insgesamt;DG;Deutschland;{value};Anzahl;X;Y\n"
    with pytest.raises(ValueError, match=match):
        parse_ffcsv_bytes((header + row).encode("utf-8-sig"))


def test_a_blank_value_cell_raises_instead_of_reading_as_a_plain_number() -> None:
    # "" is a govdata NULL_MARKERS member but not a documented GENESIS sign; treating it as a
    # marker-less null would be indistinguishable from a real number in value_marker.
    header = ";".join(ONE_BLOCK_HEADER) + "\n"
    row = "12411;Bevoelkerung;JAHR;Jahr;2015;DINSG;Deutschland insgesamt;DG;Deutschland;;Anzahl;X;Y\n"
    with pytest.raises(ValueError, match="column 'value', row 0"):
        parse_ffcsv_bytes((header + row).encode("utf-8-sig"))


def test_empty_csv_bytes_raise_a_ffcsv_value_error() -> None:
    with pytest.raises(ValueError, match="ffcsv: empty CSV"):
        parse_ffcsv_bytes(b"")


def test_value_q_column_survives_when_the_table_declares_it(fixtures_dir: Path) -> None:
    data = _new_format_csv(fixtures_dir, "21611-0002_de_flat.zip")
    table = parse_ffcsv_bytes(data)
    assert table.column("value_q").to_pylist()[0] == "e"


def test_qualitysigns_legend_is_covered_by_zero_null_or_a_flag(fixtures_dir: Path) -> None:
    # Every code in the captured legend is either a value marker this parser recognizes, or a value_q
    # flag (p/r/s) that never appears in the value cell itself.
    payload = json.loads((fixtures_dir / "genesis-guest-qualitysigns.json").read_text(encoding="utf-8"))
    flags = {"p", "r", "s"}
    for entry in payload["List"]:
        code = entry["Code"]
        if code in flags:
            continue
        if code == "0":
            continue  # a real near-zero decimal digit, not a sign in the value cell
        assert code in ZERO_MARKERS or code in NULL_MARKERS, f"unrecognized qualitysigns code {code!r}"
