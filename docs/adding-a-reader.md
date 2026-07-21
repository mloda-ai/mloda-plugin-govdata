# Adding a Reader

`BaseGovDataReader` (in `mloda_plugin_govdata/feature_groups/govdata/reader.py`) does the plumbing: locator coercion, CKAN discovery, cached download with retries, and column selection. Subclasses implement `_parse` (or, for plain CSVs, just set `schema` on a `GovDataReader` subclass), plus `suffix` when the payload is not CSV. Each data source lives in its own module (`population.py`, `bundeswahlleiterin.py`, `uba.py`); shared source-agnostic code (client, cache, discovery, locator, CSV parsing) lives in `core/`.

To connect a new dataset:

1. Check whether `GovDataReader` already handles it. A GovData slug or a direct CSV URL with a regular single-row header needs no code; every column is read as a string. For typed columns, subclass `GovDataReader` in a new module and set `schema` (see `population.py`).
2. For a different payload shape, subclass `BaseGovDataReader` and implement `_parse` (and `suffix` for non-CSV payloads); `bundeswahlleiterin.py` and `uba.py` show the pattern.
3. Keep source-specific parse logic in the source's module as a `parse_*_bytes` function plus a path wrapper, like `uba.py`. Generic parsing belongs in `core/parse.py`. That keeps it testable from fixture files without network access.
4. Add tests under `mloda_plugin_govdata/feature_groups/govdata/tests/` with a small real sample in `tests/fixtures/`.
5. Export the reader from `feature_groups/govdata/__init__.py` and add a usage snippet to the README.
6. Run `tox` (pytest, ruff, mypy strict, bandit); it must pass before a PR.
