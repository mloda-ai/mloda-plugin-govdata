"""Level 2 (recorded) and Level 3 (live) tests for the GovData reader."""

import json
from pathlib import Path
from typing import cast

import httpx
import pyarrow as pa
import pytest
import respx

from mloda.provider import FeatureSet
from mloda.user import Feature, mloda

from mloda_plugin_govdata.feature_groups.govdata.bundeswahlleiterin import BundeswahlleiterinReader
from mloda_plugin_govdata.feature_groups.govdata.feature import GovDataFeature
from mloda_plugin_govdata.feature_groups.govdata.population import StuttgartPopulationReader
from mloda_plugin_govdata.feature_groups.govdata.reader import BaseGovDataReader, GovDataReader
from mloda_plugin_govdata.feature_groups.govdata.uba import UbaAirReader, uba_measures_url

SLUG = "einwohner-nach-altersgruppen-und-stadtbezirken"
PACKAGE_SHOW = "https://ckan.govdata.de/api/3/action/package_show"
KERG_URL = "https://www.bundeswahlleiterin.de/bundestagswahlen/2025/ergebnisse/opendata/btw25/csv/kerg.csv"
KERG_MEASURE = "Wahlberechtigte Erststimmen Endgültig"


def _mock_population_endpoints(fixtures_dir: Path) -> None:
    package_show = (fixtures_dir / "package_show.json").read_text(encoding="utf-8")
    csv_bytes = (fixtures_dir / "population_sample.csv").read_bytes()
    distribution_url = json.loads(package_show)["result"]["resources"][0]["url"]
    respx.get(PACKAGE_SHOW).mock(return_value=httpx.Response(200, text=package_show))
    respx.get(distribution_url).mock(return_value=httpx.Response(200, content=csv_bytes, headers={"ETag": '"v1"'}))


class _FakeFeatureSet:
    """Just enough FeatureSet surface for load_data."""

    def __init__(self, names: set[str]) -> None:
        self._names = names

    def get_all_names(self) -> set[str]:
        return self._names


def test_feature_group_uses_base_govdata_reader() -> None:
    assert isinstance(GovDataFeature.input_data(), BaseGovDataReader)


