# Adding a Reader

`BaseGovDataReader` (in `mloda_plugin_govdata/feature_groups/govdata/reader.py`) does the plumbing: locator coercion, CKAN discovery, cached download with retries, and column selection. Subclasses implement `_parse` (or, for plain CSVs, just set `schema` on a `GovDataReader` subclass). Each data source lives in its own module (`population.py`, `bundeswahlleiterin.py`, `uba.py`); shared source-agnostic code (client, cache, discovery, locator, CSV parsing) lives in `core/`. A source with its own client and locator gets its own package (`feature_groups/destatis/`).

A feature selects a reader with an option whose key is the reader class (or its class-name string); the value is what the reader's locator coerces. `BaseGovDataReader` is generic over its locator type: any class with `coerce(value) -> locator | None` (option value to locator, `None` when the value isn't usable) and `describe() -> str` (the dataset's label in error messages, and its `data_access_identity` in lineage and audit records, so never a credential; a URL label is cut to scheme, host and path), with `GovDataLocator` as the built-in one. `match_subclass_data_access` claims a request by coercing the locator and declines it with `None`; the file suffix is never consulted, so `suffix` only names the payload type (`ReadFile` declares it, nothing on this path reads it).

Every reader flows `load_data -> _read_table -> _fetch -> _parse`. The fetch seam is `_fetch(locator, options) -> FetchedPayload`, implemented in the base as CKAN discovery plus a cached GET; parsing then runs as `_parse(path, locator, options)`. A reader with its own locator type subclasses `BaseGovDataReader[ItsLocator]`, overrides `locator_type()`, and overrides `_fetch`, which opens its own client. For offline reruns, `DownloadCache.get_or_download(url, revalidate=False)` reads the cached body without issuing a request and raises `CacheMissError` on a miss.

To connect a new dataset:

1. Check whether `GovDataReader` already handles it. A GovData slug or a direct CSV URL with a regular single-row header needs no code; every column is read as a string. For typed columns, subclass `GovDataReader` in a new module and set `schema` (see `population.py`).
2. For a different payload shape, subclass `BaseGovDataReader[GovDataLocator]` and implement `_parse`; `bundeswahlleiterin.py` and `uba.py` show the pattern. For a source with its own locator type, also override `locator_type()` and `_fetch`; the Destatis path below shows a POST source with credentials.
3. Keep source-specific parse logic in the source's module as a `parse_*_bytes` function plus a path wrapper, like `uba.py`. Generic parsing belongs in `core/parse.py`. That keeps it testable from fixture files without network access.
4. Add tests in the `tests/` package next to the module (`feature_groups/govdata/tests/`, `feature_groups/destatis/tests/`) with a small real sample in its `fixtures/`, and record the sample's source and license in the `NOTICE` there.
5. Export the reader from the package `__init__.py` and add a usage snippet to [readers.md](readers.md).
6. Run `tox` (pytest, ruff, mypy strict, bandit); it must pass before a PR.

## The Destatis path: a POST source with credentials

`DestatisReader` (`feature_groups/destatis/reader.py`) reads one GENESIS `data/tablefile` selection. It differs from the GET readers in a few places.

**Locator.** `DestatisLocator` is a frozen dataclass (it hashes inside `Options.group`) with `coerce` for the option forms (bare table code, locator, dict), `from_dict` and `to_dict` for the JSON-native form a recipe file carries, and `describe`. The selection is validated at construction, so a bad table code fails before any request.

**Fetch.** `_fetch(locator, options)` resolves the host, takes explicit credentials from `Options.context` (`explicit_credentials_from_options`), builds the wire fields (`DestatisLocator.tablefile_fields()`, which pins `format`, `job`, `compress` and `transpose`), and calls `ParameterCache.get_or_fetch(host, "data/tablefile", fields, fetch)`. The cache keys the reply by the canonical parameters and calls `fetch` on a miss only; `GenesisClient` resolves credentials (explicit, then env) on its first request, so a cached selection needs none. The cached payload becomes a `FetchedPayload` with a `Provenance` (source, endpoint URL, parameters), and its path goes to `_parse`, which unpacks the zip and parses the ffcsv.

**Matching.** `match_subclass_data_access` declines any feature name containing mloda's chain separator (`value__rebased`), so the harmonization groups own chained names and the request stays unambiguous.

Tests live in `feature_groups/destatis/tests/`: replies are `respx` mocks over fixtures (live captures made with `scripts/capture_genesis_fixtures.py`, every secret redacted, plus documented and synthetic replies; the `NOTICE` there names each source), and the tests marked `live` and `genesis_live` run the real endpoints and skip with a visible reason when no credentials are set (see [credentials.md](credentials.md)).
