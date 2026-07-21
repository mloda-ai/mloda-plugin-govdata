"""Bundeswahlleiterin federal election results (M1 elections theme, kerg.csv)."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa

from .core.discovery import ResolvedDistribution
from .core.locator import GovDataLocator
from .core.parse import ColumnType, parse_multi_header_csv
from .reader import BaseGovDataReader


class BundeswahlleiterinReader(BaseGovDataReader):
    """Reads the Bundeswahlleiterin kerg.csv result file (5-line preamble, 3-row merged header)."""

    @classmethod
    def _parse(cls, path: Path, locator: GovDataLocator, distribution: ResolvedDistribution) -> pa.Table:
        return parse_multi_header_csv(path, skiprows=5, header_rows=3, label_columns=4, value_type=ColumnType.INTEGER)