@respx.mock
def test_load_data_level2(fixtures_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(StuttgartPopulationReader, "cache_dir", str(tmp_path))
    package_show = (fixtures_dir / "package_show.json").read_text(encoding="utf-8")
    csv_bytes = (fixtures_dir / "population_sample.csv").read_bytes()
    distribution_url = json.loads(package_show)["result"]["resources"][0]["url"]

    respx.get(PACKAGE_SHOW).mock(return_value=httpx.Response(200, text=package_show))
    respx.get(distribution_url).mock(return_value=httpx.Response(200, content=csv_bytes, headers={"ETag": '"v1"'}))

    result = mloda.run_all(
        [
            Feature("Einwohner", options={StuttgartPopulationReader.__name__: SLUG}),
            Feature("Stadtbezirk", options={StuttgartPopulationReader.__name__: SLUG}),
        ],
        compute_frameworks=["PyArrowTable"],
    )
    table = result[0]
    assert set(table.schema.names) == {"Einwohner", "Stadtbezirk"}
    assert table.num_rows == 1000
    assert table.schema.field("Einwohner").type == pa.int64()


@respx.mock
def test_resolves_without_explicit_compute_framework(
    fixtures_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression: GovDataFeature must not collide with the built-in ReadFileFeature,
    # so a run_all call with no compute_frameworks pin still resolves to one group.
    monkeypatch.setattr(GovDataReader, "cache_dir", str(tmp_path))
    package_show = (fixtures_dir / "package_show.json").read_text(encoding="utf-8")
    csv_bytes = (fixtures_dir / "population_sample.csv").read_bytes()
    distribution_url = json.loads(package_show)["result"]["resources"][0]["url"]
    respx.get(PACKAGE_SHOW).mock(return_value=httpx.Response(200, text=package_show))
    respx.get(distribution_url).mock(return_value=httpx.Response(200, content=csv_bytes, headers={"ETag": '"v1"'}))

    result = mloda.run_all([Feature("Einwohner", options={GovDataReader.__name__: SLUG})])
    assert result[0].num_rows == 1000


@pytest.mark.live
def test_live_end_to_end() -> None:
    result = mloda.run_all(
        [Feature("Einwohner", options={StuttgartPopulationReader.__name__: SLUG})],
        compute_frameworks=["PyArrowTable"],
    )
    table = result[0]
    assert table.num_rows > 20_000
    assert table.schema.field("Einwohner").type == pa.int64()


@respx.mock
def test_elections_reader_level2(fixtures_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(BundeswahlleiterinReader, "cache_dir", str(tmp_path))
    kerg_bytes = (fixtures_dir / "kerg_sample.csv").read_bytes()
    respx.get(KERG_URL).mock(return_value=httpx.Response(200, content=kerg_bytes, headers={"ETag": '"k1"'}))
    result = mloda.run_all(
        [
            Feature("Gebiet", options={BundeswahlleiterinReader.__name__: KERG_URL}),
            Feature(KERG_MEASURE, options={BundeswahlleiterinReader.__name__: KERG_URL}),
        ],
        compute_frameworks=["PyArrowTable"],
    )
    table = result[0]
    assert set(table.schema.names) == {"Gebiet", KERG_MEASURE}
    assert table.num_rows == 16
    assert table.column("Gebiet").to_pylist()[0] == "Flensburg – Schleswig"
    assert table.schema.field(KERG_MEASURE).type == pa.int64()


@pytest.mark.live
def test_elections_live_end_to_end() -> None:
    result = mloda.run_all(
        [Feature("Gebiet", options={BundeswahlleiterinReader.__name__: KERG_URL})],
        compute_frameworks=["PyArrowTable"],
    )
    table = result[0]
    assert table.num_rows > 300
    assert table.column("Gebiet").to_pylist()[-1] == "Bundesgebiet"


@respx.mock
def test_peek_population_level2(fixtures_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(StuttgartPopulationReader, "cache_dir", str(tmp_path))
    _mock_population_endpoints(fixtures_dir)
    assert StuttgartPopulationReader.peek(SLUG) == {
        "Stichtag": "date32[day]",
        "Stadtbezirk": "string",
        "Alter in 10 Gruppen": "string",
        "Einwohner": "int64",
    }


@respx.mock
def test_generic_reader_reads_unknown_dataset_as_strings(
    fixtures_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The generic reader carries no dataset schema; every column comes back as a string.
    monkeypatch.setattr(GovDataReader, "cache_dir", str(tmp_path))
    _mock_population_endpoints(fixtures_dir)
    assert GovDataReader.peek(SLUG) == {
        "Stichtag": "string",
        "Stadtbezirk": "string",
        "Alter in 10 Gruppen": "string",
        "Einwohner": "string",
    }


@respx.mock
def test_peek_elections_level2(fixtures_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(BundeswahlleiterinReader, "cache_dir", str(tmp_path))
    kerg_bytes = (fixtures_dir / "kerg_sample.csv").read_bytes()
    respx.get(KERG_URL).mock(return_value=httpx.Response(200, content=kerg_bytes, headers={"ETag": '"k1"'}))
    columns = BundeswahlleiterinReader.peek(KERG_URL)
    assert columns["Gebiet"] == "string"
    assert columns[KERG_MEASURE] == "int64"


@respx.mock
def test_peek_uba_level2(fixtures_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(UbaAirReader, "cache_dir", str(tmp_path))
    url = uba_measures_url(station=143, component=3, scope=2, date_from="2025-01-01", date_to="2025-01-01")
    payload = (fixtures_dir / "uba_measures.json").read_bytes()
    respx.get(url).mock(return_value=httpx.Response(200, content=payload, headers={"ETag": '"u1"'}))
    columns = UbaAirReader.peek(url)
    assert columns["station_id"] == "int64"
    assert columns["value"] == "double"


def test_peek_rejects_unusable_data_access() -> None:
    with pytest.raises(ValueError, match="cannot handle data access"):
        GovDataReader.peek(123)


@pytest.mark.parametrize(
    "reader",
    [BaseGovDataReader, GovDataReader, StuttgartPopulationReader, BundeswahlleiterinReader, UbaAirReader],
)
def test_load_data_probe_still_raises_attribute_error(reader: type[BaseGovDataReader]) -> None:
    # The framework probes load_data(None, None) and only tolerates AttributeError.
    with pytest.raises(AttributeError):
        reader.load_data(None, cast(FeatureSet, None))


@respx.mock
def test_unknown_feature_names_available_columns(
    fixtures_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(GovDataReader, "cache_dir", str(tmp_path))
    _mock_population_endpoints(fixtures_dir)
    features = cast(FeatureSet, _FakeFeatureSet({"Einwohner_", "Stadtbezirk"}))
    with pytest.raises(ValueError) as excinfo:
        GovDataReader.load_data(SLUG, features)
    message = str(excinfo.value)
    assert "Unknown feature(s) 'Einwohner_'" in message
    assert "Available: Alter in 10 Gruppen, Einwohner, Stadtbezirk, Stichtag." in message
    assert "Did you mean 'Einwohner' instead of 'Einwohner_'?" in message


@respx.mock
def test_unknown_feature_suggestion_only_for_close_matches(
    fixtures_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(GovDataReader, "cache_dir", str(tmp_path))
    _mock_population_endpoints(fixtures_dir)
    features = cast(FeatureSet, _FakeFeatureSet({"Einwohner_", "zzzzz"}))
    with pytest.raises(ValueError) as excinfo:
        GovDataReader.load_data(SLUG, features)
    message = str(excinfo.value)
    assert "Unknown feature(s) 'Einwohner_', 'zzzzz'" in message
    assert message.count("Did you mean") == 1  # no suggestion for 'zzzzz'
    assert "Did you mean 'Einwohner' instead of 'Einwohner_'?" in message
