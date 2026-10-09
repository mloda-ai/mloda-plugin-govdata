"""AnnualPeriodFeature: int years, GENESIS labels, and dates through mloda.run_all, plus the scoping path."""

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pyarrow as pa
import pytest
import respx
from mloda.provider import FeatureChainParser, FeatureSet
from mloda.user import Feature, FeatureName, Options, mloda

from mloda_plugin_govdata.feature_groups.destatis.reader import DestatisReader
from mloda_plugin_govdata.feature_groups.govdata.population import StuttgartPopulationReader
from mloda_plugin_govdata.feature_groups.govdata.reader import GovDataReader
from mloda_plugin_govdata.feature_groups.harmonization.period import AnnualPeriodFeature

from .conftest import GOETTINGEN_LOCATOR, GOETTINGEN_ZIP

PACKAGE_SHOW = "https://ckan.govdata.de/api/3/action/package_show"
CSV_URL = "https://example.org/jahre.csv"
SLUG = "einwohner-nach-altersgruppen-und-stadtbezirken"


def _run(features: list[Feature | str]) -> Any:
    return mloda.run_all(features, compute_frameworks=["PyArrowTable"])


def test_matches_the_year_period_name_and_the_configuration_based_form() -> None:
    assert AnnualPeriodFeature.match_feature_group_criteria("time__year_period", Options({}))
    assert not AnnualPeriodFeature.match_feature_group_criteria("time__quarter_period", Options({}))
    assert AnnualPeriodFeature.match_feature_group_criteria(
        "period", Options(group={"period_freq": "year"}, context={"in_features": "time"})
    )
    assert not AnnualPeriodFeature.match_feature_group_criteria(
        "period", Options(group={"period_freq": "quarter"}, context={"in_features": "time"})
    )
    (child,) = AnnualPeriodFeature().input_features(Options({}), FeatureName("time__year_period")) or set()
    assert str(child.name) == "time"


def test_the_named_capture_binds_period_freq_by_name() -> None:
    # Regression guard on the actual production pattern (fails against the old unnamed capture,
    # whose parsed value is positional only, not a name -> value binding).
    parsed = FeatureChainParser.parse_name("time__year_period", [AnnualPeriodFeature.PREFIX_PATTERN])
    assert parsed.named_captures == {"period_freq": "year"}


def test_a_second_overlapping_period_freq_would_still_bind_by_name() -> None:
    # A pattern with two alternatives, as a real second frequency would add, still binds each value
    # by name unconditionally. No FeatureGroup involved: this exercises the parser directly, so it
    # can't leak a test-local subclass into mloda's global FeatureGroup discovery.
    pattern = r".*__(?P<period_freq>year|quarter)_period$"
    assert FeatureChainParser.parse_name("time__year_period", [pattern]).named_captures == {"period_freq": "year"}
    assert FeatureChainParser.parse_name("time__quarter_period", [pattern]).named_captures == {"period_freq": "quarter"}


@respx.mock
def test_the_ffcsv_year_column_becomes_a_date_period(genesis: Callable[[str], respx.Route]) -> None:
    genesis(GOETTINGEN_ZIP)
    features: list[Feature | str] = [
        Feature("time", options={DestatisReader.__name__: GOETTINGEN_LOCATOR}),
        Feature("time__year_period", options={DestatisReader.__name__: GOETTINGEN_LOCATOR}),
    ]
    frames = {name: table for table in _run(features) for name in table.schema.names}  # one frame per group
    table = frames["time__year_period"]
    assert table.schema.field("time__year_period").type == pa.date32()
    years = frames["time"].column("time").to_pylist()
    assert table.column("time__year_period").to_pylist() == [date(year, 1, 1) for year in years]


def _mock_csv(text: str) -> None:
    respx.get(CSV_URL).mock(return_value=httpx.Response(200, content=text.encode("utf-8"), headers={"ETag": '"j1"'}))


