[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://github.com/mloda-ai/mloda-plugin-govdata/blob/main/LICENSE)
[![mloda](https://img.shields.io/badge/built%20with-mloda-blue.svg)](https://github.com/mloda-ai/mloda)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Tests](https://github.com/mloda-ai/mloda-plugin-govdata/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/mloda-ai/mloda-plugin-govdata/actions/workflows/test.yml?query=branch%3Amain)
[![Prototype Fund](https://img.shields.io/badge/Prototype%20Fund-Jahrgang%2002-f1c40f.svg)](https://prototypefund.de)

# mloda-plugin-govdata

Connectors for German open government data, built on [mloda](https://github.com/mloda-ai/mloda). Request the columns you want as mloda features; the plugin handles CKAN discovery, download with caching and retries, and parsing (German CSV or publisher JSON) into a typed Arrow table.

Three example datasets cover population (GovData CSV), elections (Bundeswahlleiterin `kerg.csv`), and environment (UBA Air Data JSON); the Destatis connector adds GENESIS tables. On top sit harmonization features (district series across boundary changes, NUTS codes, typed periods) and recipe files that record the source, license, and checksum behind a result.

## Status

Young but working. As of 0.3.0, the three example readers, the Destatis connector, the harmonization features, and the recipes run end to end, with paginated dataset search, cached downloads with retries, and unit plus property-based tests behind them. Every reader is a thin subclass of `BaseGovDataReader` that overrides the parse step (and the fetch step for a source with its own locator type); new datasets follow the same path (see [docs/adding-a-reader.md](https://github.com/mloda-ai/mloda-plugin-govdata/blob/main/docs/adding-a-reader.md)). How the packages fit together, and where to start for a change: [docs/architecture.md](https://github.com/mloda-ai/mloda-plugin-govdata/blob/main/docs/architecture.md). Development happens in a 6-month Prototype Fund stage (June to November 2026), so the API may still shift between releases; the [release notes](https://github.com/mloda-ai/mloda-plugin-govdata/releases) list each breaking change with its migration. This version needs mloda 0.13.

## Usage

### GovData readers

Read the Stuttgart population dataset (via GovData) as a typed PyArrow table:

```python
from mloda.user import Feature, mloda
from mloda_plugin_govdata.feature_groups.govdata import StuttgartPopulationReader

slug = "einwohner-nach-altersgruppen-und-stadtbezirken"
result = mloda.run_all(
    [
        Feature("Einwohner", options={StuttgartPopulationReader: slug}),
        Feature("Stadtbezirk", options={StuttgartPopulationReader: slug}),
    ],
    compute_frameworks=["PyArrowTable"],
)
table = result[0]  # pyarrow.Table with the requested columns
result.plan  # resolved execution steps: which FeatureGroup ran on which framework
```

The options key is the reader class or its class-name string; both select the same reader. The option value is a GovData dataset slug or a direct distribution URL. The license is read from the CKAN distribution metadata. Set `BaseGovDataReader.cache_dir` to control where downloads are cached (harmonized features below use a separate `HarmonizationFeature.cache_dir`). For any other GovData CSV dataset, `GovDataReader` works out of the box and reads every column as a string; subclass it and set `schema` for typed columns.

Don't know the slug yet? Search GovData with the paginated CKAN `package_search` API:

```python
from mloda_plugin_govdata.feature_groups.govdata import build_client, search_datasets

with build_client() as client:
    for dataset in search_datasets(client, "einwohner stuttgart", max_results=10):
        print(dataset.name, "|", dataset.title)
```

`search_datasets` walks the result pages lazily (`page_size` per request) and stops at `max_results` or the end of the result set.

Got a slug but not the column names? `peek` lists what you can request as features:

```python
StuttgartPopulationReader.peek(slug)  # {"Stichtag": "date32[day]", "Stadtbezirk": "string", ...}
```

It works on every reader (`BundeswahlleiterinReader.peek(kerg)`, `UbaAirReader.peek(uba_measures_url(...))`) and downloads through the cache, so the actual feature request reuses the file. `peek` takes a raw URL, bypassing the `READER_OPTIONS` validation below. A typo in a feature name fails with the available columns and a close-match suggestion instead of a raw KeyError.

The elections reader handles a direct CSV URL whose file has a multi-row merged header (Bundeswahlleiterin `kerg.csv`):

```python
from mloda_plugin_govdata.feature_groups.govdata import BundeswahlleiterinReader

kerg = "https://www.bundeswahlleiterin.de/bundestagswahlen/2025/ergebnisse/opendata/btw25/csv/kerg.csv"
result = mloda.run_all(
    [Feature("Gebiet", options={BundeswahlleiterinReader: kerg})],
    compute_frameworks=["PyArrowTable"],
)
```

The environment reader fetches the Umweltbundesamt (UBA) Air Data v4 `measures` endpoint (REST JSON) and flattens it to one typed row per station and timestamp. Query parameters are per-feature options, not a pre-built URL (here: hourly ozone at station 143); a bad value is rejected during feature resolution, before any network call:

```python
from mloda_plugin_govdata.feature_groups.govdata import (
    OPTION_UBA_COMPONENT,
    OPTION_UBA_DATE_FROM,
    OPTION_UBA_DATE_TO,
    OPTION_UBA_SCOPE,
    OPTION_UBA_STATION,
    UbaAirReader,
)

uba_options = {
    UbaAirReader: True,
    OPTION_UBA_STATION: 143,
    OPTION_UBA_COMPONENT: 3,
    OPTION_UBA_SCOPE: 2,
    OPTION_UBA_DATE_FROM: "2025-01-01",
    OPTION_UBA_DATE_TO: "2025-01-01",
}
result = mloda.run_all(
    [
        Feature("date_start", options=uba_options),
        Feature("value", options=uba_options),
    ],
    compute_frameworks=["PyArrowTable"],
)
```

Columns are `station_id`, `date_start`, `component_id`, `scope_id`, `value`, `date_end`, and `index` (the air-quality index). Component and scope ids come from the UBA `components` and `scopes` endpoints.

### Destatis

The Destatis connector reads a GENESIS table (Statistisches Bundesamt or a Regionalstatistik installation) by table code, needs a free registration (`GENESIS_TOKEN` or `GENESIS_USER` / `GENESIS_PASSWORD`; see [docs/credentials.md](https://github.com/mloda-ai/mloda-plugin-govdata/blob/main/docs/credentials.md)), and parses the ffcsv reply:

```python
from mloda_plugin_govdata.feature_groups.destatis import DestatisReader

result = mloda.run_all(
    [Feature("value", options={DestatisReader: "12411-0010"})],  # population by Land
    compute_frameworks=["PyArrowTable"],
)
```

The option value is a bare table code (the server's default years), a `DestatisLocator`, or its dict form; the latter two narrow the selection by region, years, and classifying variables, and the dict form round-trips through a recipe file. See [docs/destatis-options.md](https://github.com/mloda-ai/mloda-plugin-govdata/blob/main/docs/destatis-options.md) for the full parameter table. `peek` lists the ffcsv columns the same way as the other readers.

### Harmonization

Harmonized features chain an operation onto a reader column (`<column>__<operation>`): `value__rebased` re-bases a Kreis series onto a later Gebietsstand with the BBSR keys, `1_variable_attribute_code__nuts2024` adds NUTS codes to Kreis and Gemeinde keys, and `time__year_period` types the period. A feature with several output columns returns them as `<name>~<part>`, mloda's multi-output convention: `value__rebased~key`, `value__rebased~flag`, and so on. `value__rebased` and `__nuts2024` read their reference tables offline from `HarmonizationFeature.cache_dir`, so fetch them once first; see [docs/harmonization.md](https://github.com/mloda-ai/mloda-plugin-govdata/blob/main/docs/harmonization.md) for the example, the options, and the one-time fetch.

Why re-basing matters: Landkreis Göttingen (`03152`) and Osterode am Harz (`03156`) merged into `03159` in November 2016. GENESIS table `12411-0015` reports each key only for the years it existed and marks the rest `-` ("nichts vorhanden"), which a plain parse turns into 0. `value__rebased` with `rebase_from_year=2015` and `rebase_to_year=2016` returns one series on the 2016 borders:

```
~key   ~year  ~value    ~flag     ~sources
03159  2013   322616.0  rebased   ["03152", "03156"]
03159  2014   324013.0  rebased   ["03152", "03156"]
03159  2015   329538.0  rebased   ["03152", "03156"]
03159  2016   327065.0  observed  []
03159  2017   328036.0  observed  []
```

### Recipes

A recipe file bundles the features, joins, and provenance of one run as JSON; `load_recipe` returns what `mloda.run_all` needs plus the compliance block (license, attribution, payload sha256, credential env names). Recipes ship under `recipes/` in the repository, not in the published package: the Land table, the re-based Kreis series, a rate with its denominator, the Land-level join, and the three example datasets above. See [docs/recipes.md](https://github.com/mloda-ai/mloda-plugin-govdata/blob/main/docs/recipes.md).

```python
from mloda_plugin_govdata.recipes import load_recipe

recipe = load_recipe("recipes/land_population.json")
result = mloda.run_all(recipe.features, compute_frameworks=["PyArrowTable"], links=set(recipe.links))
recipe.compliance.sources[0].attribution  # what to print next to the result
```

## Demo

An interactive [marimo](https://marimo.io) notebook walks through dataset discovery, all three example datasets, a Destatis table, a recipe joining two sources (population per eligible voter by Land), and a Kreis series re-based across a merger. The notebook lives in the repository (not in the published package), so run it from a source checkout:

```bash
git clone https://github.com/mloda-ai/mloda-plugin-govdata.git
cd mloda-plugin-govdata
uv sync --all-extras
uv run marimo edit demos/govdata_demo.py
```

The notebook hits the live GovData, Bundeswahlleiterin, UBA, and GENESIS-Online endpoints and fetches the BBSR key file; downloads are cached locally after the first run. The Destatis chapters need GENESIS-Online credentials in the environment (`GENESIS_TOKEN`, or `GENESIS_USER` and `GENESIS_PASSWORD`; see [docs/credentials.md](https://github.com/mloda-ai/mloda-plugin-govdata/blob/main/docs/credentials.md)) and skip themselves without them.

## Related Repositories

- **[mloda](https://github.com/mloda-ai/mloda)**: the core library this plugin builds on. You declare which features you need; mloda resolves how to compute them.

- **[mloda-registry](https://github.com/mloda-ai/mloda-registry)**: plugin registry and development guides for the mloda ecosystem.

## Funding

Developed as part of the [Prototype Fund](https://prototypefund.de) (Round 2 / Jahrgang 02), funded by the German Federal Ministry of Research, Technology and Space (BMFTR) and supported by the [Open Knowledge Foundation Deutschland](https://okfn.de). Funding code (Förderkennzeichen): **16IS26S11**. Stage 1 funding period: 6 months from June 2026.

<p>
  <img src="https://raw.githubusercontent.com/mloda-ai/mloda-plugin-govdata/main/logos/bmftr.png" alt="Funded by the Federal Ministry of Research, Technology and Space (BMFTR)" height="110">
  &nbsp;&nbsp;&nbsp;
  <img src="https://raw.githubusercontent.com/mloda-ai/mloda-plugin-govdata/main/logos/prototypefund.png" alt="Supported by the Prototype Fund" height="110">
</p>

