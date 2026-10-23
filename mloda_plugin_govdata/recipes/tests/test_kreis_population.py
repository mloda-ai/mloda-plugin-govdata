"""kreis_population_rebased: the re-based Kreis series through mloda, and a '-' before the merger is never a zero."""

import csv
import hashlib
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest
import respx
from mloda.user import Feature

from mloda_plugin_govdata.feature_groups.harmonization.core.rebase import ValidityError
from mloda_plugin_govdata.feature_groups.harmonization.core.reference.sources import BBSR_KREISE
from mloda_plugin_govdata.recipes import load_recipe
from scripts.write_recipes import CONFIGURATION_BASED_NAME, KREIS_POPULATION_REBASED

from .conftest import EXPECTED_DIR, FFCSV_FIXTURES, GOETTINGEN_ZIP, ffcsv_zip_with_rows, run

Genesis = Callable[[Mapping[str, str | bytes]], respx.Route]
PARTS = ("key", "year", "value", "flag", "sources", "marker", "issues", "provenance")
JSON_PARTS = ("issues", "provenance")


def _rows(table: Any) -> dict[int, dict[str, Any]]:
    columns = {part: table.column(f"{CONFIGURATION_BASED_NAME}~{part}").to_pylist() for part in PARTS}
    columns.update({part: [json.loads(cell) for cell in columns[part]] for part in JSON_PARTS})
    return {year: {part: columns[part][row] for part in PARTS} for row, year in enumerate(columns["year"])}


def _features(recipes_dir: Path) -> list[Feature | str]:
    return load_recipe(recipes_dir / KREIS_POPULATION_REBASED.file).features


def test_the_recipe_pins_the_captured_table_and_the_bbsr_file(recipes_dir: Path) -> None:
    destatis, bbsr = load_recipe(recipes_dir / KREIS_POPULATION_REBASED.file).compliance.sources
    assert destatis.sha256 == hashlib.sha256((FFCSV_FIXTURES / GOETTINGEN_ZIP).read_bytes()).hexdigest()
    assert destatis.credential_env == ["GENESIS_TOKEN"]
    assert (bbsr.sha256, bbsr.dataset_uri, bbsr.credential_env) == (BBSR_KREISE.sha256, BBSR_KREISE.url, [])


@respx.mock
def test_the_recipe_runs_to_the_expected_cells(recipes_dir: Path, genesis: Genesis, extract_keys: None) -> None:
    route = genesis({"12411-0015": GOETTINGEN_ZIP})
    result = run(_features(recipes_dir))
    table = result[0]
    with (EXPECTED_DIR / "expected-goettingen-2016.csv").open(encoding="utf-8", newline="") as handle:
        expected = [
            (r["key"], int(r["year"]), int(r["value"]), r["flag"], r["sources"]) for r in csv.DictReader(handle)
        ]
    rows = _rows(table)
    assert [
        (r["key"], year, round(r["value"]), r["flag"], "+".join(r["sources"])) for year, r in rows.items()
    ] == expected
    assert route.calls.call_count == 1
    steps = [step.feature_group_name for step in result.plan if step.step_kind == "compute"]
    assert steps == ["DestatisReader", "KreisRebaseFeature"]


@respx.mock
def test_zero_vs_missing_a_dash_outside_the_validity_is_not_applicable(
    recipes_dir: Path, genesis: Genesis, extract_keys: None
) -> None:
    genesis({"12411-0015": GOETTINGEN_ZIP})
    rows = _rows(run(_features(recipes_dir))[0])
    # 03159 carries "-" before the merger: its rows are re-based sums, flagged, and the sign is reported.
    for year in (2013, 2014, 2015):
        assert rows[year]["flag"] == "rebased" and rows[year]["value"] > 0
        assert any(
            i["kind"] == "not_applicable" and i["detail"].startswith("03159 does not exist before 31.12.2016")
            for i in rows[year]["issues"]
        )
    # The observed cells are numbers: no sign survives on them, and no output value is a zero.
    assert {rows[year]["marker"] for year in rows} == {""}
    assert 0.0 not in {rows[year]["value"] for year in rows}
    # The retired keys' "-" from 2016 on never enters a sum; it is reported with the provenance instead.
    elsewhere = {(i["kind"], i["key"], i["year"]) for i in rows[2016]["provenance"]["issues_elsewhere"]}
    assert {("not_applicable", key, year) for key in ("03152", "03156") for year in (2016, 2017)} <= elsewhere


@respx.mock
def test_zero_vs_missing_a_numeric_zero_where_genesis_writes_a_dash_is_refused(
    recipes_dir: Path, genesis: Genesis, extract_keys: None
) -> None:
    def zero_for_03159_in_2015(row: str) -> str:
        return (
            row.replace(";03159;Göttingen, Landkreis;-;", ";03159;Göttingen, Landkreis;0;")
            if "2015-12-31" in row
            else row
        )

    genesis({"12411-0015": ffcsv_zip_with_rows((FFCSV_FIXTURES / GOETTINGEN_ZIP).read_bytes(), zero_for_03159_in_2015)})
    with pytest.raises(ValidityError):
        run(_features(recipes_dir))
