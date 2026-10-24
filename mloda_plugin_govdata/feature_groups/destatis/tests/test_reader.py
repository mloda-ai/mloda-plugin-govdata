"""DestatisReader: locator dispatch, peek without credentials, end-to-end via mloda.run_all."""

import inspect
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
import respx
from mloda.provider import FeatureSet, SourceMatch
from mloda.user import Credential, DataAccessCollection, Feature, FeatureName, Options, mloda

from mloda_plugin_govdata.feature_groups.destatis.core.auth import OPTION_GENESIS_CREDENTIALS, DestatisCredentials
from mloda_plugin_govdata.feature_groups.destatis.core.cache import ParameterCache
from mloda_plugin_govdata.feature_groups.destatis.core.hosts import GENESIS_ONLINE, REGIONALSTATISTIK
from mloda_plugin_govdata.feature_groups.destatis.locator import DestatisLocator
from mloda_plugin_govdata.feature_groups.destatis.reader import DestatisReader
from mloda_plugin_govdata.feature_groups.govdata.core.locator import GovDataLocator
from mloda_plugin_govdata.feature_groups.govdata.feature import GovDataFeature
from mloda_plugin_govdata.feature_groups.govdata.reader import BaseGovDataReader

FFCSV_FIXTURE = "21611-0002_de_flat.zip"
TABLE_CODE = "21611-0002"
TOKEN = "t0kenAbCdEf0123456789abcdef012345"


class _FakeFeatureSet:
    """Just enough FeatureSet surface for load_neutral; mirrors govdata/tests/test_reader.py."""

    def __init__(self, names: set[str], options: Options | None = None) -> None:
        self._names = tuple(sorted(FeatureName(name) for name in names))
        self.options = options

    def get_all_names(self) -> tuple[str, ...]:
        return self._names

    def get_sorted_features(self) -> tuple[Feature, ...]:
        return ()


def _mock_tablefile(zip_bytes: bytes) -> respx.Route:
    return respx.post(GENESIS_ONLINE.base_url + "data/tablefile").mock(
        return_value=httpx.Response(200, content=zip_bytes, headers={"content-type": "application/octet-stream"})
    )


def _match(value: object) -> SourceMatch:
    [match] = DestatisReader.find_sources(
        DestatisReader.CLAIM_ROUTES[0], "value", Options({DestatisReader.__name__: value}), None
    )
    return match


def test_destatis_reader_is_a_concrete_source_group_under_the_shared_root() -> None:
    assert issubclass(DestatisReader, BaseGovDataReader)
    assert issubclass(DestatisReader, GovDataFeature)
    assert not inspect.isabstract(DestatisReader)
    assert DestatisReader.pointer_keys() == (DestatisReader.__name__,)


def test_class_options_key_normalizes_to_reader_name() -> None:
    options = Options(cast(dict[str, Any], {DestatisReader: TABLE_CODE}))
    assert options.get(DestatisReader.__name__) == TABLE_CODE


def test_destatis_option_never_yields_a_govdata_locator() -> None:
    matched = DestatisReader._source_locator(TABLE_CODE, "value", Options({}))
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
    # As in govdata/tests/test_reader.py: the reader must not collide with mloda's own source groups,
    # so run_all with no compute_frameworks pin still resolves to one group.
    monkeypatch.setattr(DestatisReader, "cache_dir", str(tmp_path))
    monkeypatch.setenv("GENESIS_TOKEN", TOKEN)
    zip_bytes = (fixtures_dir / "ffcsv" / FFCSV_FIXTURE).read_bytes()
    _mock_tablefile(zip_bytes)
    result = mloda.run_all([Feature("value", options={DestatisReader.__name__: TABLE_CODE})])
    assert len(result[0]) == 207


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
    assert payload.provenance.license == DestatisReader.LICENSE == "DL-DE-BY-2.0"
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
    assert DestatisReader.data_access_identity(_match(locator)) == identity


def _requiring_license(value: str) -> Feature:
    return Feature("value", options={DestatisReader.__name__: TABLE_CODE}, required_declarations={"license": value})


def test_a_required_license_the_reader_declares_plans() -> None:
    assert mloda.explain([_requiring_license("DL-DE-BY-2.0")], compute_frameworks=["PyArrowTable"])


def test_a_required_license_the_reader_does_not_declare_is_refused_at_plan_time() -> None:
    with pytest.raises(ValueError, match="requires declared 'license' == 'CC-BY-4.0'"):
        mloda.explain([_requiring_license("CC-BY-4.0")], compute_frameworks=["PyArrowTable"])


ENV_TOKEN = "envTokenAbCdEf0123456789abcdef0123"


