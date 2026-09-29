"""KreisRebaseFeature: matching, option forwarding, and the expected re-based cells through mloda.run_all."""

import csv
import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest
import respx
from mloda.provider import FeatureSet
from mloda.user import Feature, FeatureName, FeatureResolutionError, Options, mloda

from mloda_plugin_govdata.feature_groups.destatis.core.auth import OPTION_GENESIS_CREDENTIALS, DestatisCredentials
from mloda_plugin_govdata.feature_groups.destatis.reader import DestatisReader
from mloda_plugin_govdata.feature_groups.govdata.core.cache import CacheMissError
from mloda_plugin_govdata.feature_groups.harmonization.core.rebase import (
    Flag,
    KeySheet,
    RebasedRow,
    RebaseResult,
    ShareKind,
    rebase,
)
from mloda_plugin_govdata.feature_groups.harmonization.rebase import KreisRebaseFeature
from mloda_plugin_govdata.recipes import Compliance, SourceCompliance, build_recipe, parse_recipe, recipe_to_json

from .conftest import COCHEM_ZELL_ZIP, EXTRACT, GOETTINGEN_LOCATOR, GOETTINGEN_ZIP, LAND_ZIP, ffcsv_zip_with_rows

CONFIGURATION_BASED_NAME = "destatis__bevoelkerung__kreise"
PARTS = KreisRebaseFeature.PARTS
YEARS = {"rebase_from_year": 2015, "rebase_to_year": 2016}


