"""Period model normalizing GENESIS and kerg temporal semantics to one shape.

GENESIS annual tables carry two labels for the same annual granularity: JAHR
(a plain year, ``"2015"``) and STAG (a 31 Dec reference date, ``"2015-12-31"``
or ``"31.12.2015"``). Both normalize to the same annual :class:`Period`; only
the year matters, not which label produced it. kerg has no time column, the
election date comes from the locator or recipe (:func:`from_snapshot`); the
Destatis Stichtag a snapshot joins to is :func:`stichtag_period`.
Quarter and month parsing are not built:
:class:`Frequency` keeps all three values for forward compatibility, but only
``year`` has a working parser.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from enum import Enum


class Frequency(str, Enum):
    YEAR = "year"
    QUARTER = "quarter"
    MONTH = "month"


@dataclass(frozen=True)
class Period:
    start: date
    freq: Frequency

    def __post_init__(self) -> None:
        # Coerces a raw string that reached here from JSON-native recipe/locator options
        # (see DestatisLocator.coerce) rather than a typed Frequency; mypy only protects
        # in-repo callers.
        object.__setattr__(self, "freq", Frequency(self.freq))


_JAHR = re.compile(r"^\d{4}$", re.ASCII)
_STAG_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$", re.ASCII)
_STAG_DE = re.compile(r"^(\d{2})\.(\d{2})\.(\d{4})$", re.ASCII)


def parse_genesis_time(label: str) -> Period:
    """Parses a GENESIS ``time`` cell: JAHR (``"2015"``) or STAG (``"2015-12-31"`` / ``"31.12.2015"``).

    Surrounding whitespace in ``label`` is stripped before matching. Raises
    ``ValueError`` naming the label for anything else, including a STAG date
    whose day/month is not the annual 31 Dec reference point, or a
    syntactically 4-digit year outside ``date``'s 1..9999 range.
    """
    text = label.strip()
    if _JAHR.fullmatch(text):
        year = int(text)
        _year_date(label, year=year, month=1, day=1)  # validates the year is in date's range
        return Period(date(year, 1, 1), Frequency.YEAR)
    iso_match = _STAG_ISO.fullmatch(text)
    if iso_match is not None:
        return _annual_stag(
            label, year=int(iso_match.group(1)), month=int(iso_match.group(2)), day=int(iso_match.group(3))
        )
    de_match = _STAG_DE.fullmatch(text)
    if de_match is not None:
        return _annual_stag(
            label, year=int(de_match.group(3)), month=int(de_match.group(2)), day=int(de_match.group(1))
        )
    raise ValueError(f"{label!r} is not a recognized GENESIS time label (JAHR or STAG)")


def _year_date(label: str, *, year: int, month: int, day: int) -> date:
    """Builds a ``date``, re-raising with the original label on an out-of-range year or day."""
    try:
        return date(year, month, day)
    except ValueError as exc:
        raise ValueError(f"{label!r} is not a valid calendar date: {exc}") from exc


def _annual_stag(label: str, *, year: int, month: int, day: int) -> Period:
    parsed = _year_date(label, year=year, month=month, day=day)
    if (parsed.month, parsed.day) != (12, 31):
        raise ValueError(f"{label!r} is a STAG date but not the annual 31 Dec reference date")
    return Period(date(parsed.year, 1, 1), Frequency.YEAR)


def from_snapshot(snapshot: date, freq: Frequency = Frequency.YEAR) -> Period:
    """Builds a :class:`Period` from a point-in-time snapshot (e.g. an election date).

    Floors to the calendar year containing ``snapshot``: the snapshot's own year,
    not the Destatis year it joins to (that is :func:`stichtag_period`). Only
    ``Frequency.YEAR`` is implemented; quarter and month raise ``NotImplementedError``.
    """
    freq = Frequency(freq)
    if freq is not Frequency.YEAR:
        raise NotImplementedError(f"{freq.value} periods are not built; only year periods are")
    return Period(date(snapshot.year, 1, 1), freq)


def stichtag_period(snapshot: date) -> Period:
    """The annual period of the last 31 Dec Stichtag on or before ``snapshot`` (the join year for an election)."""
    year = snapshot.year if (snapshot.month, snapshot.day) == (12, 31) else snapshot.year - 1
    return Period(date(year, 1, 1), Frequency.YEAR)


def assert_same_frequency(left: Period, right: Period) -> None:
    """Raises ``ValueError`` naming both frequencies on a mismatch. No implicit aggregation."""
    if left.freq is not right.freq:
        raise ValueError(
            f"cannot compare periods of different frequency: {left.freq.value!r} vs {right.freq.value!r}; "
            "resample one side to the other's frequency before joining"
        )
