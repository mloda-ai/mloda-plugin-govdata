"""Level 1: deterministic German-CSV parsing on captured byte fixtures."""

import datetime
from pathlib import Path

import pyarrow as pa
import pytest

from mloda_plugin_govdata.feature_groups.govdata.core.parse import (
    ColumnType,
    detect_encoding,
    parse_german_csv,
    parse_german_csv_bytes,
    parse_multi_header_csv,
    parse_multi_header_csv_bytes,
)

POPULATION_COLUMNS: dict[str, ColumnType] = {
    "Stichtag": ColumnType.DATE,
    "Stadtbezirk": ColumnType.STRING,
    "Alter in 10 Gruppen": ColumnType.STRING,
    "Einwohner": ColumnType.INTEGER,
}

VALUE_MARKER_COLUMNS: dict[str, ColumnType] = {
    "Stichtag": ColumnType.DATE,
    "Gebiet": ColumnType.STRING,
    "Wert": ColumnType.INTEGER,
}


def test_detect_encoding_population(fixtures_dir: Path) -> None:
    data = (fixtures_dir / "population_sample.csv").read_bytes()
    assert detect_encoding(data) == "cp1252"
    with pytest.raises(UnicodeDecodeError):
        data.decode("utf-8")


def test_detect_encoding_prefers_utf8_sig_with_bom() -> None:
    assert detect_encoding("Wert\r\n123\r\n".encode("utf-8-sig")) == "utf-8-sig"


def test_detect_encoding_falls_back_for_cp1252_undefined_byte() -> None:
    # 0x81 is undefined in cp1252, so the ladder must reach an 8859 fallback.
    assert detect_encoding(b"\x81") in {"iso-8859-15", "latin-1"}


def test_parse_population_sample(fixtures_dir: Path) -> None:
    table = parse_german_csv(fixtures_dir / "population_sample.csv", POPULATION_COLUMNS)
    assert table.schema.names == ["Stichtag", "Stadtbezirk", "Alter in 10 Gruppen", "Einwohner"]
    assert table.num_rows == 1000
    assert table.schema.field("Stichtag").type == pa.date32()
    assert table.schema.field("Einwohner").type == pa.int64()
    first = table.slice(0, 1).to_pylist()[0]
    assert first["Stichtag"] == datetime.date(1986, 6, 30)
    assert first["Stadtbezirk"] == "Mitte"
    assert first["Einwohner"] == 494


def test_value_markers_map_correctly(fixtures_dir: Path) -> None:
    table = parse_german_csv(fixtures_dir / "value_markers.csv", VALUE_MARKER_COLUMNS)
    # '-' -> 0 (never null); '.', '...', '/', 'x' -> null; '1.234' -> 1234.
    assert table.column("Wert").to_pylist() == [0, 123, None, None, None, None, 1234]
    # cp1252 umlauts decode correctly.
    assert "Möhringen" in table.column("Gebiet").to_pylist()


def test_unknown_columns_default_to_string(fixtures_dir: Path) -> None:
    table = parse_german_csv(fixtures_dir / "value_markers.csv")
    assert all(field_type == pa.string() for field_type in table.schema.types)
    # Untyped: the '-' marker is preserved verbatim as a string.
    assert table.column("Wert").to_pylist()[0] == "-"


def test_missing_column_raises(fixtures_dir: Path) -> None:
    with pytest.raises(KeyError):
        parse_german_csv(fixtures_dir / "value_markers.csv", {"DoesNotExist": ColumnType.STRING})


def test_integer_validation_raises_on_non_numeric() -> None:
    data = "Wert\r\nnotanumber\r\n".encode("cp1252")
    with pytest.raises(ValueError):
        parse_german_csv_bytes(data, {"Wert": ColumnType.INTEGER})


def test_date_validation_raises_on_bad_date() -> None:
    data = "Stichtag\r\n99.99.9999\r\n".encode("cp1252")
    with pytest.raises(ValueError):
        parse_german_csv_bytes(data, {"Stichtag": ColumnType.DATE})


def test_large_integer_parses_exactly() -> None:
    # Values above 2**53 must not be rounded through float.
    big = 9007199254740993
    data = f"Wert\r\n{big}\r\n".encode("cp1252")
    table = parse_german_csv_bytes(data, {"Wert": ColumnType.INTEGER})
    assert table.column("Wert").to_pylist() == [big]


def test_multi_header_flattens_and_types_kerg(fixtures_dir: Path) -> None:
    table = parse_multi_header_csv(
        fixtures_dir / "kerg_sample.csv", skiprows=5, header_rows=3, label_columns=4, value_type=ColumnType.INTEGER
    )
    assert table.num_columns == 140  # 140 real columns; the trailing ';' phantom column is dropped
    assert table.num_rows == 16  # 17 data lines minus one ';' separator row
    assert table.schema.names[:4] == ["Nr", "Gebiet", "gehört zu", "Gewählt"]
    # the 3 merged header rows flatten into one combined name
    assert "Wahlberechtigte Erststimmen Endgültig" in table.schema.names
    assert table.schema.field("Gebiet").type == pa.string()
    assert table.schema.field("Wahlberechtigte Erststimmen Endgültig").type == pa.int64()
    assert table.column("Gebiet").to_pylist()[0] == "Flensburg – Schleswig"
    assert table.column("Wahlberechtigte Erststimmen Endgültig").to_pylist()[0] == 232131


def test_multi_header_forward_fills_merged_cells() -> None:
    data = b"Group;;Other\r\na;b;c\r\n1;2;3\r\n"
    table = parse_multi_header_csv_bytes(data, skiprows=0, header_rows=2, label_columns=3, value_type=ColumnType.STRING)
    assert table.schema.names == ["Group a", "Group b", "Other c"]


def test_multi_header_dedupes_duplicate_names() -> None:
    data = b"skip\r\nA;A\r\n1;2\r\n3;4\r\n"
    table = parse_multi_header_csv_bytes(
        data, skiprows=1, header_rows=1, label_columns=0, value_type=ColumnType.INTEGER
    )
    assert table.schema.names == ["A", "A (2)"]
    assert table.column("A").to_pylist() == [1, 3]
    assert table.column("A (2)").to_pylist() == [2, 4]


def test_multi_header_does_not_fill_padded_cells() -> None:
    # The top header row omits a trailing cell; padding must not forward-fill into it.
    data = b"A;B\r\nx;y;z\r\n1;2;3\r\n"
    table = parse_multi_header_csv_bytes(data, skiprows=0, header_rows=2, label_columns=3, value_type=ColumnType.STRING)
    assert table.schema.names == ["A x", "B y", "z"]


def test_multi_header_dedupe_handles_existing_suffix() -> None:
    data = b"A;A (2);A\r\n1;2;3\r\n"
    table = parse_multi_header_csv_bytes(
        data, skiprows=0, header_rows=1, label_columns=0, value_type=ColumnType.INTEGER
    )
    assert table.schema.names == ["A", "A (2)", "A (3)"]


def test_multi_header_empty_measure_is_null() -> None:
    data = b"Region;Votes\r\nBerlin;\r\nHamburg;5\r\n"
    table = parse_multi_header_csv_bytes(
        data, skiprows=0, header_rows=1, label_columns=1, value_type=ColumnType.INTEGER
    )
    assert table.column("Votes").to_pylist() == [None, 5]
