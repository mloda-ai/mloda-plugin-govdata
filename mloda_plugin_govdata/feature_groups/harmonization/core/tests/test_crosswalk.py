from pathlib import Path

import pytest

from mloda_plugin_govdata.feature_groups.harmonization.core.crosswalk import load_nuts_crosswalk
from mloda_plugin_govdata.feature_groups.harmonization.core.reference.eurostat import parse_lau_nuts_de_workbook
from mloda_plugin_govdata.feature_groups.harmonization.core.reference.gv_isys import parse_gv_isys_workbook


class _FakeCache:
    """Stands in for DownloadCache: load_nuts_crosswalk only calls fetch_pinned, which this bypasses."""


def test_load_nuts_crosswalk_from_real_fixture(monkeypatch: pytest.MonkeyPatch, reference_fixtures_dir: Path) -> None:
    rows = parse_lau_nuts_de_workbook(reference_fixtures_dir / "eurostat-lau-nuts-de-extract.xlsx")
    monkeypatch.setattr(
        "mloda_plugin_govdata.feature_groups.harmonization.core.crosswalk.load_lau_nuts_de",
        lambda cache, **kwargs: rows,
    )
    crosswalk = load_nuts_crosswalk(_FakeCache())  # type: ignore[arg-type]
    assert crosswalk.nuts_version == "2024"
    assert crosswalk.gebietsstand == "2024"
    assert crosswalk.year_range == (2024, 2024)
    assert len(crosswalk.lau_rows) == 5


def test_load_nuts_crosswalk_year_range_widens_with_gv_isys_history(
    monkeypatch: pytest.MonkeyPatch, reference_fixtures_dir: Path
) -> None:
    rows = parse_lau_nuts_de_workbook(reference_fixtures_dir / "eurostat-lau-nuts-de-extract.xlsx")
    changes = parse_gv_isys_workbook(reference_fixtures_dir / "gv-isys-2016-extract.xlsx")
    monkeypatch.setattr(
        "mloda_plugin_govdata.feature_groups.harmonization.core.crosswalk.load_lau_nuts_de",
        lambda cache, **kwargs: rows,
    )
    crosswalk = load_nuts_crosswalk(_FakeCache(), gv_isys_changes=changes)  # type: ignore[arg-type]
    assert min(c.effective_date_legal.year for c in changes) == 2015  # must not widen the range
    assert crosswalk.year_range == (2016, 2024)
    assert crosswalk.gv_isys_changes == tuple(changes)


def test_load_nuts_crosswalk_raises_on_multiple_periods(
    monkeypatch: pytest.MonkeyPatch, reference_fixtures_dir: Path
) -> None:
    rows = parse_lau_nuts_de_workbook(reference_fixtures_dir / "eurostat-lau-nuts-de-extract.xlsx")
    mixed = [rows[0], rows[1].__class__(**{**rows[1].__dict__, "period": 2021})]
    monkeypatch.setattr(
        "mloda_plugin_govdata.feature_groups.harmonization.core.crosswalk.load_lau_nuts_de",
        lambda cache, **kwargs: mixed,
    )
    with pytest.raises(ValueError, match="multiple PERIOD values"):
        load_nuts_crosswalk(_FakeCache())  # type: ignore[arg-type]