def _env_token_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GENESIS_TOKEN", ENV_TOKEN)
    for var in ("GENESIS_USER", "GENESIS_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(DestatisReader, "cache_dir", str(tmp_path))


@respx.mock
def test_explicit_credentials_from_options_are_used_over_env(
    fixtures_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _env_token_only(monkeypatch, tmp_path)
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
def test_another_plugins_token_is_never_sent_to_genesis(
    fixtures_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _env_token_only(monkeypatch, tmp_path)
    route = _mock_tablefile((fixtures_dir / "ffcsv" / FFCSV_FIXTURE).read_bytes())
    mloda.run_all(
        [Feature("value", options={DestatisReader.__name__: TABLE_CODE})],
        compute_frameworks=["PyArrowTable"],
        data_access_collection=DataAccessCollection(credentials={"hf": Credential(token=TOKEN)}),
    )
    assert route.calls.last.request.headers["username"] == ENV_TOKEN


@respx.mock
def test_explicit_credentials_win_over_the_collection_in_one_request(
    fixtures_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _env_token_only(monkeypatch, tmp_path)
    route = _mock_tablefile((fixtures_dir / "ffcsv" / FFCSV_FIXTURE).read_bytes())
    explicit = Feature(
        "value",
        options=Options(
            group={DestatisReader.__name__: TABLE_CODE},
            context={OPTION_GENESIS_CREDENTIALS: DestatisCredentials(token=TOKEN)},
        ),
    )
    plain = Feature("time", options={DestatisReader.__name__: TABLE_CODE})
    mloda.run_all(
        [plain, explicit],
        compute_frameworks=["PyArrowTable"],
        data_access_collection=DataAccessCollection(credentials={"genesis": Credential(token="collectionToken0123")}),
    )
    assert {call.request.headers["username"] for call in route.calls} == {TOKEN}


@respx.mock
def test_different_explicit_credentials_in_one_batch_are_refused(
    fixtures_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _env_token_only(monkeypatch, tmp_path)
    route = _mock_tablefile((fixtures_dir / "ffcsv" / FFCSV_FIXTURE).read_bytes())
    features: list[Feature | str] = [
        Feature(
            name,
            options=Options(
                group={DestatisReader.__name__: TABLE_CODE},
                context={OPTION_GENESIS_CREDENTIALS: DestatisCredentials(token=token)},
            ),
        )
        for name, token in (("value", TOKEN), ("time", ENV_TOKEN))
    ]
    with pytest.raises(ValueError, match="carry different explicit credentials"):
        mloda.run_all(features, compute_frameworks=["PyArrowTable"])
    assert route.calls.call_count == 0


@respx.mock
def test_describe_columns_uses_the_collection_credentials(
    fixtures_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_genesis_env: None
) -> None:
    monkeypatch.setattr(DestatisReader, "cache_dir", str(tmp_path))
    route = _mock_tablefile((fixtures_dir / "ffcsv" / FFCSV_FIXTURE).read_bytes())
    collection = DataAccessCollection(credentials={"genesis": Credential(token=TOKEN)})
    options = Options({DestatisReader.__name__: TABLE_CODE})
    [match] = DestatisReader.find_sources(DestatisReader.CLAIM_ROUTES[0], "value", options, collection)
    assert TOKEN not in repr(match) and DestatisReader.data_access_identity(match) == TABLE_CODE
    assert "value" in DestatisReader.describe_columns(match)
    assert route.calls.last.request.headers["username"] == TOKEN


@respx.mock
def test_an_ambiguous_collection_is_refused_at_match_time_without_a_request(
    fixtures_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Resolved while matching, so a cached selection fails too: a misconfigured collection never passes silently.
    _env_token_only(monkeypatch, tmp_path)
    route = _mock_tablefile((fixtures_dir / "ffcsv" / FFCSV_FIXTURE).read_bytes())
    collection = DataAccessCollection(
        credentials={"a": Credential(host="genesis", token=TOKEN), "b": Credential(host="genesis", token=ENV_TOKEN)}
    )
    with pytest.raises(ValueError, match="Several credentials for host 'genesis': a, b") as excinfo:
        mloda.run_all(
            [Feature("value", options={DestatisReader.__name__: TABLE_CODE})],
            compute_frameworks=["PyArrowTable"],
            data_access_collection=collection,
        )
    assert TOKEN not in str(excinfo.value) and route.calls.call_count == 0
    # An explicit per-feature override never consults the collection, so the ambiguity cannot block it.
    explicit = Options(
        group={DestatisReader.__name__: TABLE_CODE},
        context={OPTION_GENESIS_CREDENTIALS: DestatisCredentials(token=TOKEN)},
    )
    mloda.run_all(
        [Feature("value", options=explicit)],
        compute_frameworks=["PyArrowTable"],
        data_access_collection=collection,
    )
    assert route.calls.last.request.headers["username"] == TOKEN


@respx.mock
def test_collection_credentials_follow_the_host(
    fixtures_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_genesis_env: None
) -> None:
    monkeypatch.setattr(DestatisReader, "cache_dir", str(tmp_path))
    zip_bytes = (fixtures_dir / "ffcsv" / FFCSV_FIXTURE).read_bytes()
    regional = respx.post(REGIONALSTATISTIK.base_url + "data/tablefile").mock(
        return_value=httpx.Response(200, content=zip_bytes, headers={"content-type": "application/octet-stream"})
    )
    online = _mock_tablefile(zip_bytes)
    collection = DataAccessCollection(
        credentials={"genesis": Credential(token=TOKEN), "regionalstatistik": Credential(token="regionalToken0123")}
    )
    regional_table = DestatisLocator("13211-02-05-4", host="regionalstatistik")
    mloda.run_all(
        [
            Feature("value", options={DestatisReader.__name__: regional_table}),
            Feature("time", options={DestatisReader.__name__: TABLE_CODE}),
        ],
        compute_frameworks=["PyArrowTable"],
        data_access_collection=collection,
    )
    assert regional.calls.last.request.headers["username"] == "regionalToken0123"
    assert online.calls.last.request.headers["username"] == TOKEN


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
        DestatisReader.load_neutral(_match(TABLE_CODE), features)
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
    from mloda_plugin_govdata.feature_groups.destatis.core.hosts import GENESIS_ONLINE, REGIONALSTATISTIK

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
    assert [step.feature_group_name for step in compute_steps] == ["DestatisReader"], compute_steps
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
