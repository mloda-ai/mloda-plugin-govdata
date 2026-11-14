"""A chained request with its locator in options and its token in the collection resolves in a fresh interpreter."""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

from .conftest import GOETTINGEN_ZIP

_SCRIPT = textwrap.dedent(
    """
    import json
    import sys
    import httpx
    import respx
    from mloda.user import Credential, DataAccessCollection, Feature, Options, mloda

    fixture_zip, keys_xlsx, cache_dir = sys.argv[1:4]

    # Only the documented surface: the harmonization package registers the derived groups, the
    # Destatis package the reader.
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

    locator = {
        "name": "12411-0015",
        "regionalvariable": "KREISE",
        "regionalkey": ["03152", "03156", "03159"],
        "startyear": 2013,
        "endyear": 2017,
    }
    feature = Feature(
        "destatis__bevoelkerung__kreise",
        Options(
            group={DestatisReader.__name__: locator, "rebase_from_year": 2015, "rebase_to_year": 2016},
            context={"in_features": "value"},
        ),
    )
    collection = DataAccessCollection(credentials={"genesis": Credential(token="sub-token-0123456789")})
    with respx.mock:
        route = respx.post(GENESIS_ONLINE.base_url + "data/tablefile").mock(
            return_value=httpx.Response(200, content=zip_bytes, headers={"content-type": "application/octet-stream"})
        )
        result = mloda.run_all([feature], compute_frameworks=["PyArrowTable"], data_access_collection=collection)
    assert route.calls.last.request.headers["username"] == "sub-token-0123456789"
    table = result[0]
    values = table.column("destatis__bevoelkerung__kreise~value").to_pylist()
    assert values == [322616.0, 324013.0, 329538.0, 327065.0, 328036.0], values
    provenance = json.loads(table.column("destatis__bevoelkerung__kreise~provenance").to_pylist()[0])
    assert provenance["sheet"] == "2015-2016", provenance
    compute = [step for step in result.plan if step.step_kind == "compute"]
    steps = [(step.feature_group_name, step.bound_credential_handle) for step in compute]
    assert steps == [("DestatisReader", "genesis"), ("KreisRebaseFeature", None)], steps
    print("OK")
    """
)


def test_chained_request_resolves_in_a_fresh_subprocess(
    ffcsv_fixtures_dir: Path, reference_fixtures_dir: Path, tmp_path: Path
) -> None:
    keys = reference_fixtures_dir / "bbsr-ref-kreise-extract.xlsx"
    completed = subprocess.run(
        [sys.executable, "-c", _SCRIPT, str(ffcsv_fixtures_dir / GOETTINGEN_ZIP), str(keys), str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
        env={k: v for k, v in os.environ.items() if not k.startswith(("GENESIS_", "REGIONALSTATISTIK_"))},
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert completed.stdout.strip() == "OK"
    assert "sub-token-0123456789" not in completed.stdout + completed.stderr