def _expected(path: Path) -> list[tuple[str, int, int, str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [(r["key"], int(r["year"]), int(r["value"]), r["flag"], r["sources"]) for r in csv.DictReader(handle)]


def _cells(table: pa.Table, name: str) -> list[tuple[str, int, int, str, str]]:
    columns = [table.column(f"{name}~{part}").to_pylist() for part in ("key", "year", "value", "flag", "sources")]
    return [
        (key, year, round(value), flag, "+".join(json.loads(sources)))
        for key, year, value, flag, sources in zip(*columns)
    ]


def _run(features: list[Feature | str]) -> Any:
    return mloda.run_all(features, compute_frameworks=["PyArrowTable"])


# --- Level 1: matching and input features -----------------------------------------------------


def test_matches_the_chained_and_the_configuration_based_name() -> None:
    years = Options(group=YEARS)
    assert KreisRebaseFeature.match_feature_group_criteria("value__rebased", years)
    assert KreisRebaseFeature.match_feature_group_criteria("value__rebased~flag", years)
    assert not KreisRebaseFeature.match_feature_group_criteria("value__rebased~edition", years)  # not a part
    assert not KreisRebaseFeature.match_feature_group_criteria("value__rebased", Options({}))  # the years are required
    assert not KreisRebaseFeature.match_feature_group_criteria("value", years)
    configured = Options(group=YEARS, context={"in_features": "value"})
    assert KreisRebaseFeature.match_feature_group_criteria(CONFIGURATION_BASED_NAME, configured)
    assert KreisRebaseFeature.match_feature_group_criteria(f"{CONFIGURATION_BASED_NAME}~flag", configured)
    assert not KreisRebaseFeature.match_feature_group_criteria(f"{CONFIGURATION_BASED_NAME}~edition", configured)
    assert not KreisRebaseFeature.match_feature_group_criteria(
        CONFIGURATION_BASED_NAME, Options(context={"in_features": "value"})
    )
    assert not KreisRebaseFeature.match_feature_group_criteria(CONFIGURATION_BASED_NAME, Options(group=YEARS))


def test_children_carry_the_locator_and_leave_the_group_keys_behind() -> None:
    options = Options(group={DestatisReader.__name__: GOETTINGEN_LOCATOR, **YEARS})
    children = KreisRebaseFeature().input_features(options, FeatureName("value__rebased")) or set()
    assert {str(c.name) for c in children} == {
        "value",
        "1_variable_code",
        "1_variable_attribute_code",
        "time",
        "value_marker",
    }
    for child in children:
        assert child.forward_group is None  # the reader locator forwards by default
        assert {"rebase_from_year", "rebase_to_year", "rebase_share"} <= child.forward_group_exclude
        assert child.inherit_context_keys == frozenset({OPTION_GENESIS_CREDENTIALS})
    configured = Options(group=YEARS, context={"in_features": "value"})
    assert {
        str(c.name)
        for c in KreisRebaseFeature().input_features(configured, FeatureName(CONFIGURATION_BASED_NAME)) or set()
    } == {
        "value",
        "1_variable_code",
        "1_variable_attribute_code",
        "time",
        "value_marker",
    }


def test_the_destatis_reader_leaves_chained_names_to_the_derived_groups() -> None:
    assert DestatisReader.match_subclass_data_access("12411-0015", ["value__rebased"], Options({})) is None
    assert DestatisReader.match_subclass_data_access("12411-0015", ["kreise~edition"], Options({})) is None
    assert DestatisReader.match_subclass_data_access("12411-0015", ["value"], Options({})) is not None


# --- Level 3: through mloda.run_all over the captured tables -------------------------------------


@respx.mock
def test_goettingen_series_through_the_configuration_based_name(
    genesis: Callable[[str], respx.Route], extract_keys: None, expected_dir: Path
) -> None:
    route = genesis(GOETTINGEN_ZIP)
    feature = Feature(
        CONFIGURATION_BASED_NAME,
        Options(group={DestatisReader.__name__: GOETTINGEN_LOCATOR, **YEARS}, context={"in_features": "value"}),
    )
    result = _run([feature])
    table = result[0]

    assert sorted(table.schema.names) == sorted(f"{CONFIGURATION_BASED_NAME}~{part}" for part in PARTS)
    assert _cells(table, CONFIGURATION_BASED_NAME) == _expected(expected_dir / "expected-goettingen-2016.csv")
    assert table.column(f"{CONFIGURATION_BASED_NAME}~value").to_pylist() == [
        322616.0,
        324013.0,
        329538.0,
        327065.0,
        328036.0,
    ]
    assert table.column(f"{CONFIGURATION_BASED_NAME}~marker").to_pylist() == [""] * 5
    assert route.calls.call_count == 1
    steps = [step.feature_group_name for step in result.plan if step.step_kind == "compute"]
    assert steps == ["GovDataFeature", "KreisRebaseFeature"]


@respx.mock
def test_the_chained_name_gives_the_same_rows(
    genesis: Callable[[str], respx.Route], extract_keys: None, expected_dir: Path
) -> None:
    genesis(GOETTINGEN_ZIP)
    table = _run([Feature("value__rebased", options={DestatisReader.__name__: GOETTINGEN_LOCATOR, **YEARS})])[0]
    assert _cells(table, "value__rebased") == _expected(expected_dir / "expected-goettingen-2016.csv")


@respx.mock
def test_one_sub_column_can_be_requested_alone(genesis: Callable[[str], respx.Route], extract_keys: None) -> None:
    genesis(GOETTINGEN_ZIP)
    table = _run([Feature("value__rebased~flag", options={DestatisReader.__name__: GOETTINGEN_LOCATOR, **YEARS})])[0]
    assert table.schema.names == ["value__rebased~flag"]
    assert table.column(0).to_pylist() == [Flag.REBASED.value] * 3 + [Flag.OBSERVED.value] * 2


@respx.mock
def test_an_unknown_part_is_refused_before_any_fetch_naming_the_parts(
    genesis: Callable[[str], respx.Route], extract_keys: None
) -> None:
    route = genesis(GOETTINGEN_ZIP)
    options = {DestatisReader.__name__: GOETTINGEN_LOCATOR, **YEARS}
    features = [
        Feature("value__rebased~edition", options=options),
        Feature("value__rebased~edition__nuts2024", options=options),  # inside a chain
        Feature("kreise~edition", Options(group=options, context={"in_features": "value"})),  # the reader declines it
    ]
    for feature in features:
        with pytest.raises(
            FeatureResolutionError,
            match=r"KreisRebaseFeature \(feature name\): unknown part ~edition; "
            r"KreisRebaseFeature returns ~key.*~provenance",
        ):
            _run([feature])
    assert route.calls.call_count == 0


@respx.mock
def test_issues_sit_next_to_their_rows_and_the_provenance_carries_the_rest(
    genesis: Callable[[str], respx.Route], extract_keys: None
) -> None:
    genesis(GOETTINGEN_ZIP)
    table = _run([Feature("value__rebased", options={DestatisReader.__name__: GOETTINGEN_LOCATOR, **YEARS})])[0]
    issues = {
        year: json.loads(records)
        for year, records in zip(
            table.column("value__rebased~year").to_pylist(), table.column("value__rebased~issues").to_pylist()
        )
    }

    assert any(
        i["kind"] == "not_applicable" and i["detail"].startswith("03159 does not exist before 31.12.2016")
        for i in issues[2013]
    )
    assert {i["key"] for i in issues[2014] if i["kind"] == "unverified_year"} == {"03152", "03156"}
    assert issues[2016] == []
    assert issues[2017][0]["kind"] == "unverified_year"
    assert issues[2017][0]["detail"].startswith("no key sheet 2016-2017")

    provenances = set(table.column("value__rebased~provenance").to_pylist())
    assert len(provenances) == 1
    provenance = json.loads(provenances.pop())
    assert sorted(provenance) == [
        "census_breaks",
        "from_year",
        "issues_elsewhere",
        "sha256",
        "share",
        "sheet",
        "source",
        "to_year",
        "url",
    ]
    assert provenance["source"] == EXTRACT.name
    assert provenance["sha256"] == EXTRACT.sha256
    assert (provenance["sheet"], provenance["share"], provenance["census_breaks"]) == ("2015-2016", "population", [])
    # Issues no output row carries keep their full record, never dropped.
    elsewhere = {(i["kind"], i["key"], i["year"]) for i in provenance["issues_elsewhere"]}
    assert elsewhere == {
        ("not_applicable", "03152", 2016),
        ("not_applicable", "03152", 2017),
        ("not_applicable", "03156", 2016),
        ("not_applicable", "03156", 2017),
        ("share_sum", "07135", None),
        ("share_sum", "07137", None),
    }
    assert any("0.9828486" in i["detail"] for i in provenance["issues_elsewhere"])
    # A row's issue records have the shape of the records the provenance carries.
    shapes = {frozenset(i) for i in provenance["issues_elsewhere"]} | {frozenset(i) for r in issues.values() for i in r}
    assert shapes == {frozenset({"kind", "key", "year", "detail", "target"})}


@respx.mock
def test_two_parts_of_one_output_in_one_request(genesis: Callable[[str], respx.Route], extract_keys: None) -> None:
    genesis(GOETTINGEN_ZIP)
    options = {DestatisReader.__name__: GOETTINGEN_LOCATOR, **YEARS}
    table = _run([Feature("value__rebased~key", options=options), Feature("value__rebased~value", options=options)])[0]
    assert sorted(table.schema.names) == ["value__rebased~key", "value__rebased~value"]
    assert table.num_rows == 5


def _stub_result(*pairs: tuple[str, int]) -> RebaseResult:
    key_sheet = KeySheet("src", "https://example.test/src", None, 2015, 2016, ShareKind.POPULATION)
    rows = tuple(RebasedRow(key, year, 1.0, Flag.OBSERVED, ()) for key, year in pairs)
    return RebaseResult(rows, key_sheet, (), ())


def _calculate_with_stubbed_rebase(monkeypatch: pytest.MonkeyPatch, results_by_column: dict[str, RebaseResult]) -> Any:
    monkeypatch.setattr(KreisRebaseFeature, "load_keys", classmethod(lambda cls: ((), None)))
    monkeypatch.setattr(
        KreisRebaseFeature,
        "_rebase",
        classmethod(lambda cls, table, value_column, options, keys, source: results_by_column[value_column]),
    )
    features = FeatureSet([Feature("value1__rebased"), Feature("value2__rebased")])
    return KreisRebaseFeature.calculate_feature(pa.table({}), features)


def test_two_outputs_re_based_to_the_same_rows_combine(monkeypatch: pytest.MonkeyPatch) -> None:
    aligned = _stub_result(("03101", 2016), ("03159", 2016))
    table = _calculate_with_stubbed_rebase(monkeypatch, {"value1": aligned, "value2": aligned})
    assert table.num_rows == 2
    assert table.column("value1__rebased~key").to_pylist() == table.column("value2__rebased~key").to_pylist()


def test_two_outputs_re_based_to_different_rows_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    # Same row count, different (Kreis, year) pairs: pa.table would otherwise stack them silently.
    with pytest.raises(ValueError, match="different \\(Kreis, year\\) rows"):
        _calculate_with_stubbed_rebase(
            monkeypatch,
            {
                "value1": _stub_result(("03101", 2016)),
                "value2": _stub_result(("03159", 2016)),
            },
        )


@respx.mock
def test_a_missing_feeder_is_explained_on_the_null_target_row(
    genesis: Callable[[str | bytes], respx.Route], extract_keys: None, ffcsv_fixtures_dir: Path
) -> None:
    # Only 03152 is observed, so the re-based 03159 is null; its row says which feeder is missing.
    only_03152 = ffcsv_zip_with_rows((ffcsv_fixtures_dir / GOETTINGEN_ZIP).read_bytes(), lambda row: ";03152;" in row)
    genesis(only_03152)
    options = {DestatisReader.__name__: GOETTINGEN_LOCATOR, **YEARS, "rebase_on_incomplete": "flag"}
    table = _run([Feature("value__rebased", options=options)])[0]
    rows = {
        year: (value, json.loads(sources), json.loads(issues))
        for year, value, sources, issues in zip(
            *(table.column(f"value__rebased~{part}").to_pylist() for part in ("year", "value", "sources", "issues"))
        )
    }
    assert set(table.column("value__rebased~key").to_pylist()) == {"03159"}
    assert rows[2015][:2] == (None, ["03152"])
    assert any(
        i["kind"] == "missing_source" and "03156 2015 was not given but feeds 03159" in i["detail"]
        for i in rows[2015][2]
    )


@respx.mock
def test_an_empty_selection_keeps_the_schema(
    genesis: Callable[[str | bytes], respx.Route], extract_keys: None, ffcsv_fixtures_dir: Path
) -> None:
    genesis(ffcsv_zip_with_rows((ffcsv_fixtures_dir / GOETTINGEN_ZIP).read_bytes(), lambda row: False))
    table = _run([Feature("value__rebased", options={DestatisReader.__name__: GOETTINGEN_LOCATOR, **YEARS})])[0]
    assert sorted(table.schema.names) == sorted(f"value__rebased~{part}" for part in PARTS)
    assert table.num_rows == 0


@respx.mock
def test_the_configuration_based_name_round_trips_through_a_recipe(
    genesis: Callable[[str], respx.Route], extract_keys: None, expected_dir: Path
) -> None:
    genesis(GOETTINGEN_ZIP)
    feature = Feature(
        CONFIGURATION_BASED_NAME,
        Options(group={DestatisReader.__name__: GOETTINGEN_LOCATOR, **YEARS}, context={"in_features": "value"}),
    )
    compliance = Compliance(
        sources=[
            SourceCompliance(
                license="dl-de/by-2-0",
                attribution="(c) Statistisches Bundesamt (Destatis), 2026",
                dataset_uri="https://genesis.destatis.de/datenbank/online/statistic/12411/table/12411-0015",
                retrieved_at=datetime(2026, 9, 12, tzinfo=timezone.utc),
                sha256="0" * 64,
                credential_env=["GENESIS_TOKEN"],
            )
        ]
    )
    loaded = parse_recipe(recipe_to_json(build_recipe([feature], compliance)))
    table = _run(list(loaded.features))[0]
    assert _cells(table, CONFIGURATION_BASED_NAME) == _expected(expected_dir / "expected-goettingen-2016.csv")


@respx.mock
def test_the_fractional_case_matches_the_expected_values(
    genesis: Callable[[str], respx.Route], extract_keys: None, expected_dir: Path
) -> None:
    genesis(COCHEM_ZELL_ZIP)
    options = {
        DestatisReader.__name__: {
            "name": "12411-0015",
            "regionalvariable": "KREISE",
            "startyear": 2013,
            "endyear": 2014,
        },
        "rebase_from_year": 2013,
        "rebase_to_year": 2014,
        "rebase_share": ShareKind.POPULATION.value,
    }
    table = _run([Feature("value__rebased", options=options)])[0]
    assert _cells(table, "value__rebased") == _expected(expected_dir / "expected-cochem-zell-2014.csv")
    assert set(table.column("value__rebased~issues").to_pylist()) == {"[]"}


@respx.mock
def test_options_reach_the_module(
    genesis: Callable[[str], respx.Route], extract_keys: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    genesis(GOETTINGEN_ZIP)
    seen: dict[str, Any] = {}

    def spy(observations: Any, **kwargs: Any) -> Any:
        seen.update(kwargs)
        return rebase(observations, **kwargs)

    monkeypatch.setattr("mloda_plugin_govdata.feature_groups.harmonization.rebase.rebase", spy)
    options = {
        DestatisReader.__name__: GOETTINGEN_LOCATOR,
        **YEARS,
        "rebase_share": "area",
        "rebase_tolerance": 1e-3,
        "rebase_on_unmatched": "flag",
        "rebase_on_incomplete": "drop",
    }
    _run([Feature("value__rebased", options=options)])
    assert seen["source"] is EXTRACT
    assert (seen["from_year"], seen["to_year"], seen["share"], seen["tolerance"]) == (2015, 2016, "area", 1e-3)
    assert (seen["on_unmatched"], seen["on_incomplete"]) == ("flag", "drop")


@respx.mock
def test_explicit_credentials_travel_from_the_derived_feature_to_the_reader(
    genesis: Callable[[str], respx.Route], extract_keys: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    route = genesis(GOETTINGEN_ZIP)
    for var in ("GENESIS_TOKEN", "GENESIS_USER", "GENESIS_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    feature = Feature(
        "value__rebased",
        Options(
            group={DestatisReader.__name__: GOETTINGEN_LOCATOR, **YEARS},
            context={OPTION_GENESIS_CREDENTIALS: DestatisCredentials(token="explicit-token")},
        ),
    )
    table = _run([feature])[0]
    assert table.num_rows == 5
    assert route.calls.call_count == 1


@respx.mock
def test_missing_years_raise_a_clear_error(genesis: Callable[[str], respx.Route], extract_keys: None) -> None:
    genesis(GOETTINGEN_ZIP)
    with pytest.raises(ValueError, match="rebase_from_year, rebase_to_year are absent"):
        _run([Feature("value__rebased", options={DestatisReader.__name__: GOETTINGEN_LOCATOR})])


@respx.mock
def test_a_land_table_is_refused_by_its_variable(genesis: Callable[[str], respx.Route], extract_keys: None) -> None:
    genesis(LAND_ZIP)
    locator = {"name": "12411-0010", "startyear": 2024, "endyear": 2024}
    with pytest.raises(ValueError, match=r"variable block 1 holds \['DLAND'\], not 'KREISE'"):
        _run([Feature("value__rebased", options={DestatisReader.__name__: locator, **YEARS})])


def test_keys_missing_from_the_cache_name_the_fetch_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(KreisRebaseFeature, "cache_dir", str(tmp_path))
    with pytest.raises(
        CacheMissError, match="load_bbsr_kreise\\(cache, revalidate=True\\).*KreisRebaseFeature.cache_dir"
    ):
        KreisRebaseFeature.load_keys()
