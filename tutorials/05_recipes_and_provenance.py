"""Tutorial 5: run a recipe, join two sources, and read where every number came from.

Run with: uv run marimo edit tutorials/05_recipes_and_provenance.py (needs network access and a GENESIS-Online account).
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
    # Tutorial 5: recipes and provenance

    **Goal:** run a result from a recipe file, join two sources, and read where every number came from.

    **Time:** about 15 minutes. **You need:** basic Python, a network connection, the GENESIS-Online token
    from tutorial 3, and a clone of the repository: recipe files sit in its `recipes/` folder, not in the
    installed package.

    **Setup:** clone the repository and run `uv sync --all-extras` (see the README), put your token in
    `.env` as in tutorial 3, then `uv run marimo edit tutorials/05_recipes_and_provenance.py`.

    A *recipe* is a small file that writes one result down: which columns to read from which sources, how
    to join them, and where the data came from. Anyone with the file can run the same result again. This
    tutorial runs the recipe for the number of people per eligible voter in each *Land* (federal state;
    plural *Länder*): population counts from Destatis on one side, the 2025 election to the *Bundestag*
    (the federal parliament) on the other.
    """)
    return


@app.cell
def _():
    import pandas as pd

    from mloda.user import Feature, mloda
    from mloda_plugin_govdata.feature_groups.destatis import (
        GENESIS_ONLINE,
        DestatisCredentials,
        DestatisLocator,
        DestatisReader,
        MissingCredentialsError,
        ParameterCache,
    )
    from mloda_plugin_govdata.feature_groups.govdata import BundeswahlleiterinReader, DownloadCache
    from mloda_plugin_govdata.feature_groups.harmonization import check_land_names
    from mloda_plugin_govdata.feature_groups.land_population_per_voter import LAND_LOCATOR, LandPopulationPerVoter
    from mloda_plugin_govdata.recipes import load_recipe

    return (
        BundeswahlleiterinReader,
        DestatisCredentials,
        DestatisLocator,
        DestatisReader,
        DownloadCache,
        Feature,
        GENESIS_ONLINE,
        LAND_LOCATOR,
        LandPopulationPerVoter,
        MissingCredentialsError,
        ParameterCache,
        check_land_names,
        load_recipe,
        mloda,
        pd,
    )


@app.cell
def _(DestatisCredentials, GENESIS_ONLINE, MissingCredentialsError, mo):
    # Every later cell takes a name from this cell, so mo.stop holds them all back.
    _why = None
    try:
        if DestatisCredentials.from_env(GENESIS_ONLINE) is None:
            _why = "No token found: `GENESIS_TOKEN` is not set (nor `GENESIS_USER` and `GENESIS_PASSWORD`)."
    except MissingCredentialsError:  # a user name without a password, or the reverse
        _why = "Set both `GENESIS_USER` and `GENESIS_PASSWORD`, or only `GENESIS_TOKEN`."
    except ValueError:  # a character that cannot be part of a token, e.g. a copied quote mark
        _why = "The token contains a character that does not belong in it. Copy it again."
    if _why is not None:
        _why += " See *Get a token* in tutorial 3, then start marimo again."
    elif mo.notebook_dir() is None or not (mo.notebook_dir().parent / "recipes").is_dir():
        _why = "This notebook cannot find the `recipes/` folder. Open it from your clone of the repository."
    mo.stop(_why is not None, mo.md(f"**Stopped.** {_why}"))
    recipes = mo.notebook_dir().parent / "recipes"
    return (recipes,)


@app.cell
def _(mo):
    mo.md("""
    ## Step 1: open the recipe

    `load_recipe` reads a recipe file and returns three things: `features`, the columns to read, ready for
    `mloda.run_all`; `links`, how to join the sources; and `compliance`, where the data came from.

    The first five features are columns of Destatis table `12411-0010` from tutorial 3, for the year 2024.
    The other five are columns of `kerg.csv`, the results file of the *Bundeswahlleiterin* (the federal
    returning officer): `Nr` is an area's number, `Gebiet` its name, `gehört zu` (belongs to) the number of
    the area it is part of, then the eligible voters and the votes for one party. The election took place on
    23 February 2025, so it is paired with the population of 31 December 2024, the last count before it.
    """)
    return


@app.cell
def _(load_recipe, recipes):
    recipe = load_recipe(recipes / "land_population_per_voter.json")
    [str(_feature.name) for _feature in recipe.features]
    return (recipe,)


