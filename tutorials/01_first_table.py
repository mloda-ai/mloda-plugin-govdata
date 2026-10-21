"""Tutorial 1: find a GovData dataset, see its columns, read it as a table.

Run with: uv run marimo edit tutorials/01_first_table.py (needs network access, no account).
"""

import marimo

__generated_with = "0.23.16"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell
def _(mo):
    mo.md("""
    # Tutorial 1: your first table

    **Goal:** find a dataset in Germany's open data catalog and read it as a table whose columns have
    types: dates are dates, counts are numbers.

    **Time:** about 15 minutes. **You need:** basic Python and a network connection. No account.

    [mloda](https://github.com/mloda-ai/mloda) works like this: you name the columns you want, and mloda
    finds the code that fetches and prepares them. In mloda, a column you ask for is called a *feature*.
    This plugin adds that code for German open government data.

    [GovData](https://www.govdata.de) is Germany's national catalog of open government data. It lists the
    datasets; the files themselves live with each publisher, here the city of Stuttgart.
    """)
    return


@app.cell
def _():
    import altair as alt
    import pandas as pd

    from mloda.user import Feature, mloda
    from mloda_plugin_govdata.feature_groups.govdata import (
        DownloadCache,
        GovDataLocator,
        StuttgartPopulationReader,
        build_client,
        resolve_distribution,
        search_datasets,
    )

    return (
        DownloadCache,
        Feature,
        GovDataLocator,
        StuttgartPopulationReader,
        alt,
        build_client,
        mloda,
        pd,
        resolve_distribution,
        search_datasets,
    )


@app.cell
def _(mo):
    mo.md("""
    ## Step 1: find a dataset

    The catalog is in German, so we search in German: *Einwohner* means residents, *Altersgruppen* means
    age groups. `search_datasets` asks the catalog and returns each match with its id and title.
    """)
    return


@app.cell
def _(build_client, pd, search_datasets):
    QUERY = "einwohner stuttgart altersgruppen"  # change it and run the cell again

    with build_client() as _client:
        _hits = list(search_datasets(_client, QUERY, max_results=10))
    pd.DataFrame({"id": [_d.name for _d in _hits], "title": [_d.title for _d in _hits]})
    return


@app.cell
def _(mo):
    mo.md("""
    Look for the id `einwohner-nach-altersgruppen-und-stadtbezirken`: residents by age group and city
    district. We copy that id by hand into the next cell, so the rest of the tutorial does not depend on
    the search order.
    """)
    return


@app.cell
def _():
    DATASET_ID = "einwohner-nach-altersgruppen-und-stadtbezirken"
    return (DATASET_ID,)


@app.cell
def _(mo):
    mo.md("""
    ## Step 2: see the columns

    A *reader* turns one kind of file into a table. This plugin ships `StuttgartPopulationReader` for this
    dataset, with a type for every column. (Any other GovData CSV file works with `GovDataReader`, which
    reads every column as text.)

    `peek` lists the columns you can ask for. It downloads the file, so this cell is the slow one; later
    cells reuse the download.
    """)
    return


@app.cell
def _(DATASET_ID, StuttgartPopulationReader):
    StuttgartPopulationReader.peek(DATASET_ID)
    return


@app.cell
def _(mo):
    mo.md("""
    Four columns:

    - **Stichtag**: the reference date the count was taken on. Type `date32[day]`, a calendar date.
    - **Stadtbezirk**: the city district. Type `string`, text.
    - **Alter in 10 Gruppen**: the age group, one of ten. Text.
    - **Einwohner**: the number of residents. Type `int64`, a whole number.

    Typed columns mean dates are dates and counts are numbers, so you can compare and add them right away.
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    ## Step 3: read it

    Ask for each column as a `Feature`. The `options` say which reader to use and which dataset to read.
    `compute_frameworks=["PyArrowTable"]` picks the table format of the result, and
    `column_ordering="request_order"` keeps the columns in the order you asked for. The result is a list
    of tables; here there is one. `to_pandas()` turns it into a pandas DataFrame.
    """)
    return


