"""Recipes over captured fixtures in a fresh process: the loader registers the feature groups and mloda runs them."""

import hashlib
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from mloda_plugin_govdata.recipes import load_recipe
from scripts.write_recipes import RECIPES_DIR

from .conftest import FFCSV_FIXTURES, GOETTINGEN_ZIP, LAND_ZIP, REFERENCE_FIXTURES

LAND_TABLE_ZIP = FFCSV_FIXTURES / LAND_ZIP
LAND_RECIPE = RECIPES_DIR / "land_population.json"

_RUN_SCRIPT = textwrap.dedent(
    """
    import sys
    import httpx
    import respx
    from mloda.user import mloda

    # The only plugin import before loading: the loader must register the feature groups itself.
    from mloda_plugin_govdata.recipes import load_recipe

    recipe_path, fixture_zip, cache_dir = sys.argv[1:4]
    recipe = load_recipe(recipe_path)

    from mloda_plugin_govdata.feature_groups.destatis import DestatisReader
    from mloda_plugin_govdata.feature_groups.destatis.core.hosts import GENESIS_ONLINE

    DestatisReader.cache_dir = cache_dir
    with open(fixture_zip, "rb") as handle:
        zip_bytes = handle.read()
    with respx.mock:
        respx.post(GENESIS_ONLINE.base_url + "data/tablefile").mock(
            return_value=httpx.Response(200, content=zip_bytes, headers={"content-type": "application/octet-stream"})
        )
        result = mloda.run_all(recipe.features, compute_frameworks=["PyArrowTable"], links=set(recipe.links))
    table = result[0]
    assert table.num_rows == 16, table.num_rows
    assert sorted(table.column_names) == ["1_variable_attribute_code", "value"], table.column_names
    assert sorted(table.column("1_variable_attribute_code").to_pylist()) == [f"{n:02d}" for n in range(1, 17)]
    print("OK")
    """
)

_REBASE_SCRIPT = textwrap.dedent(
    """
    import sys
    import httpx
    import respx
    from mloda.user import mloda

    # Loading the recipe registers the harmonization groups; nothing else is imported first.
    from mloda_plugin_govdata.recipes import load_recipe

    recipe_path, fixture_zip, keys_xlsx, cache_dir = sys.argv[1:5]
    recipe = load_recipe(recipe_path)

    from mloda_plugin_govdata.feature_groups.destatis import DestatisReader
    from mloda_plugin_govdata.feature_groups.destatis.core.hosts import GENESIS_ONLINE
    from mloda_plugin_govdata.feature_groups.harmonization import KreisRebaseFeature
    from mloda_plugin_govdata.feature_groups.harmonization.core.reference.bbsr import parse_bbsr_kreise_workbook
    from mloda_plugin_govdata.feature_groups.harmonization.core.reference.sources import BBSR_KREISE

    DestatisReader.cache_dir = cache_dir
    rows = parse_bbsr_kreise_workbook(keys_xlsx)
    KreisRebaseFeature.load_keys = classmethod(lambda cls: (rows, BBSR_KREISE))
    with open(fixture_zip, "rb") as handle:
        zip_bytes = handle.read()
    with respx.mock:
        respx.post(GENESIS_ONLINE.base_url + "data/tablefile").mock(
            return_value=httpx.Response(200, content=zip_bytes, headers={"content-type": "application/octet-stream"})
        )
        result = mloda.run_all(recipe.features, compute_frameworks=["PyArrowTable"])
    values = result[0].column("destatis__bevoelkerung__kreise~value").to_pylist()
    assert values == [322616.0, 324013.0, 329538.0, 327065.0, 328036.0], values
    steps = [step.feature_group_name for step in result.plan if step.step_kind == "compute"]
    assert steps == ["DestatisReader", "KreisRebaseFeature"], steps
    print("OK")
    """
)

_LINK_SCRIPT = textwrap.dedent(
    """
    import sys
    from mloda_plugin_govdata.recipes import load_recipe

    recipe = load_recipe(sys.argv[1])

    from mloda.user import Feature
    from mloda_plugin_govdata.feature_groups.destatis import DestatisReader
    from mloda_plugin_govdata.feature_groups.govdata import BundeswahlleiterinReader

    (link,) = recipe.links
    assert link.left_feature_group is DestatisReader and link.right_feature_group is BundeswahlleiterinReader, link
    assert link.left_index.index == ("1_variable_attribute_code",) and link.right_index.index == ("Nr",), link
    # Each side's reader must be one the features point at, or mloda never matches the node.
    pointed = {key for feature in recipe.features if isinstance(feature, Feature) for key in feature.options.group}
    assert {DestatisReader.__name__, BundeswahlleiterinReader.__name__} <= pointed, pointed
    print("OK")
    """
)


@pytest.fixture(autouse=True)
def _no_genesis_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("GENESIS_TOKEN", "GENESIS_USER", "GENESIS_PASSWORD"):
        monkeypatch.delenv(name, raising=False)


def _fresh_process(script: str, *args: str) -> None:
    completed = subprocess.run([sys.executable, "-c", script, *args], capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert completed.stdout.strip() == "OK"


def test_land_population_pins_the_captured_payload() -> None:
    (source,) = load_recipe(LAND_RECIPE).compliance.sources
    assert source.sha256 == hashlib.sha256(LAND_TABLE_ZIP.read_bytes()).hexdigest()
    assert source.credential_env == ["GENESIS_TOKEN"]


def test_recipe_runs_through_mloda_in_a_fresh_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENESIS_TOKEN", "test-token")
    _fresh_process(_RUN_SCRIPT, str(LAND_RECIPE), str(LAND_TABLE_ZIP), str(tmp_path))


def test_the_rebased_recipe_runs_in_a_fresh_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENESIS_TOKEN", "test-token")
    keys = REFERENCE_FIXTURES / "bbsr-ref-kreise-extract.xlsx"
    recipe = RECIPES_DIR / "kreis_population_rebased.json"
    _fresh_process(_REBASE_SCRIPT, str(recipe), str(FFCSV_FIXTURES / GOETTINGEN_ZIP), str(keys), str(tmp_path))


def test_links_resolve_in_a_fresh_process() -> None:
    _fresh_process(_LINK_SCRIPT, str(RECIPES_DIR / "land_population_per_voter.json"))
