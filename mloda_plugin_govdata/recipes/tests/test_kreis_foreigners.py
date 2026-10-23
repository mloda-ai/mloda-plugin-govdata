"""kreis_foreigners_share: two Destatis selections as two frames, the share computable, '-' told apart from a count."""

import hashlib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import respx

from mloda_plugin_govdata.recipes import load_recipe
from scripts.write_recipes import FOREIGNERS, GOETTINGEN, KEY, KREIS_FOREIGNERS_SHARE

from .conftest import FFCSV_FIXTURES, FOREIGNERS_ZIP, GOETTINGEN_ZIP, run

Genesis = Callable[[Mapping[str, str | bytes]], respx.Route]
SEX_LABEL = "2_variable_attribute_label"
Rows = dict[tuple[str, int], dict[str, Any]]


def _by_key_and_year(table: Any, *, only: Callable[[dict[str, Any]], bool] = lambda row: True) -> Rows:
    names = table.schema.names
    rows = [dict(zip(names, values)) for values in zip(*(table.column(n).to_pylist() for n in names))]
    return {(row[KEY], row["time"]): row for row in rows if only(row)}


def _frames(recipes_dir: Path) -> tuple[Rows, Rows]:
    """The total rows of the foreigners table and the population rows, keyed by Kreis and year."""
    result = run(load_recipe(recipes_dir / KREIS_FOREIGNERS_SHARE.file).features)
    by_table = {}
    for step, frame in result.frames():
        # The table code: mloda masks a dict pointer's values in the step options.
        assert step.data_access_identity is not None, step
        by_table[step.data_access_identity] = frame
    assert len(by_table) == 2, by_table
    foreigners, population = by_table[FOREIGNERS["name"]], by_table[GOETTINGEN["name"]]
    assert (foreigners.num_rows, population.num_rows) == (45, 15)
    totals = _by_key_and_year(foreigners, only=lambda row: row[SEX_LABEL] == "Insgesamt")
    assert len(totals) == 15 and all(row["2_variable_attribute_code"] is None for row in totals.values())
    return totals, _by_key_and_year(population)


def test_the_recipe_pins_both_captured_tables(recipes_dir: Path) -> None:
    foreigners, population = load_recipe(recipes_dir / KREIS_FOREIGNERS_SHARE.file).compliance.sources
    assert foreigners.sha256 == hashlib.sha256((FFCSV_FIXTURES / FOREIGNERS_ZIP).read_bytes()).hexdigest()
    assert population.sha256 == hashlib.sha256((FFCSV_FIXTURES / GOETTINGEN_ZIP).read_bytes()).hexdigest()
    assert {source.credential_env[0] for source in (foreigners, population)} == {"GENESIS_TOKEN"}


@respx.mock
def test_the_two_selections_come_back_as_two_frames_and_the_share_follows(recipes_dir: Path, genesis: Genesis) -> None:
    route = genesis({"12521-0040": FOREIGNERS_ZIP, "12411-0015": GOETTINGEN_ZIP})
    totals, residents = _frames(recipes_dir)
    assert route.calls.call_count == 2
    assert totals[("03159", 2016)]["value"] / residents[("03159", 2016)]["value"] == 28035 / 327065
    assert totals[("03159", 2017)]["value"] / residents[("03159", 2017)]["value"] == 28955 / 328036


@respx.mock
def test_zero_vs_missing_a_dash_keeps_its_sign_next_to_the_zero_on_both_sides(
    recipes_dir: Path, genesis: Genesis
) -> None:
    genesis({"12521-0040": FOREIGNERS_ZIP, "12411-0015": GOETTINGEN_ZIP})
    totals, residents = _frames(recipes_dir)
    for rows in (totals, residents):
        # Before the merger 03159 does not exist, after it 03152 and 03156 do not: GENESIS writes "-", the
        # parser reads 0 and keeps the sign, so the cell is told apart from a counted zero by its marker.
        for key, year in (("03159", 2013), ("03159", 2015), ("03152", 2016), ("03156", 2017)):
            assert (rows[(key, year)]["value"], rows[(key, year)]["value_marker"]) == (0.0, "-")
        # A counted cell carries no sign, and no counted cell in this selection is a zero.
        assert rows[("03152", 2013)]["value_marker"] == ""
        assert all(row["value"] > 0 for row in rows.values() if row["value_marker"] == "")
    assert totals[("03152", 2013)]["value"] == 17794 and residents[("03152", 2013)]["value"] == 248249
    # A share that respects the marker is defined exactly where both sides are counted.
    defined = {key for key in totals if totals[key]["value_marker"] == "" and residents[key]["value_marker"] == ""}
    assert defined == {("03152", y) for y in (2013, 2014, 2015)} | {("03156", y) for y in (2013, 2014, 2015)} | {
        ("03159", 2016),
        ("03159", 2017),
    }
