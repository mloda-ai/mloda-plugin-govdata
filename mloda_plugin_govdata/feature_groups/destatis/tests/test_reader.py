"""DestatisReader: locator dispatch, peek without credentials, end-to-end via mloda.run_all."""

import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
import respx
from mloda.provider import FeatureSet
from mloda.user import Feature, FeatureName, Options, mloda
from mloda_plugins.feature_group.input_data.read_file import ReadFile

from mloda_plugin_govdata.feature_groups.destatis.core.cache import ParameterCache
from mloda_plugin_govdata.feature_groups.destatis.core.hosts import GENESIS_ONLINE
from mloda_plugin_govdata.feature_groups.destatis.locator import DestatisLocator
from mloda_plugin_govdata.feature_groups.destatis.reader import DestatisReader
from mloda_plugin_govdata.feature_groups.govdata.core.locator import GovDataLocator
from mloda_plugin_govdata.feature_groups.govdata.feature import GovDataFeature
from mloda_plugin_govdata.feature_groups.govdata.reader import BaseGovDataReader

FFCSV_FIXTURE = "21611-0002_de_flat.zip"
TABLE_CODE = "21611-0002"
TOKEN = "t0kenAbCdEf0123456789abcdef012345"


class _FakeFeatureSet:
    """Just enough FeatureSet surface for load_data; mirrors govdata/tests/test_reader.py."""

    def __init__(self, names: set[str], options: Options | None = None) -> None:
        self._names = tuple(sorted(FeatureName(name) for name in names))
        self.options = options

    def get_all_names(self) -> tuple[str, ...]:
        return self._names


def _mock_tablefile(zip_bytes: bytes) -> respx.Route:
    return respx.post(GENESIS_ONLINE.base_url + "data/tablefile").mock(
        return_value=httpx.Response(200, content=zip_bytes, headers={"content-type": "application/octet-stream"})
    )


def test_destatis_reader_uses_the_shared_root_feature_group() -> None:
    assert isinstance(GovDataFeature.input_data(), BaseGovDataReader)


def test_destatis_reader_classifies_as_a_final_reader() -> None:
    assert DestatisReader.final_reader_anchor() is ReadFile
    assert DestatisReader.is_final_reader() is True


def test_class_options_key_normalizes_to_reader_name() -> None:
    options = Options(cast(dict[str, Any], {DestatisReader: TABLE_CODE}))
    assert options.get(DestatisReader.__name__) == TABLE_CODE


def test_destatis_option_never_yields_a_govdata_locator() -> None:
    matched = DestatisReader.match_subclass_data_access(TABLE_CODE, ["value"], Options({}))
    assert matched == DestatisLocator(TABLE_CODE)
    assert not isinstance(matched, GovDataLocator)


