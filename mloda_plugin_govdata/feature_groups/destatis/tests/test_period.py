import re
from datetime import date

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from mloda_plugin_govdata.feature_groups.destatis.core.period import (
    Frequency,
    Period,
    assert_same_frequency,
    from_snapshot,
    parse_genesis_time,
    stichtag_period,
)

_YEARS = st.integers(min_value=1900, max_value=2100)

# Independent copies of the three recognized label shapes (not imports from period.py),
# used only to steer the fuzz strategy in test_parse_genesis_time_rejects_unrecognized_shapes.
_JAHR_SHAPE = re.compile(r"^[0-9]{4}$")
_STAG_ISO_SHAPE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_STAG_DE_SHAPE = re.compile(r"^[0-9]{2}\.[0-9]{2}\.[0-9]{4}$")


@given(year=_YEARS)
def test_parse_genesis_time_jahr_is_annual(year: int) -> None:
    assert parse_genesis_time(str(year)) == Period(date(year, 1, 1), Frequency.YEAR)


def test_parse_genesis_time_strips_surrounding_whitespace() -> None:
    assert parse_genesis_time("  2015  ") == Period(date(2015, 1, 1), Frequency.YEAR)


@given(year=_YEARS)
def test_parse_genesis_time_stag_iso_and_de_agree_with_jahr(year: int) -> None:
    expected = Period(date(year, 1, 1), Frequency.YEAR)
    assert parse_genesis_time(f"{year:04d}-12-31") == expected
    assert parse_genesis_time(f"31.12.{year:04d}") == expected


@pytest.mark.parametrize("label", ["0000", "0000-12-31", "31.12.0000"])
def test_parse_genesis_time_rejects_year_zero(label: str) -> None:
    with pytest.raises(ValueError, match=re.escape(repr(label))):
        parse_genesis_time(label)


@pytest.mark.parametrize("year", [1, 9999])
def test_parse_genesis_time_accepts_the_date_range_boundaries(year: int) -> None:
    expected = Period(date(year, 1, 1), Frequency.YEAR)
    assert parse_genesis_time(f"{year:04d}") == expected
    assert parse_genesis_time(f"{year:04d}-12-31") == expected


@given(d=st.dates().filter(lambda d: (d.month, d.day) != (12, 31)))
def test_parse_genesis_time_rejects_non_annual_stag_date(d: date) -> None:
    for label in (f"{d.year:04d}-{d.month:02d}-{d.day:02d}", f"{d.day:02d}.{d.month:02d}.{d.year:04d}"):
        with pytest.raises(ValueError, match=re.escape(repr(label))):
            parse_genesis_time(label)


@given(label=st.text(alphabet="0123456789-. \t", min_size=1, max_size=20))
def test_parse_genesis_time_rejects_unrecognized_shapes(label: str) -> None:
    text = label.strip()
    assume(not (_JAHR_SHAPE.fullmatch(text) or _STAG_ISO_SHAPE.fullmatch(text) or _STAG_DE_SHAPE.fullmatch(text)))
    with pytest.raises(ValueError, match=re.escape(repr(label))):
        parse_genesis_time(label)


@given(label=st.text(min_size=1, max_size=20))
def test_parse_genesis_time_never_raises_without_naming_the_label(label: str) -> None:
    # Whatever label Hypothesis throws at it (Unicode included), a rejection always
    # names the exact label; a successful parse always yields a Period.
    try:
        result = parse_genesis_time(label)
    except ValueError as exc:
        assert repr(label) in str(exc)
    else:
        assert isinstance(result, Period)


def test_parse_genesis_time_rejects_empty_string() -> None:
    with pytest.raises(ValueError, match="not a recognized"):
        parse_genesis_time("")


@given(d=st.dates(min_value=date(1900, 1, 1), max_value=date(2100, 12, 31)))
def test_from_snapshot_floors_to_the_start_of_year(d: date) -> None:
    assert from_snapshot(d) == Period(date(d.year, 1, 1), Frequency.YEAR)


@given(d=st.dates(min_value=date(1900, 1, 1), max_value=date(2100, 12, 31)))
def test_from_snapshot_matches_genesis_annual_period_for_the_same_year(d: date) -> None:
    # The snapshot's own year as a Destatis annual period; the year it joins to is stichtag_period.
    assert from_snapshot(d) == parse_genesis_time(f"{d.year:04d}")


@given(d=st.dates(min_value=date(1900, 1, 1), max_value=date(2100, 12, 31)))
def test_stichtag_period_is_the_last_31_dec_on_or_before_the_snapshot(d: date) -> None:
    year = stichtag_period(d).start.year
    assert date(year, 12, 31) <= d < date(year + 1, 12, 31)


@pytest.mark.parametrize(
    ("snapshot", "year"),
    [(date(2025, 2, 23), 2024), (date(2024, 12, 31), 2024), (date(2025, 1, 1), 2024)],
)
def test_stichtag_period_cases(snapshot: date, year: int) -> None:
    assert stichtag_period(snapshot) == parse_genesis_time(f"31.12.{year}")


@pytest.mark.parametrize("freq", [Frequency.QUARTER, Frequency.MONTH])
def test_from_snapshot_rejects_unshipped_frequencies(freq: Frequency) -> None:
    with pytest.raises(NotImplementedError, match="not built"):
        from_snapshot(date(2015, 6, 15), freq)


def test_from_snapshot_coerces_a_raw_string_frequency() -> None:
    # JSON-native recipe/locator options arrive as plain strings, not Frequency members.
    assert from_snapshot(date(2015, 6, 15), "year") == Period(date(2015, 1, 1), Frequency.YEAR)  # type: ignore[arg-type]


def test_period_coerces_a_raw_string_frequency() -> None:
    assert Period(date(2015, 1, 1), "year").freq is Frequency.YEAR  # type: ignore[arg-type]


def test_assert_same_frequency_passes_when_equal() -> None:
    left = Period(date(2015, 1, 1), Frequency.YEAR)
    right = Period(date(2020, 1, 1), Frequency.YEAR)
    assert_same_frequency(left, right)  # does not raise


def test_assert_same_frequency_raises_with_resampling_guidance_on_mismatch() -> None:
    left = Period(date(2015, 1, 1), Frequency.YEAR)
    right = Period(date(2015, 4, 1), Frequency.QUARTER)
    with pytest.raises(ValueError, match="resample"):
        assert_same_frequency(left, right)


def test_assert_same_frequency_coerces_a_raw_string_frequency() -> None:
    left = Period(date(2015, 1, 1), Frequency.YEAR)
    right = Period(date(2015, 1, 1), "year")  # type: ignore[arg-type]
    assert_same_frequency(left, right)  # does not raise; both sides coerce to Frequency.YEAR
