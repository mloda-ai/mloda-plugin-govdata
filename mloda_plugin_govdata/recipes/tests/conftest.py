"""Offline mocks for the shipped recipes: every reader answers from a committed fixture, never the network."""

import io
import json
import zipfile
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs

import httpx
import pytest
import respx
from mloda.user import Credential, DataAccessCollection, Feature, Link, mloda

from mloda_plugin_govdata.feature_groups.destatis.core.hosts import GENESIS_ONLINE
from mloda_plugin_govdata.feature_groups.destatis.reader import DestatisReader
from mloda_plugin_govdata.feature_groups.govdata import (
    BundeswahlleiterinReader,
    StuttgartPopulationReader,
    UbaAirReader,
)
from mloda_plugin_govdata.feature_groups.harmonization.core.reference.bbsr import parse_bbsr_kreise_workbook
from mloda_plugin_govdata.feature_groups.harmonization.core.reference.sources import BBSR_KREISE
from mloda_plugin_govdata.feature_groups.harmonization.rebase import KreisRebaseFeature
from scripts.write_recipes import KERG_URL, RECIPES_DIR, UBA_URL

REPO_ROOT = Path(__file__).resolve().parents[3]
_PACKAGE = REPO_ROOT / "mloda_plugin_govdata"
FFCSV_FIXTURES = _PACKAGE / "feature_groups" / "destatis" / "tests" / "fixtures" / "ffcsv"
GOVDATA_FIXTURES = _PACKAGE / "feature_groups" / "govdata" / "tests" / "fixtures"
REFERENCE_FIXTURES = _PACKAGE / "feature_groups" / "harmonization" / "core" / "reference" / "tests" / "fixtures"
EXPECTED_DIR = _PACKAGE / "feature_groups" / "harmonization" / "core" / "tests" / "fixtures"
PACKAGE_SHOW = "https://ckan.govdata.de/api/3/action/package_show"
TOKEN = "test-token"
GOETTINGEN_ZIP = "12411-0015_2013-2017_de_flat.zip"
FOREIGNERS_ZIP = "12521-0040_2013-2017_de_flat.zip"
LAND_ZIP = "12411-0010_2024_de_flat.zip"


class Mock(Protocol):
    """Mocks one GET: the committed fixture by default, or ``body`` for a variant of it."""

    def __call__(self, body: bytes | None = None) -> respx.Route: ...


def run(features: Iterable[Feature | str], links: Iterable[Link] = ()) -> Any:
    collection = DataAccessCollection(credentials={"genesis": Credential(token=TOKEN)})
    return mloda.run_all(
        list(features), compute_frameworks=["PyArrowTable"], links=set(links), data_access_collection=collection
    )


def ffcsv_zip_with_rows(zip_bytes: bytes, edit: Callable[[str], str]) -> bytes:
    """The fixture zip with every CSV row passed through ``edit`` (the header stays)."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        (member,) = archive.namelist()
        header, *rows = archive.read(member).decode("utf-8-sig").splitlines(keepends=True)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, ("﻿" + header + "".join(edit(row) for row in rows)).encode("utf-8"))
    return out.getvalue()


@pytest.fixture
def recipes_dir() -> Path:
    return RECIPES_DIR


@pytest.fixture
def genesis(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[[Mapping[str, str | bytes]], respx.Route]:
    """Isolated Destatis cache; the tablefile POST answers each table code with its zip (``run`` passes the token)."""
    monkeypatch.setattr(DestatisReader, "cache_dir", str(tmp_path / "genesis"))

    def mock(zips: Mapping[str, str | bytes]) -> respx.Route:
        bodies = {
            code: body if isinstance(body, bytes) else (FFCSV_FIXTURES / body).read_bytes()
            for code, body in zips.items()
        }

        def answer(request: httpx.Request) -> httpx.Response:
            (name,) = parse_qs(request.content.decode("utf-8"))["name"]
            return httpx.Response(200, content=bodies[name], headers={"content-type": "application/octet-stream"})

        return respx.post(GENESIS_ONLINE.base_url + "data/tablefile").mock(side_effect=answer)

    return mock


@pytest.fixture
def extract_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = parse_bbsr_kreise_workbook(REFERENCE_FIXTURES / "bbsr-ref-kreise-extract.xlsx")
    monkeypatch.setattr(KreisRebaseFeature, "load_keys", classmethod(lambda cls: (rows, BBSR_KREISE)))


def _get_mock(url: str, default: Path, etag: str) -> Mock:
    def mock(body: bytes | None = None) -> respx.Route:
        content = default.read_bytes() if body is None else body
        return respx.get(url).mock(return_value=httpx.Response(200, content=content, headers={"ETag": etag}))

    return mock


@pytest.fixture
def kerg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Mock:
    monkeypatch.setattr(BundeswahlleiterinReader, "cache_dir", str(tmp_path / "kerg"))
    return _get_mock(KERG_URL, GOVDATA_FIXTURES / "kerg_sample.csv", '"k1"')


@pytest.fixture
def stuttgart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Mock:
    monkeypatch.setattr(StuttgartPopulationReader, "cache_dir", str(tmp_path / "stuttgart"))
    package_show = (GOVDATA_FIXTURES / "package_show.json").read_text(encoding="utf-8")
    distribution_url = json.loads(package_show)["result"]["resources"][0]["url"]
    csv_mock = _get_mock(distribution_url, GOVDATA_FIXTURES / "population_sample.csv", '"v1"')

    def mock(body: bytes | None = None) -> respx.Route:
        respx.get(PACKAGE_SHOW).mock(return_value=httpx.Response(200, text=package_show))
        return csv_mock(body)

    return mock


@pytest.fixture
def uba(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Mock:
    monkeypatch.setattr(UbaAirReader, "cache_dir", str(tmp_path / "uba"))
    return _get_mock(UBA_URL, GOVDATA_FIXTURES / "uba_measures.json", '"u1"')
