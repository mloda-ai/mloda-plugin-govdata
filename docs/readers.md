# Readers

Every reader turns one source into a typed PyArrow table. The option key is the reader class or its class-name string; the option value says what to read.

## GovData

The option value is a GovData dataset slug or a direct distribution URL. The license is read from the CKAN distribution metadata.

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

For any other GovData CSV dataset, `GovDataReader` works out of the box and reads every column as a string; subclass it and set `schema` for typed columns. Set `BaseGovDataReader.cache_dir` to control where downloads are cached.

### Find a dataset

Search GovData with the paginated CKAN `package_search` API:

```python
from mloda_plugin_govdata.feature_groups.govdata import build_client, search_datasets

with build_client() as client:
    for dataset in search_datasets(client, "einwohner stuttgart", max_results=10):
        print(dataset.name, "|", dataset.title)
```

`search_datasets` walks the result pages lazily (`page_size` per request) and stops at `max_results` or the end of the result set.

### List the columns

`peek` lists what you can request as features:

```python
StuttgartPopulationReader.peek(slug)  # {"Stichtag": "date32[day]", "Stadtbezirk": "string", ...}
```

It works on every reader (`BundeswahlleiterinReader.peek(kerg)`, `UbaAirReader.peek(uba_measures_url(...))`, `DestatisReader.peek(...)`) and downloads through the cache, so the actual feature request reuses the file. `peek` takes a raw URL, bypassing the `READER_OPTIONS` validation. `describe_columns` returns the same columns with mloda `DataType`s, the form lineage extenders read. A typo in a feature name fails with the available columns and a close-match suggestion.

## Elections (Bundeswahlleiterin)

Reads a direct CSV URL whose file has a multi-row merged header (`kerg.csv`):

```python
from mloda_plugin_govdata.feature_groups.govdata import BundeswahlleiterinReader

kerg = "https://www.bundeswahlleiterin.de/bundestagswahlen/2025/ergebnisse/opendata/btw25/csv/kerg.csv"
result = mloda.run_all(
    [Feature("Gebiet", options={BundeswahlleiterinReader: kerg})],
    compute_frameworks=["PyArrowTable"],
)
```

## Air quality (UBA)

Fetches the Umweltbundesamt Air Data v4 `measures` endpoint and flattens it to one typed row per station and timestamp. Query parameters are per-feature options (here: hourly ozone at station 143); a bad value is rejected before any network call:

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

## Destatis (GENESIS)

Reads a GENESIS table (GENESIS-Online or a Regionalstatistik installation) by table code and parses the ffcsv reply. Needs a free registration, see [credentials.md](credentials.md).

```python
from mloda_plugin_govdata.feature_groups.destatis import DestatisReader

result = mloda.run_all(
    [Feature("value", options={DestatisReader: "12411-0010"})],  # population by Land
    compute_frameworks=["PyArrowTable"],
)
```

The option value is a bare table code (the server's default years), a `DestatisLocator`, or its dict form; the latter two narrow the selection by region, years, and classifying variables, and the dict form round-trips through a recipe file. The full parameter table is in [destatis-options.md](destatis-options.md).

Adding a source of your own: [adding-a-reader.md](adding-a-reader.md).
