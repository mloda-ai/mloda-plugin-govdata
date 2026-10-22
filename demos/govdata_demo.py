"""Marimo demo: discover GovData datasets, read three example datasets and a Destatis table, run two recipes.

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
        paginated CKAN API, read three example datasets (population,
        elections, environment) as typed Arrow tables, then read a Destatis
        table, join two sources with a shipped recipe, and re-base a Kreis
        series across a merger. Every cell below talks to the live
        endpoints; downloads are cached locally after the first run.

        Part of the Prototype Fund project mloda-plugin-govdata (FKZ 16IS26S11).
        """
    )
    return


@app.cell
def _():
    import pandas as pd

    from mloda.user import Feature, mloda
    from mloda_plugin_govdata.feature_groups.govdata import (
        OPTION_UBA_COMPONENT,
        OPTION_UBA_DATE_FROM,
        OPTION_UBA_DATE_TO,
        OPTION_UBA_SCOPE,
        OPTION_UBA_STATION,
        BundeswahlleiterinReader,
        StuttgartPopulationReader,
        UbaAirReader,
        build_client,
        search_datasets,
    )

    return (
        BundeswahlleiterinReader,
        Feature,
        OPTION_UBA_COMPONENT,
        OPTION_UBA_DATE_FROM,
        OPTION_UBA_DATE_TO,
        OPTION_UBA_SCOPE,
        OPTION_UBA_STATION,
        StuttgartPopulationReader,
        UbaAirReader,
        build_client,
        mloda,
        pd,
        search_datasets,
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
            Feature("Stichtag", options={StuttgartPopulationReader: _slug}),
            Feature("Stadtbezirk", options={StuttgartPopulationReader: _slug}),
            Feature("Alter in 10 Gruppen", options={StuttgartPopulationReader: _slug}),
            Feature("Einwohner", options={StuttgartPopulationReader: _slug}),
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
        [Feature("Gebiet", options={BundeswahlleiterinReader: _kerg})],
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
def _(
    Feature,
    OPTION_UBA_COMPONENT,
    OPTION_UBA_DATE_FROM,
    OPTION_UBA_DATE_TO,
    OPTION_UBA_SCOPE,
    OPTION_UBA_STATION,
    UbaAirReader,
    mloda,
):
    _uba_options = {
        UbaAirReader: True,
        OPTION_UBA_STATION: 143,
        OPTION_UBA_COMPONENT: 3,
        OPTION_UBA_SCOPE: 2,
        OPTION_UBA_DATE_FROM: "2025-01-01",
        OPTION_UBA_DATE_TO: "2025-01-01",
    }
    _result = mloda.run_all(
        [
            Feature("date_start", options=_uba_options),
            Feature("value", options=_uba_options),
        ],
        compute_frameworks=["PyArrowTable"],
    )
    environment = _result[0].to_pandas()
    environment
    return


@app.cell
def _(mo):
    mo.md(
        """
        ## 5. Destatis: population by Land (GENESIS-Online)

        This chapter and the next two need a GENESIS-Online registration in the environment before
        marimo starts: `GENESIS_TOKEN`, or `GENESIS_USER` and `GENESIS_PASSWORD` (see
        `docs/credentials.md`). Without one they skip themselves.
        """
    )
    return


@app.cell
def _(mo):
    from mloda_plugin_govdata.feature_groups.destatis import (
        GENESIS_ONLINE,
        DestatisCredentials,
        DestatisReader,
        MissingCredentialsError,
    )
    from mloda_plugin_govdata.feature_groups.harmonization import KreisRebaseFeature
    from mloda_plugin_govdata.feature_groups.harmonization.core.land_codes import check_land_names
    from mloda_plugin_govdata.feature_groups.land_population_per_voter import LandPopulationPerVoter
    from mloda_plugin_govdata.recipes import frames_by_column, load_recipe

    # Every Destatis cell takes a name from this cell, so mo.stop skips them all.
    _why = None
    try:
        if DestatisCredentials.from_env(GENESIS_ONLINE) is None:
            _why = "no GENESIS-Online credentials in the environment"
    except MissingCredentialsError as exc:  # one half of the user plus password pair
        _why = str(exc)
    if mo.notebook_dir() is None:
        _why = "the notebook has no file location, so `recipes/` cannot be found"
    mo.stop(_why is not None, mo.md(f"Destatis cells skipped: {_why}"))
    recipes = mo.notebook_dir().parent / "recipes"

    def compliance_note(recipe):
        sources = "\n".join(
            f"- {s.attribution}, {s.license}, retrieved {s.retrieved_at:%Y-%m-%d}; "
            f"changed: {'; '.join(s.modifications)}"
            for s in recipe.compliance.sources
        )
        return mo.md(f"{sources}\n\n{recipe.compliance.notes or ''}")

    return (
        DestatisReader,
        KreisRebaseFeature,
        LandPopulationPerVoter,
        check_land_names,
        compliance_note,
        frames_by_column,
        load_recipe,
        recipes,
    )


@app.cell
def _(DestatisReader, Feature, mloda):
    _table = "12411-0010"  # a bare table code: the server's default years
    _result = mloda.run_all(
        [
            Feature("time", options={DestatisReader: _table}),
            Feature("1_variable_attribute_code", options={DestatisReader: _table}),
            Feature("1_variable_attribute_label", options={DestatisReader: _table}),
            Feature("value", options={DestatisReader: _table}),
        ],
        compute_frameworks=["PyArrowTable"],
    )
    land_population = _result[0].to_pandas()
    land_population
    return


@app.cell
def _(mo):
    mo.md(
        """
        ## 6. Join two sources with a recipe: population per eligible voter by Land (`land_population_per_voter.json`)

        A recipe file under `recipes/` names the features of one run, the joins, and where the data
        came from; `load_recipe` returns what `mloda.run_all` needs plus the compliance block.
        Requesting the recipe's own features returns two frames, one per source.
        `check_land_names` verifies the AGS-2 codes and names on each side.
        `LandPopulationPerVoter` is a consumer FeatureGroup needing a column from each side and
        declares the recipe's link on both inputs, so mloda's join fires for it: no manual merge.
        """
    )
    return


@app.cell
def _(check_land_names, frames_by_column, load_recipe, mloda, recipes):
    land_recipe = load_recipe(recipes / "land_population_per_voter.json")
    _frames = frames_by_column(mloda.run_all(land_recipe.features, compute_frameworks=["PyArrowTable"]))
    population_by_land = _frames["value"].to_pandas()
    _election = _frames["Nr"].to_pandas()
    voters_by_land = _election[_election["gehört zu"] == "99"]  # the Land rows; Bundesgebiet has no parent
    check_land_names(
        zip(population_by_land["1_variable_attribute_code"], population_by_land["1_variable_attribute_label"])
    )
    check_land_names(zip(voters_by_land["Nr"], voters_by_land["Gebiet"]))
    return land_recipe, population_by_land, voters_by_land


@app.cell
def _(mo, population_by_land, voters_by_land):
    mo.hstack([population_by_land, voters_by_land], gap=2)
    return


@app.cell
def _(Feature, LandPopulationPerVoter, mloda):
    _table = mloda.run_all([Feature(LandPopulationPerVoter.NAME)], compute_frameworks=["PyArrowTable"])[0]
    # ~code, ~land, ~population, ~voters, ~value: one labeled row per Land, sorted by AGS-2 code.
    per_voter = _table.rename_columns([name.rpartition("~")[2] for name in _table.schema.names]).to_pandas()
    per_voter  # Bevölkerung je Wahlberechtigte
    return


@app.cell
def _(compliance_note, land_recipe):
    compliance_note(land_recipe)
    return


@app.cell
def _(mo):
    mo.md(
        """
        ## 7. Re-base a Kreis series across the Göttingen merger (`kreis_population_rebased.json`)

        The BBSR key file must be in the download cache before the feature group runs: fetched once,
        checked against its pinned sha256, read offline afterwards.
        """
    )
    return


@app.cell
def _(KreisRebaseFeature, load_recipe, mloda, recipes):
    KreisRebaseFeature.fetch_reference()
    kreis_recipe = load_recipe(recipes / "kreis_population_rebased.json")
    rebased = mloda.run_all(kreis_recipe.features, compute_frameworks=["PyArrowTable"])[0].to_pandas()
    rebased.columns = [name.rpartition("~")[2] for name in rebased.columns]  # strip the feature-name prefix
    rebased[["key", "year", "value", "flag", "sources", "marker", "issues"]]
    return (kreis_recipe,)


@app.cell
def _(compliance_note, kreis_recipe):
    compliance_note(kreis_recipe)
    return


if __name__ == "__main__":
    app.run()
