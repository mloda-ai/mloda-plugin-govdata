from pathlib import Path

import pytest

from mloda_plugin_govdata.feature_groups.govdata.core.cache import DownloadCache
from mloda_plugin_govdata.feature_groups.harmonization.core.reference import eurostat
from mloda_plugin_govdata.feature_groups.harmonization.core.reference.eurostat import (
    load_lau_nuts_de,
    parse_lau_nuts_de_workbook,
    parse_nuts_correspondence_workbook,
)


def test_parses_lau_nuts_de_rows(fixtures_dir: Path) -> None:
    rows = parse_lau_nuts_de_workbook(fixtures_dir / "eurostat-lau-nuts-de-extract.xlsx")
    assert len(rows) == 5
    by_lau = {r.lau_code: r for r in rows}
    assert by_lau["11000000"].nuts3 == "DE300"  # Berlin
    assert by_lau["03159501"].nuts3 == "DE91C"  # Harz gemeindefreies Gebiet
    assert all(r.period == 2024 for r in rows)


def test_lau_code_preserves_leading_zeros(fixtures_dir: Path) -> None:
    rows = parse_lau_nuts_de_workbook(fixtures_dir / "eurostat-lau-nuts-de-extract.xlsx")
    assert all(len(r.lau_code) == 8 for r in rows)
    assert all(r.lau_code.isdigit() for r in rows)


def test_parses_nuts_correspondence_overview(fixtures_dir: Path) -> None:
    overview = parse_nuts_correspondence_workbook(fixtures_dir / "eurostat-nuts-correspondence-extract.xlsx")
    assert overview.kreise == 401
    assert overview.gemeinden == 10957
    assert overview.version_label == "NUTS 2027 and LAU 2025"


def test_overview_version_differs_from_the_crosswalk_version(fixtures_dir: Path) -> None:
    # The overview table's own label names a different, not-yet-current NUTS version from the
    # NUTS 2024 crosswalk the mapper actually uses.
    overview = parse_nuts_correspondence_workbook(fixtures_dir / "eurostat-nuts-correspondence-extract.xlsx")
    assert "2024" not in overview.version_label


def test_lau_loader_docstring_documents_the_partial_validation_caveat() -> None:
    docstring = eurostat.parse_lau_nuts_de_workbook.__doc__ or ""
    assert "Cyprus" in docstring
    assert "validated" in docstring


@pytest.mark.live
def test_the_pinned_real_lau_file_maps_each_kreis_to_one_nuts3(tmp_path: Path) -> None:
    with DownloadCache(tmp_path) as cache:
        rows = load_lau_nuts_de(cache, revalidate=True)
    pairs = {(row.lau_code[:5], row.nuts3) for row in rows}
    assert len({kreis for kreis, _ in pairs}) == len({nuts3 for _, nuts3 in pairs}) == len(pairs) == 400