@respx.mock
def test_genesis_labels_over_a_plain_csv_need_the_group_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # GovDataReader claims any name whose options carry its key, so a chained name over it is scoped explicitly.
    monkeypatch.setattr(GovDataReader, "cache_dir", str(tmp_path))
    _mock_csv("Jahr;Stichtag\n2015;31.12.2015\n2016;2016-12-31\n")
    options = {GovDataReader.__name__: CSV_URL}
    with pytest.raises(ValueError, match="Multiple feature groups found"):
        _run([Feature("Jahr__year_period", options=options)])
    features: list[Feature | str] = [
        Feature("Jahr__year_period", options=options, feature_group=AnnualPeriodFeature),
        Feature("Stichtag__year_period", options=options, feature_group=AnnualPeriodFeature),
    ]
    table = _run(features)[0]
    assert table.column("Jahr__year_period").to_pylist() == [date(2015, 1, 1), date(2016, 1, 1)]
    assert table.column("Stichtag__year_period").to_pylist() == [date(2015, 1, 1), date(2016, 1, 1)]


@respx.mock
def test_a_date_inside_the_year_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, govdata_fixtures_dir: Path
) -> None:
    # The Stuttgart Stichtag is 30 June: which year it joins to is chosen by a join, not by this group.
    monkeypatch.setattr(StuttgartPopulationReader, "cache_dir", str(tmp_path))
    package_show = (govdata_fixtures_dir / "package_show.json").read_text(encoding="utf-8")
    distribution_url = json.loads(package_show)["result"]["resources"][0]["url"]
    respx.get(PACKAGE_SHOW).mock(return_value=httpx.Response(200, text=package_show))
    respx.get(distribution_url).mock(
        return_value=httpx.Response(
            200, content=(govdata_fixtures_dir / "population_sample.csv").read_bytes(), headers={"ETag": '"v1"'}
        )
    )
    feature = Feature(
        "Stichtag__year_period", options={StuttgartPopulationReader.__name__: SLUG}, feature_group=AnnualPeriodFeature
    )
    with pytest.raises(ValueError, match="Stichtag, row 0: '1986-06-30' is a STAG date but not the annual 31 Dec"):
        _run([feature])


@respx.mock
def test_a_missing_time_value_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(GovDataReader, "cache_dir", str(tmp_path))
    _mock_csv("Jahr;x\n2015;a\n;b\n")
    feature = Feature("Jahr__year_period", options={GovDataReader.__name__: CSV_URL}, feature_group=AnnualPeriodFeature)
    with pytest.raises(ValueError, match="Jahr, row 1: no time value"):
        _run([feature])


@respx.mock
def test_a_contradicting_explicit_freq_is_refused(genesis: Callable[[str], respx.Route]) -> None:
    genesis(GOETTINGEN_ZIP)
    options = {DestatisReader.__name__: GOETTINGEN_LOCATOR, "period_freq": "quarter"}
    with pytest.raises(ValueError, match="'quarter' not found in mapping for 'period_freq'"):
        _run([Feature("time__year_period", options=options)])


def test_five_outputs_append_in_a_stable_alphabetical_order() -> None:
    # Five outputs, not two: an unfixed set-iteration order has only a 1-in-120 chance of
    # coincidentally matching this expected order on a given run. Calls calculate_feature
    # directly, bypassing run_all's own set-ordered final column selection.
    sources = {
        "Jahr": ["2015"],
        "Stichtag": ["2016-12-31"],
        "Bezugsjahr": ["2013"],
        "Erhebungsjahr": ["2012-12-31"],
        "Meldejahr": ["2011"],
    }
    table = pa.table(sources)
    names = [f"{column}__year_period" for column in sources]
    features = FeatureSet([Feature(name) for name in names])
    result = AnnualPeriodFeature.calculate_feature(table, features)
    assert result.schema.names == [*sources, *sorted(names)]
