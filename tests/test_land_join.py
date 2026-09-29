"""Land-level join of Destatis DLAND with Bundeswahlleiterin results (Nr); key columns line up without
name mapping. ``LandPopulationPerVoter`` is the consumer FeatureGroup mloda's join fires for."""

from pathlib import Path
from typing import Any

import httpx
import pyarrow as pa
import pytest
import respx
from mloda.steward import Extender, ExtenderHook, HookContext
from mloda.user import Feature, PluginCollector, mloda

from mloda_plugin_govdata.feature_groups.destatis import DestatisReader, parse_ffcsv_zip
from mloda_plugin_govdata.feature_groups.destatis.core.hosts import GENESIS_ONLINE
from mloda_plugin_govdata.feature_groups.govdata import BundeswahlleiterinReader, GovDataFeature, GovDataLocator
from mloda_plugin_govdata.feature_groups.harmonization.core.land_codes import check_land_names
from mloda_plugin_govdata.feature_groups.land_population_per_voter import (
    KERG_URL,
    LAND_LOCATOR,
    PARTS,
    VOTERS,
    LandPopulationPerVoter,
)

FEATURE_GROUPS = Path(__file__).resolve().parents[1] / "mloda_plugin_govdata" / "feature_groups"
LAND_TABLE_ZIP = FEATURE_GROUPS / "destatis" / "tests" / "fixtures" / "ffcsv" / "12411-0010_2024_de_flat.zip"
KERG_SAMPLE = FEATURE_GROUPS / "govdata" / "tests" / "fixtures" / "kerg_sample.csv"
LAND_CODES = {f"{n:02d}" for n in range(1, 17)}
TOKEN = "test-token"


def _mock_both_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(DestatisReader, "cache_dir", str(tmp_path))
    monkeypatch.setattr(BundeswahlleiterinReader, "cache_dir", str(tmp_path))
    monkeypatch.setenv("GENESIS_TOKEN", TOKEN)
    respx.post(GENESIS_ONLINE.base_url + "data/tablefile").mock(
        return_value=httpx.Response(
            200, content=LAND_TABLE_ZIP.read_bytes(), headers={"content-type": "application/octet-stream"}
        )
    )
    respx.get(KERG_URL).mock(
        return_value=httpx.Response(200, content=KERG_SAMPLE.read_bytes(), headers={"ETag": '"k1"'})
    )


def test_land_keys_line_up_without_name_mapping() -> None:
    destatis = parse_ffcsv_zip(LAND_TABLE_ZIP.read_bytes())
    kerg = BundeswahlleiterinReader._parse(KERG_SAMPLE, GovDataLocator.from_string(KERG_URL))

    assert destatis.column("1_variable_code").to_pylist() == ["DLAND"] * 16
    assert set(destatis.column("1_variable_attribute_code").to_pylist()) == LAND_CODES
    assert destatis.schema.field("1_variable_attribute_code").type == pa.string()

    parents = kerg.column("gehört zu").to_pylist()
    land_keys = {nr for nr, parent in zip(kerg.column("Nr").to_pylist(), parents) if parent == "99"}
    assert land_keys == LAND_CODES
    assert kerg.schema.field("Nr").type == pa.string()
    # Wahlkreis numbers (and the federal total, Nr 99, in the full file) never collide with a Land code,
    # so an inner join on Nr keeps exactly the 16 Land rows.
    others = set(kerg.column("Nr").to_pylist()) - LAND_CODES
    assert others and LAND_CODES.isdisjoint(others)


def _expected_ratios() -> dict[str, float]:
    """Population per voter per Land, computed independently of ``LandPopulationPerVoter``."""
    destatis = parse_ffcsv_zip(LAND_TABLE_ZIP.read_bytes())
    population = dict(
        zip(destatis.column("1_variable_attribute_code").to_pylist(), destatis.column("value").to_pylist())
    )
    kerg = BundeswahlleiterinReader._parse(KERG_SAMPLE, GovDataLocator.from_string(KERG_URL))
    rows = zip(kerg.column("Nr").to_pylist(), kerg.column("gehört zu").to_pylist(), kerg.column(VOTERS).to_pylist())
    voters = {nr: count for nr, parent, count in rows if parent == "99"}
    assert set(population) == set(voters) == LAND_CODES
    return {key: population[key] / voters[key] for key in LAND_CODES}


@respx.mock
def test_land_join_through_mloda(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_both_sources(tmp_path, monkeypatch)

    result = mloda.run_all(
        [Feature(LandPopulationPerVoter.NAME)],
        compute_frameworks=["PyArrowTable"],
        # Only the two groups the join needs resolve features, so no other registered group can claim a column.
        plugin_collector=PluginCollector.enabled_feature_groups({GovDataFeature, LandPopulationPerVoter}),
    )

    table = result[0]
    assert table.num_rows == 16
    assert set(table.schema.names) == {f"{LandPopulationPerVoter.NAME}~{part}" for part in PARTS}
    assert [step.step_kind for step in result.plan].count("join") == 1
    codes = table.column(f"{LandPopulationPerVoter.NAME}~code").to_pylist()
    assert codes == sorted(codes)  # sorted by Land code, not join order
    check_land_names(zip(codes, table.column(f"{LandPopulationPerVoter.NAME}~land").to_pylist()))
    actual = dict(zip(codes, table.column(f"{LandPopulationPerVoter.NAME}~value").to_pylist()))
    assert actual == pytest.approx(_expected_ratios())


class _LoadIdentities(Extender):
    """Records the name each data load hands to extenders (lineage, audit, tracing), per reader."""

    def __init__(self) -> None:
        self.seen: dict[str | None, str | None] = {}

    def wraps(self) -> set[ExtenderHook]:
        return {ExtenderHook.INPUT_DATA_LOAD}

    def __call__(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        context = HookContext.current()
        assert context is not None
        self.seen[context.data_access_format] = context.data_access_identity
        return func(*args, **kwargs)


@respx.mock
def test_each_source_keeps_its_own_name_for_extenders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_both_sources(tmp_path, monkeypatch)
    recorder = _LoadIdentities()

    mloda.run_all(
        [Feature(LandPopulationPerVoter.NAME)],
        compute_frameworks=["PyArrowTable"],
        plugin_collector=PluginCollector.enabled_feature_groups({GovDataFeature, LandPopulationPerVoter}),
        function_extender={recorder},
    )

    # mloda's default would name both loads by their locator type alone.
    assert recorder.seen == {DestatisReader.__name__: LAND_LOCATOR["name"], BundeswahlleiterinReader.__name__: KERG_URL}
