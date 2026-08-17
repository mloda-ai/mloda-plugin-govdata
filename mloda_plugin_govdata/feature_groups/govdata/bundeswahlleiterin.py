"""Bundeswahlleiterin federal election results (M1 elections theme, kerg.csv)."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pyarrow as pa
from mloda.provider import PropertySpec
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


class BundeswahlleiterinReader(BaseGovDataReader):
    """Reads German election-result CSVs with the Bundeswahlleiterin kerg.csv as the default geometry.

    The header geometry defaults to the btw25 kerg.csv layout (5-line preamble, 3-row merged
    header, 4 label columns, integer values) and is overridable per feature via the
    ``OPTION_WAHL_*`` option keys. A degenerate geometry (``header_rows=1``, ``skiprows=0``)
    covers single-header publisher exports, so connecting the next election is a
    configuration step instead of a code change.
    """

    READER_OPTIONS: ClassVar[dict[str, PropertySpec]] = {
        OPTION_WAHL_SKIPROWS: PropertySpec("Preamble lines to skip before the header block.", default=5),
        OPTION_WAHL_HEADER_ROWS: PropertySpec("Merged header rows flattened into column names.", default=3),
        OPTION_WAHL_LABEL_COLUMNS: PropertySpec("Leading columns typed as strings, not value_type.", default=4),
        OPTION_WAHL_VALUE_TYPE: PropertySpec("ColumnType of the non-label columns.", default=ColumnType.INTEGER),
    }

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
