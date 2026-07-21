"""Marimo demo: discover GovData datasets and read the three M1 example datasets.

Run with: marimo edit demos/govdata_demo.py (needs network access; install the
"demo" extra for marimo itself).
"""

import marimo

__generated_with = "0.14.16"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell
def _(mo):
    mo.md(
        """
        # mloda-plugin-govdata demo

        German open government data as mloda features: search GovData via the
        paginated CKAN API, then read the three M1 example datasets (population,
        elections, environment) as typed Arrow tables. Every cell below talks to
        the live endpoints; downloads are cached locally after the first run.

        Part of the Prototype Fund project mloda-plugin-govdata (FKZ 16IS26S11).
        """
    )
    return


@app.cell
def _():
    import pandas as pd

    from mloda.user import Feature, mloda
    from mloda_plugin_govdata.feature_groups.govdata import (
        BundeswahlleiterinReader,
        StuttgartPopulationReader,
        UbaAirReader,
        build_client,
        search_datasets,
        uba_measures_url,
    )

    return (
        BundeswahlleiterinReader,
        Feature,
        StuttgartPopulationReader,
        UbaAirReader,
        build_client,
        mloda,
        pd,
        search_datasets,
        uba_measures_url,
    )


@app.cell
def _(mo):
    mo.md("""## 1. Discover datasets (paginated CKAN `package_search`)""")
    return


@app.cell
def _(mo):
    query = mo.ui.text(value="einwohner stuttgart altersgruppen", label="GovData search", full_width=True)
    query
    return (query,)


@app.cell
def _(build_client, pd, query, search_datasets):
    with build_client() as _client:
        _hits = list(search_datasets(_client, query.value, max_results=10))
    hits = pd.DataFrame({"name": [d.name for d in _hits], "title": [d.title for d in _hits]})
    hits
    return


@app.cell
def _(mo):
    mo.md("""## 2. Population: Stuttgart residents by age group (GovData CSV)""")
    return


@app.cell
def _(Feature, StuttgartPopulationReader, mloda):
    _slug = "einwohner-nach-altersgruppen-und-stadtbezirken"
    _result = mloda.run_all(
        [
            Feature("Stichtag", options={StuttgartPopulationReader.__name__: _slug}),
            Feature("Stadtbezirk", options={StuttgartPopulationReader.__name__: _slug}),
            Feature("Alter in 10 Gruppen", options={StuttgartPopulationReader.__name__: _slug}),
            Feature("Einwohner", options={StuttgartPopulationReader.__name__: _slug}),
        ],
        compute_frameworks=["PyArrowTable"],
    )
    population = _result[0].to_pandas()
    population
    return


@app.cell
def _(mo):
    mo.md("""## 3. Elections: Bundestagswahl 2025 results (`kerg.csv`, merged header)""")
    return


@app.cell
def _(BundeswahlleiterinReader, Feature, mloda):
    _kerg = "https://www.bundeswahlleiterin.de/bundestagswahlen/2025/ergebnisse/opendata/btw25/csv/kerg.csv"
    _result = mloda.run_all(
        [Feature("Gebiet", options={BundeswahlleiterinReader.__name__: _kerg})],
        compute_frameworks=["PyArrowTable"],
    )
    elections = _result[0].to_pandas()
    elections.head(20)
    return


@app.cell
def _(mo):
    mo.md("""## 4. Environment: hourly ozone at one station (UBA Air Data JSON)""")
    return


@app.cell
def _(Feature, UbaAirReader, mloda, uba_measures_url):
    _url = uba_measures_url(station=143, component=3, scope=2, date_from="2025-01-01", date_to="2025-01-01")
    _result = mloda.run_all(
        [
            Feature("date_start", options={UbaAirReader.__name__: _url}),
            Feature("value", options={UbaAirReader.__name__: _url}),
        ],
        compute_frameworks=["PyArrowTable"],
    )
    environment = _result[0].to_pandas()
    environment
    return


if __name__ == "__main__":
    app.run()
