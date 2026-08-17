"""Bundeswahlleiterin federal election results (M1 elections theme, kerg.csv)."""

from __future__ import annotations

import numbers
from pathlib import Path
from typing import Any, ClassVar

import pyarrow as pa
from mloda.provider import PropertySpec, is_positive_int
from mloda.user import Options

from .core.discovery import ResolvedDistribution
from .core.locator import GovDataLocator
from .core.parse import ColumnType, parse_multi_header_csv
from .reader import BaseGovDataReader

# Feature-option keys steering the multi-header election parse; defaults are the btw25 kerg.csv
# geometry, so a new election file is a per-feature configuration change, not a code change.
OPTION_WAHL_SKIPROWS = "govdata_wahl_skiprows"
OPTION_WAHL_HEADER_ROWS = "govdata_wahl_header_rows"
OPTION_WAHL_LABEL_COLUMNS = "govdata_wahl_label_columns"
OPTION_WAHL_VALUE_TYPE = "govdata_wahl_value_type"


def _is_non_negative_int(value: Any) -> bool:
    """Element validator for a count that may legitimately be zero (the degenerate geometry:
    a single-header export needs ``skiprows=0`` or ``label_columns=0``). Mirrors mloda's
    ``is_positive_int`` (rejects bool, accepts numpy integers and decimal strings) but admits 0.
    """
    if isinstance(value, bool):
        return False
    if isinstance(value, numbers.Integral):
        return int(value) >= 0
    return isinstance(value, str) and value.isdecimal() and int(value) >= 0


class BundeswahlleiterinReader(BaseGovDataReader):
    """Reads German election-result CSVs with the Bundeswahlleiterin kerg.csv as the default geometry.

    The header geometry defaults to the btw25 kerg.csv layout (5-line preamble, 3-row merged
    header, 4 label columns, integer values) and is overridable per feature via the
    ``OPTION_WAHL_*`` option keys. A degenerate geometry (``header_rows=1``, ``skiprows=0``)
    covers single-header publisher exports, so connecting the next election is a
    configuration step instead of a code change.
    """

    READER_OPTIONS: ClassVar[dict[str, PropertySpec]] = {
        OPTION_WAHL_SKIPROWS: PropertySpec(
            "Preamble lines to skip before the header block.",
            default=5,
            strict_validation=True,
            element_validator=_is_non_negative_int,
        ),
        OPTION_WAHL_HEADER_ROWS: PropertySpec(
            "Merged header rows flattened into column names.",
            default=3,
            strict_validation=True,
            element_validator=is_positive_int,
        ),
        OPTION_WAHL_LABEL_COLUMNS: PropertySpec(
            "Leading columns typed as strings, not value_type.",
            default=4,
            strict_validation=True,
            element_validator=_is_non_negative_int,
        ),
        OPTION_WAHL_VALUE_TYPE: PropertySpec(
            "ColumnType of the non-label columns.",
            default=ColumnType.INTEGER,
            strict_validation=True,
            allowed_values=tuple(ColumnType),
        ),
    }

    @classmethod
    def match_subclass_data_access(cls, data_access: Any, feature_names: list[str], options: Any) -> Any:
        locator = super().match_subclass_data_access(data_access, feature_names, options)
        if locator is None:
            return None
        for key in cls.READER_OPTIONS:
            cls._scalar_reader_option(key, options)
        return locator

    @classmethod
    def _parse(
        cls, path: Path, locator: GovDataLocator, distribution: ResolvedDistribution, options: Options | None = None
    ) -> pa.Table:
        return parse_multi_header_csv(
            path,
            skiprows=int(cls.reader_option(OPTION_WAHL_SKIPROWS, options)),  # non-numeric values raise loudly
            header_rows=int(cls.reader_option(OPTION_WAHL_HEADER_ROWS, options)),
            label_columns=int(cls.reader_option(OPTION_WAHL_LABEL_COLUMNS, options)),
            value_type=ColumnType(cls.reader_option(OPTION_WAHL_VALUE_TYPE, options)),
        )
