"""Destatis GV-ISys change-file loader (Gebietsstand history).

Each year's "Namens-Grenz-Aenderung" workbook uses a two-level merged-cell header
whose row offset is not something a single sample year can pin reliably across the
full 1990-2024 span. Data rows are found by their own shape instead: the first
column holds a change id (``<land>/<year>/<seq>-<letter>``, e.g. ``03/2016/0006-R``),
a pattern no header or blank row matches.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from mloda_plugin_govdata.feature_groups.govdata.core.cache import DownloadCache

from .download import fetch_pinned, load_workbook
from .sources import gv_isys_source

_CHANGE_ID = re.compile(r"^\d{2}/\d{4}/\d+-[A-Z]$")


@dataclass(frozen=True)
class GvIsysChange:
    change_id: str
    level: str  # "Kreis", "Gemeinde" or "Gemeindeverband" (no AGS, only the RS)
    from_rs: str
    from_ags: str | None
    from_name: str
    change_type: str
    to_rs: str
    to_ags: str | None
    to_name: str
    effective_date_legal: date  # "juristisch"
    effective_date_statistical: date  # "statistisch"


def _ags(value: Any) -> str | None:
    """An AGS cell, stripped of its padding; ``None`` when empty."""
    text = "" if value is None else str(value).strip()
    return text or None


def _parse_date(value: Any) -> date:
    """Parses a German ``dd.mm.yyyy`` calendar date. No time-of-day, so no timezone applies."""
    if isinstance(value, date):
        return value
    day, month, year = str(value).strip().split(".")
    return date(int(year), int(month), int(day))


def parse_gv_isys_workbook(path: str | os.PathLike[str]) -> list[GvIsysChange]:
    """Parses one year's GV-ISys "Namens-Grenz-Aenderung" workbook into change rows.

    A merger or split reads as several rows sharing one ``change_id`` (one row per
    donating/dissolving unit).
    """
    workbook = load_workbook(path)
    # The published file opens with a cover sheet, so read every sheet.
    rows = (cells for sheet in workbook.worksheets for cells in sheet.iter_rows(values_only=True))

    changes: list[GvIsysChange] = []
    for cells in rows:
        change_id = cells[0] if cells else None
        if not isinstance(change_id, str) or not _CHANGE_ID.match(change_id):
            continue  # title, blank, or header row; data rows are self-describing
        (
            _change_id,
            level,
            from_rs,
            from_ags,
            from_name,
            change_type,
            _area_sqm,
            _population,
            to_rs,
            to_ags,
            to_name,
            legal_date,
            statistical_date,
        ) = cells[:13]  # read-only mode pads each row to the sheet's dimension
        if any(value is not None for value in cells[13:]):
            raise ValueError(f"GV-ISys row {change_id}: cells past column 13, so the layout changed")
        changes.append(
            GvIsysChange(
                change_id=change_id,
                level=str(level).strip(),
                from_rs=str(from_rs).strip(),
                from_ags=_ags(from_ags),
                from_name=str(from_name).strip(),
                change_type=str(change_type).strip(),
                to_rs=str(to_rs).strip(),
                to_ags=_ags(to_ags),
                to_name=str(to_name).strip(),
                effective_date_legal=_parse_date(legal_date),
                effective_date_statistical=_parse_date(statistical_date),
            )
        )
    if not changes:
        raise ValueError(f"No GV-ISys change rows in {path} (sheets: {', '.join(workbook.sheetnames)})")
    return changes


def load_gv_isys_changes(
    year: int, cache: DownloadCache, *, sha256: str | None = None, revalidate: bool = False
) -> list[GvIsysChange]:
    """Fetches (offline-cache-first) and parses one year's GV-ISys change rows.

    ``sha256`` overrides the pin; when omitted, the known hash is applied automatically for
    a year that has one on record (2016 today, ``sources.GV_ISYS_2016_SHA256``), so the pin
    check is never silently skipped just because the caller forgot to pass it. Other years
    fetch unpinned.
    """
    source = gv_isys_source(year, sha256=sha256)
    path = fetch_pinned(cache, source, revalidate=revalidate)
    return parse_gv_isys_workbook(path)