@app.cell
def _(DATASET_ID, Feature, StuttgartPopulationReader, mloda):
    options = {StuttgartPopulationReader: DATASET_ID}
    result = mloda.run_all(
        [
            Feature("Stichtag", options=options),
            Feature("Stadtbezirk", options=options),
            Feature("Alter in 10 Gruppen", options=options),
            Feature("Einwohner", options=options),
        ],
        compute_frameworks=["PyArrowTable"],
        column_ordering="request_order",
    )
    population = result[0].to_pandas()
    population
    return (population,)


@app.cell
def _(mo):
    mo.md("""
    One row per date, district and age group. The age groups read like "18 bis unter 30 Jahre":
    *bis unter* means "up to but not including", so this group is 18 to 29 years old.
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    ## Pitfall: count each person once

    The city counts its residents several times a year: two to five reference dates per year. Here is
    the district Mitte in 2020, summed over the age groups:
    """)
    return


@app.cell
def _(pd, population):
    _dates = pd.to_datetime(population["Stichtag"])
    _mitte_2020 = population[(population["Stadtbezirk"] == "Mitte") & (_dates.dt.year == 2020)]
    _mitte_2020.groupby("Stichtag")["Einwohner"].sum()
    return


@app.cell
def _(mo):
    mo.md("""
    Each line is the whole district on one date. Adding up 2020 would count the same people four
    times. So keep one date per year: 31 December. The year 2023 has only a March count, so it drops
    out, and the series runs to 2022.
    """)
    return


@app.cell
def _(pd, population):
    _dates = pd.to_datetime(population["Stichtag"])
    year_end = population[(_dates.dt.month == 12) & (_dates.dt.day == 31)].assign(year=_dates.dt.year)
    return (year_end,)


@app.cell
def _(mo):
    mo.md("""
    ## Try it: pick a district

    Choose a district; the chart below shows its residents on 31 December of each year.
    """)
    return


@app.cell
def _(mo, year_end):
    district = mo.ui.dropdown(
        options=sorted(year_end["Stadtbezirk"].unique()), value="Mitte", label="District (Stadtbezirk)"
    )
    district
    return (district,)


@app.cell
def _(alt, district, year_end):
    _per_year = year_end[year_end["Stadtbezirk"] == district.value].groupby("year", as_index=False)["Einwohner"].sum()
    alt.Chart(_per_year, title=f"Residents of {district.value} on 31 December").mark_line(point=True).encode(
        x=alt.X("year:Q", title="Year", axis=alt.Axis(format="d")),
        y=alt.Y("Einwohner:Q", title="Residents"),
        tooltip=["year", "Einwohner"],
    )
    return


@app.cell
def _(mo):
    mo.md("""
    ## Where the data came from

    Every published number needs its source. The catalog entry names the publisher and the license; the
    download cache knows when you fetched the file.
    """)
    return


@app.cell
def _(
    DATASET_ID,
    DownloadCache,
    GovDataLocator,
    StuttgartPopulationReader,
    build_client,
    mo,
    resolve_distribution,
):
    with build_client() as _client:
        _source = resolve_distribution(GovDataLocator(dataset_id=DATASET_ID), _client)
        with DownloadCache(StuttgartPopulationReader.cache_dir, client=_client) as _cache:
            _retrieved = _cache.get_or_download(_source.url).retrieved_at
    _extras = _source.dataset.extras if _source.dataset else {}
    mo.md(f"""
    - **Publisher:** {_extras.get("publisher_name")}
    - **License:** {_source.license}
    - **Dataset page:** {_extras.get("uri")}
    - **File:** {_source.url}
    - **Retrieved:** {_retrieved:%Y-%m-%d}
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    The publisher is the statistics office of the city of Stuttgart (*Landeshauptstadt* means state
    capital). The license, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), lets you reuse the
    data if you name the source, link the license and say whether you changed the data. Filtering to
    31 December counts as a change.

    ## Next

    [Readers](https://github.com/mloda-ai/mloda-plugin-govdata/blob/main/docs/readers.md) lists every
    source this plugin reads, how to search them and how to read any other GovData file.
    """)
    return


if __name__ == "__main__":
    app.run()