@respx.mock
def test_load_data_level2_string_locator(fixtures_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(DestatisReader, "cache_dir", str(tmp_path))
    monkeypatch.setenv("GENESIS_TOKEN", TOKEN)
    zip_bytes = (fixtures_dir / "ffcsv" / FFCSV_FIXTURE).read_bytes()
    route = _mock_tablefile(zip_bytes)
    result = mloda.run_all(
        [Feature("value", options={DestatisReader.__name__: TABLE_CODE})],
        compute_frameworks=["PyArrowTable"],
    )
    table = result[0]
    assert table.num_rows == 207
    assert route.calls.call_count == 1
    sent = route.calls.last.request.content.decode("utf-8")
    assert "language=de" in sent and "format=ffcsv" in sent


@respx.mock
def test_load_data_level2_dict_locator(fixtures_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(DestatisReader, "cache_dir", str(tmp_path))
    monkeypatch.setenv("GENESIS_TOKEN", TOKEN)
    zip_bytes = (fixtures_dir / "ffcsv" / FFCSV_FIXTURE).read_bytes()
    _mock_tablefile(zip_bytes)
    result = mloda.run_all(
        [Feature("value", options={DestatisReader.__name__: {"name": TABLE_CODE, "quality": True}})],
        compute_frameworks=["PyArrowTable"],
    )
    assert result[0].num_rows == 207


@respx.mock
def test_load_data_level2_class_key_locator(
    fixtures_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(DestatisReader, "cache_dir", str(tmp_path))
    monkeypatch.setenv("GENESIS_TOKEN", TOKEN)
    zip_bytes = (fixtures_dir / "ffcsv" / FFCSV_FIXTURE).read_bytes()
    _mock_tablefile(zip_bytes)
    result = mloda.run_all(
        [Feature("value", options=cast(dict[str, Any], {DestatisReader: DestatisLocator(TABLE_CODE)}))],
        compute_frameworks=["PyArrowTable"],
    )
    assert result[0].num_rows == 207


@respx.mock
def test_resolves_without_explicit_compute_framework(
    fixtures_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # As in govdata/tests/test_reader.py: GovDataFeature must not collide with the built-in ReadFileFeature,
    # so run_all with no compute_frameworks pin still resolves to one group.
    monkeypatch.setattr(DestatisReader, "cache_dir", str(tmp_path))
    monkeypatch.setenv("GENESIS_TOKEN", TOKEN)
    zip_bytes = (fixtures_dir / "ffcsv" / FFCSV_FIXTURE).read_bytes()
    _mock_tablefile(zip_bytes)
    result = mloda.run_all([Feature("value", options={DestatisReader.__name__: TABLE_CODE})])
    assert result[0].num_rows == 207


@respx.mock
def test_peek_and_fetch_without_credentials_on_a_cache_hit(
    fixtures_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for var in ("GENESIS_TOKEN", "GENESIS_USER", "GENESIS_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(DestatisReader, "cache_dir", str(tmp_path))
    zip_bytes = (fixtures_dir / "ffcsv" / FFCSV_FIXTURE).read_bytes()
    locator = DestatisLocator(TABLE_CODE)
    fields = locator.tablefile_fields()
    ParameterCache(tmp_path).store(GENESIS_ONLINE, "data/tablefile", fields, zip_bytes)

    columns = DestatisReader.peek(TABLE_CODE)
    payload = DestatisReader._fetch(locator)

    assert columns["value"] == "double"
    assert columns["time"] == "int64"
    assert payload.provenance.source == "genesis"
    assert payload.provenance.url == GENESIS_ONLINE.url("data/tablefile")
    assert payload.provenance.parameters["name"] == TABLE_CODE
    assert respx.calls.call_count == 0


@respx.mock
def test_peek_without_credentials_raises_on_a_cache_miss(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("GENESIS_TOKEN", "GENESIS_USER", "GENESIS_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(DestatisReader, "cache_dir", str(tmp_path))
    with pytest.raises(Exception, match="No credentials"):
        DestatisReader.peek(TABLE_CODE)
    assert respx.calls.call_count == 0


@pytest.mark.parametrize(
    ("locator", "identity"),
    [
        (DestatisLocator(TABLE_CODE), TABLE_CODE),
        (DestatisLocator(TABLE_CODE, regionalkey=("01",), startyear=2020), TABLE_CODE),  # the selection is left out
        (DestatisLocator("13211-02-05-4", host="regionalstatistik"), "13211-02-05-4@regionalstatistik"),
    ],
)
def test_data_access_identity_is_the_table_code(locator: DestatisLocator, identity: str) -> None:
    assert DestatisReader.data_access_identity(locator) == identity


@respx.mock
def test_explicit_credentials_from_options_are_used_over_env(
    fixtures_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mloda_plugin_govdata.feature_groups.destatis.core.auth import OPTION_GENESIS_CREDENTIALS, DestatisCredentials

    monkeypatch.setenv("GENESIS_TOKEN", "envTokenAbCdEf0123456789abcdef0123")
    for var in ("GENESIS_USER", "GENESIS_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(DestatisReader, "cache_dir", str(tmp_path))
    zip_bytes = (fixtures_dir / "ffcsv" / FFCSV_FIXTURE).read_bytes()
    route = _mock_tablefile(zip_bytes)
    result = mloda.run_all(
        [
            Feature(
                "value",
                options=Options(
                    group={DestatisReader.__name__: TABLE_CODE},
                    context={OPTION_GENESIS_CREDENTIALS: DestatisCredentials(token=TOKEN)},
                ),
            )
        ],
        compute_frameworks=["PyArrowTable"],
    )
    assert result[0].num_rows == 207
    assert route.calls.last.request.headers["username"] == TOKEN


@respx.mock
def test_unknown_feature_names_available_columns(
    fixtures_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(DestatisReader, "cache_dir", str(tmp_path))
    monkeypatch.setenv("GENESIS_TOKEN", TOKEN)
    zip_bytes = (fixtures_dir / "ffcsv" / FFCSV_FIXTURE).read_bytes()
    _mock_tablefile(zip_bytes)
    features = cast(FeatureSet, _FakeFeatureSet({"value", "not_a_column"}))
    with pytest.raises(ValueError) as excinfo:
        DestatisReader.load_data(TABLE_CODE, features)
    message = str(excinfo.value)
    assert "Unknown feature(s) 'not_a_column'" in message
    assert "value" in message


_SUBPROCESS_SCRIPT = textwrap.dedent(
    """
    import sys
    import httpx
    import respx
    from mloda.user import Feature, mloda

    fixture_zip, cache_dir = sys.argv[1], sys.argv[2]

    # Only the documented Destatis surface; registration must not depend on also
    # importing mloda_plugin_govdata.feature_groups.govdata directly.
    from mloda_plugin_govdata.feature_groups.destatis import DestatisReader
    from mloda_plugin_govdata.feature_groups.destatis.core.hosts import GENESIS_ONLINE

    # The reader layer imports nothing from the layers built on it.
    reader_layer = tuple(f"mloda_plugin_govdata.feature_groups.{p}" for p in ("destatis", "govdata"))
    ours = (m for m in sys.modules if m.startswith("mloda_plugin_govdata."))
    leaked = sorted(m for m in ours if m != "mloda_plugin_govdata.feature_groups" and not m.startswith(reader_layer))
    assert not leaked, leaked

    DestatisReader.cache_dir = cache_dir
    with open(fixture_zip, "rb") as handle:
        zip_bytes = handle.read()

    with respx.mock:
        respx.post(GENESIS_ONLINE.base_url + "data/tablefile").mock(
            return_value=httpx.Response(200, content=zip_bytes, headers={"content-type": "application/octet-stream"})
        )
        result = mloda.run_all(
            [Feature("value", options={DestatisReader.__name__: "21611-0002"})],
            compute_frameworks=["PyArrowTable"],
        )
    table = result[0]
    assert table.num_rows == 207, table.num_rows
    compute_steps = [step for step in result.plan if step.step_kind == "compute"]
    assert [step.feature_group_name for step in compute_steps] == ["GovDataFeature"], compute_steps
    print("OK")
    """
)


def test_registration_in_a_fresh_subprocess_with_only_destatis_imported(
    fixtures_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GENESIS_TOKEN", TOKEN)
    zip_path = fixtures_dir / "ffcsv" / FFCSV_FIXTURE
    completed = subprocess.run(
        [sys.executable, "-c", _SUBPROCESS_SCRIPT, str(zip_path), str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert completed.stdout.strip() == "OK"
