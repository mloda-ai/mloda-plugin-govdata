"""The NUTS crosswalk the AGS-to-NUTS mapping resolves keys against.

A ``NutsCrosswalk`` names its Gebietsstand and NUTS version and carries the loaded LAU-to-NUTS rows
with the reference-data identity they were built from (source, URL, sha256, covered year range).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from mloda_plugin_govdata.feature_groups.govdata.core.cache import DownloadCache

from .reference.eurostat import LauNutsRow, load_lau_nuts_de
from .reference.gv_isys import GvIsysChange
from .reference.sources import EUROSTAT_LAU_NUTS

# The NUTS version of the pinned single-year crosswalk, not the differently-labelled version of
# Eurostat's "Correspondence table" (see reference/eurostat.py:NutsCorrespondenceOverview).
NUTS_VERSION = "2024"


@dataclass(frozen=True)
class NutsCrosswalk:
    gebietsstand: str
    nuts_version: str
    source: str
    url: str
    sha256: str | None
    year_range: tuple[int, int]
    lau_rows: tuple[LauNutsRow, ...]
    gv_isys_changes: tuple[GvIsysChange, ...] = ()


def load_nuts_crosswalk(
    cache: DownloadCache, *, gv_isys_changes: Sequence[GvIsysChange] = (), revalidate: bool = False
) -> NutsCrosswalk:
    """Builds the :class:`NutsCrosswalk` from the pinned Eurostat LAU-to-NUTS file.

    ``gv_isys_changes`` is optional history (e.g. from :func:`reference.gv_isys.load_gv_isys_changes`)
    used to redirect a since-retired Kreis code to its successor; without it, only Kreis codes
    already present in the crosswalk resolve.
    """
    rows = load_lau_nuts_de(cache, revalidate=revalidate)
    if not rows:
        raise ValueError("Eurostat LAU-to-NUTS table loaded with zero rows; cannot build a crosswalk")
    periods = {row.period for row in rows}
    if len(periods) > 1:
        raise ValueError(f"Eurostat LAU-to-NUTS rows span multiple PERIOD values: {sorted(periods)}")
    year = periods.pop()
    # The statistical date: a legal date can precede it, and data_year is a statistics year.
    years = [year, *(c.effective_date_statistical.year for c in gv_isys_changes)]
    return NutsCrosswalk(
        gebietsstand=str(year),
        nuts_version=NUTS_VERSION,
        source=EUROSTAT_LAU_NUTS.name,
        url=EUROSTAT_LAU_NUTS.url,
        sha256=EUROSTAT_LAU_NUTS.sha256,
        year_range=(min(years), max(years)),
        lau_rows=tuple(rows),
        gv_isys_changes=tuple(gv_isys_changes),
    )