@app.cell
def _(mo):
    mo.md("""
    ## Step 2: run it

    Hand the recipe's features to `mloda.run_all`, like any list of features. `frame_for` picks a result
    table by a feature it holds: `value` is only on the Destatis side, `Nr` only on the election side. The
    election file also has rows for constituencies and for Germany as a whole; a Land belongs to `99`, the
    number of Germany as a whole, so `gehört zu == "99"` keeps the Länder.
    """)
    return


@app.cell
def _(mloda, recipe):
    _result = mloda.run_all(recipe.features, compute_frameworks=["PyArrowTable"], column_ordering="request_order")
    population = _result.frame_for("value").to_pandas().sort_values("1_variable_attribute_code", ignore_index=True)
    election = _result.frame_for("Nr").to_pandas()
    lands = election[election["gehört zu"] == "99"].sort_values("Nr", ignore_index=True)
    lands
    return election, lands, population


@app.cell
def _(check_land_names, election, lands, mo, population):
    # check_land_names raises an error if a number and its name disagree, a number repeats, or a Land is missing.
    check_land_names(zip(population["1_variable_attribute_code"], population["1_variable_attribute_label"]))
    check_land_names(zip(lands["Nr"], lands["Gebiet"]))
    _constituencies = election["gehört zu"].isin(lands["Nr"]).sum()
    mo.md(f"""
    Two tables, one per source, not one joined table: mloda joins only for a feature that needs columns from
    both sides (Step 3). The population table (not shown) has {len(population)} rows, one per Land. The election table
    has {len(election)}: {_constituencies} constituencies (*Wahlkreise*), {len(lands)} Länder and Germany as
    a whole.

    Both sides number the Länder the same way, with the first two digits of the *AGS* (the official region
    key), from `01` Schleswig-Holstein to `16` Thüringen. `check_land_names` passed on both: each side names
    all 16 Länder, and every number matches its name.
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    ## Step 3: join the two sources

    The recipe's `links` hold the join: Destatis `1_variable_attribute_code` to election `Nr`. mloda uses
    such a link only for a feature that needs columns from both sides. `LandPopulationPerVoter` is one: it
    reads the same table and file as the recipe, declares the same link, joins the two per Land and divides
    the population by the eligible voters. Ask for it by its name. Like `value__rebased` in tutorial 4, the
    result has several parts, named `land_population_per_voter~<part>`.
    """)
    return


@app.cell
def _(Feature, LandPopulationPerVoter, mloda, recipe):
    _after_step_1 = recipe  # waits for the token check and Step 1
    _table = mloda.run_all([Feature(LandPopulationPerVoter.NAME)], compute_frameworks=["PyArrowTable"])[0]
    per_voter = _table.to_pandas()
    per_voter.columns = [_name.rpartition("~")[2] for _name in per_voter.columns]  # keep only the part name
    per_voter[["code", "land", "population", "voters", "value"]]
    return (per_voter,)


@app.cell
def _(mo, per_voter):
    _ranked = per_voter.sort_values("value")
    _lowest, _highest = _ranked.iloc[0], _ranked.iloc[-1]
    _above_one = (
        " Every value is above 1: children and people without German citizenship count in the population but"
        " cannot vote for the Bundestag."
        if (per_voter["value"] > 1).all()
        else ""
    )
    mo.md(f"""
    One row per Land. `value` is the population divided by the eligible voters: {_highest["land"]} has the
    most people per voter ({_highest["value"]:.2f}), {_lowest["land"]} the fewest ({_lowest["value"]:.2f}).{_above_one}
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    ## Pitfall: empty is not zero

    The recipe also reads the final (*Endgültig*) *Zweitstimmen* (second votes, the vote for a party's list)
    of the CSU. The CSU and the CDU are sister parties that never stand against each other: the CSU stands
    only in Bayern (Bavaria), the CDU everywhere else. So the CSU cell is empty in every other Land. Empty
    means "not on the ballot", not "no votes".
    """)
    return


@app.cell
def _(lands, mo):
    _csu = lands.set_index("Gebiet")["Christlich-Soziale Union in Bayern e.V. Zweitstimmen Endgültig"]
    _counted = ", ".join(f"{_land} ({_votes:,.0f} votes)" for _land, _votes in _csu.dropna().items())
    _stood = "the Land" if _csu.count() == 1 else f"the {_csu.count()} Länder"
    mo.md(f"""
    The CSU column has a number only for {_counted} and is empty for the other {_csu.isna().sum()} Länder.
    pandas shows an empty cell as `NaN` (not a number), and `.mean()` skips it: the mean of the column is
    {_csu.mean():,.0f}, taken over {_stood} where the CSU stood. Fill the empty cells with 0 first
    (`.fillna(0).mean()`) and the mean drops to {_csu.fillna(0).mean():,.0f}: every Land where nobody could
    vote for the CSU now counts as zero votes.
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    ## Try it: read another recipe

    The repository ships more recipes. Pick one to see its sources as its compliance block writes them down.
    Nothing is downloaded: the file alone says where its data comes from and under which license.
    """)
    return


