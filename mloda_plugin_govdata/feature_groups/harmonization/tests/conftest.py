"""Offline fixtures: the captured GENESIS replies behind a mocked POST, the reference extracts behind the loaders."""

import io
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from mloda.user import Credential, DataAccessCollection

from mloda_plugin_govdata.feature_groups.destatis.core.hosts import GENESIS_ONLINE
from mloda_plugin_govdata.feature_groups.destatis.reader import DestatisReader
from mloda_plugin_govdata.feature_groups.harmonization.core.crosswalk import NutsCrosswalk
from mloda_plugin_govdata.feature_groups.harmonization.core.reference.bbsr import parse_bbsr_kreise_workbook
from mloda_plugin_govdata.feature_groups.harmonization.core.reference.eurostat import parse_lau_nuts_de_workbook
from mloda_plugin_govdata.feature_groups.harmonization.core.reference.gv_isys import parse_gv_isys_workbook
from mloda_plugin_govdata.feature_groups.harmonization.core.tests.test_rebase import EXTRACT
from mloda_plugin_govdata.feature_groups.harmonization.nuts import AgsToNutsFeature
from mloda_plugin_govdata.feature_groups.harmonization.rebase import KreisRebaseFeature

_PACKAGE = Path(__file__).resolve().parents[3]
TOKEN = "test-token"
GOETTINGEN_ZIP = "12411-0015_2013-2017_de_flat.zip"
COCHEM_ZELL_ZIP = "12411-0015_2013-2014_de_flat.zip"
LAND_ZIP = "12411-0010_2024_de_flat.zip"
GOETTINGEN_LOCATOR = {
    "name": "12411-0015",
    "regionalvariable": "KREISE",
    "regionalkey": ["03152", "03156", "03159"],
    "startyear": 2013,
    "endyear": 2017,
}

__all__ = ["EXTRACT"]  # the extract's own ReferenceSource, shared with the module tests


def genesis_collection() -> DataAccessCollection:
    """The run's GENESIS credential for the mocked host."""
    return DataAccessCollection(credentials={"genesis": Credential(token=TOKEN)})


@pytest.fixture
def ffcsv_fixtures_dir() -> Path:
    return _PACKAGE / "feature_groups" / "destatis" / "tests" / "fixtures" / "ffcsv"


@pytest.fixture
def reference_fixtures_dir() -> Path:
    return _PACKAGE / "feature_groups" / "harmonization" / "core" / "reference" / "tests" / "fixtures"


@pytest.fixture
def expected_dir() -> Path:
    return _PACKAGE / "feature_groups" / "harmonization" / "core" / "tests" / "fixtures"


@pytest.fixture
def govdata_fixtures_dir() -> Path:
    return _PACKAGE / "feature_groups" / "govdata" / "tests" / "fixtures"


@pytest.fixture
def genesis(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ffcsv_fixtures_dir: Path) -> Callable[[str], respx.Route]:
    """Isolated reader cache; returns a mocker for the tablefile POST (runs pass ``genesis_collection()``)."""
    monkeypatch.setattr(DestatisReader, "cache_dir", str(tmp_path))

    def mock(zip_name: str | bytes) -> respx.Route:
        zip_bytes = zip_name if isinstance(zip_name, bytes) else (ffcsv_fixtures_dir / zip_name).read_bytes()
        return respx.post(GENESIS_ONLINE.base_url + "data/tablefile").mock(
            return_value=httpx.Response(200, content=zip_bytes, headers={"content-type": "application/octet-stream"})
        )

    return mock


def ffcsv_zip_with_rows(
    zip_bytes: bytes, keep: Callable[[str], bool], edit: Callable[[str], str] = lambda row: row
) -> bytes:
    """The fixture zip with only the CSV rows ``keep`` accepts, each passed through ``edit`` (the header stays)."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        (member,) = archive.namelist()
        header, *rows = archive.read(member).decode("utf-8-sig").splitlines(keepends=True)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        body = header + "".join(edit(row) for row in rows if keep(row))
        archive.writestr(member, ("﻿" + body).encode("utf-8"))
    return out.getvalue()


@pytest.fixture
def extract_keys(monkeypatch: pytest.MonkeyPatch, reference_fixtures_dir: Path) -> None:
    rows = parse_bbsr_kreise_workbook(reference_fixtures_dir / "bbsr-ref-kreise-extract.xlsx")
    monkeypatch.setattr(KreisRebaseFeature, "load_keys", classmethod(lambda cls: (rows, EXTRACT)))


def lau_rows(reference_fixtures_dir: Path) -> tuple[Any, ...]:
    return tuple(parse_lau_nuts_de_workbook(reference_fixtures_dir / "eurostat-lau-nuts-de-extract.xlsx"))


def gv_isys_changes(reference_fixtures_dir: Path) -> tuple[Any, ...]:
    return tuple(parse_gv_isys_workbook(reference_fixtures_dir / "gv-isys-2016-extract.xlsx"))


def fixture_crosswalk(reference_fixtures_dir: Path, *, with_history: bool = True) -> NutsCrosswalk:
    rows = lau_rows(reference_fixtures_dir)
    changes = gv_isys_changes(reference_fixtures_dir)
    return NutsCrosswalk(
        gebietsstand="2024",
        nuts_version="2024",
        source="test extract",
        url="test://lau-nuts",
        sha256=None,
        year_range=(2016, 2024),
        lau_rows=rows,
        gv_isys_changes=changes if with_history else (),
    )


@pytest.fixture
def extract_crosswalk(monkeypatch: pytest.MonkeyPatch, reference_fixtures_dir: Path) -> NutsCrosswalk:
    crosswalk = fixture_crosswalk(reference_fixtures_dir)
    monkeypatch.setattr(AgsToNutsFeature, "load_crosswalk", classmethod(lambda cls: crosswalk))
    return crosswalk
