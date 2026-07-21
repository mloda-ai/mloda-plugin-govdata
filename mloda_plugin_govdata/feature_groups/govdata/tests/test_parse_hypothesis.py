"""Level 1: property-based round-trip invariants for the German-CSV parser."""

from hypothesis import given
from hypothesis import strategies as st

from mloda_plugin_govdata.feature_groups.govdata.core.parse import ColumnType, parse_german_csv_bytes


def _german_thousands(value: int) -> str:
    """Format an int with '.' as the German thousands separator (e.g. 1234 -> '1.234')."""
    return f"{value:,}".replace(",", ".")


@given(values=st.lists(st.integers(min_value=0, max_value=10_000_000), min_size=1, max_size=40))
def test_integer_thousands_roundtrip(values: list[int]) -> None:
    lines = ["Wert", *[_german_thousands(v) for v in values]]
    data = ("\r\n".join(lines) + "\r\n").encode("cp1252")
    table = parse_german_csv_bytes(data, {"Wert": ColumnType.INTEGER})
    assert table.column("Wert").to_pylist() == values


_LABELS = (
    st.text(
        alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 äöüÄÖÜß.-",
        min_size=1,
        max_size=20,
    )
    .map(str.strip)
    .filter(lambda s: s != "")
)


@given(labels=st.lists(_LABELS, min_size=1, max_size=20))
def test_string_cp1252_roundtrip(labels: list[str]) -> None:
    lines = ["Gebiet", *labels]
    data = ("\r\n".join(lines) + "\r\n").encode("cp1252")
    table = parse_german_csv_bytes(data, {"Gebiet": ColumnType.STRING})
    assert table.column("Gebiet").to_pylist() == labels