@app.cell
def _(mo, recipes):
    _names = sorted(_path.name for _path in recipes.glob("*.json"))
    picked = mo.ui.dropdown(options=_names, value=_names[0], label="Recipe")
    picked
    return (picked,)


@app.cell
def _(load_recipe, pd, picked, recipes):
    _sources = load_recipe(recipes / picked.value).compliance.sources
    pd.DataFrame(
        {
            "source": [_source.attribution for _source in _sources],
            "license": [_source.license for _source in _sources],
            "downloaded by the recipe's author": [f"{_source.retrieved_at:%Y-%m-%d}" for _source in _sources],
            "address": [_source.dataset_uri for _source in _sources],
        }
    )
    return


@app.cell
def _(mo):
    mo.md("""
    ## Where the data came from

    The compliance block of the recipe from Step 1 names each source with its license and attribution, the
    day the recipe's author downloaded it, and a *checksum* (sha256): a fingerprint of the downloaded file.
    The copies on your disk carry their own download date and checksum. The same checksum means the same
    file.
    """)
    return


@app.cell
def _(
    BundeswahlleiterinReader,
    DestatisLocator,
    DestatisReader,
    DownloadCache,
    GENESIS_ONLINE,
    LAND_LOCATOR,
    ParameterCache,
    mo,
    per_voter,
    recipe,
):
    _after_step_3 = per_voter  # Steps 2 and 3 put both copies on disk
    _destatis, _election = recipe.compliance.sources
    # LAND_LOCATOR names the same table and year as the recipe.
    _destatis_copy = ParameterCache(DestatisReader.cache_dir).lookup(
        GENESIS_ONLINE, "data/tablefile", DestatisLocator(**LAND_LOCATOR).tablefile_fields()
    )
    with DownloadCache(BundeswahlleiterinReader.cache_dir) as _cache:
        _election_copy = _cache.get_or_download(_election.dataset_uri, revalidate=False)
    _destatis_yours = (
        f"you on {_destatis_copy.retrieved_at:%Y-%m-%d}" if _destatis_copy else "your copy is no longer in the cache"
    )
    _same = (
        "the same file"
        if _election_copy.sha256 == _election.sha256
        else "a different file: it changed between the two downloads"
    )
    mo.md(f"""
    - **{_destatis.attribution}**, license `{_destatis.license}`, {_destatis.dataset_uri}. The recipe's author
      downloaded it on {_destatis.retrieved_at:%Y-%m-%d}, {_destatis_yours}. Its checksum cannot be compared:
      GENESIS packs every answer into a new zip archive whose inner file name carries the time of the
      request, so the checksum changes on every download, even when no number does. Changes recorded in the
      recipe: {"; ".join(_destatis.modifications)}.
    - **{_election.attribution}**, license `{_election.license}`, {_election.dataset_uri}. The recipe's author
      downloaded it on {_election.retrieved_at:%Y-%m-%d}, you on {_election_copy.retrieved_at:%Y-%m-%d}. The
      checksums say: {_same}. Changes recorded in the recipe: {"; ".join(_election.modifications)}.
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    Both sources publish under the [Data License Germany, attribution, version 2.0](https://www.govdata.de/dl-de/by-2-0)
    (`DL-DE-BY-2.0`): you may reuse the data if you name the source, link the license and the data, and say
    what you changed. The readers' changes are recorded above. In plain words: *ffcsv* is the CSV format
    GENESIS delivers, its reference date (*Stichtag*) became a year, a `-` sign became 0 with the sign kept
    in `value_marker`, and the three header rows of the election file became one column name each. This
    tutorial changed more: it kept only the 16 Land rows of the election file and divided the population by
    the eligible voters.

    ## Next

    The next tutorial reads a new election with configuration only, no new code.
    [Recipes](https://github.com/mloda-ai/mloda-plugin-govdata/blob/main/docs/recipes.md) describes the file
    format, every shipped recipe and how each one is checked against its sources.
    """)
    return


if __name__ == "__main__":
    app.run()
