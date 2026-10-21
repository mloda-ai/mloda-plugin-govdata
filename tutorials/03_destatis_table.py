"""Tutorial 3: read a table from Destatis, choose its years and categories, read the signs in its values.

Run with: uv run marimo edit tutorials/03_destatis_table.py (needs network access and a free GENESIS-Online account).
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
    # Tutorial 3: a table from Destatis

    **Goal:** read a table from Destatis, Germany's Federal Statistical Office, choose its years and
    categories, and read the signs it puts in place of numbers.

    **Time:** about 15 minutes, plus registering for a free account (same day). **You need:** basic Python,
    a network connection and a GENESIS-Online account.

    **Setup:** clone the repository and run `uv sync --all-extras` (see the README), get a token (below), then
    `uv run marimo edit tutorials/03_destatis_table.py`.

    Destatis publishes its tables in *GENESIS-Online*, its database. Every table has a code. Table
    `12411-0010` counts the population of each *Land* (federal state; plural *Länder*) on 31 December of
    each year. The day a count is taken on is its *Stichtag* (reference date).
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    ## Get a token

    Unlike tutorials 1 and 2, GENESIS-Online needs an account.

    1. Register for free at https://genesis.destatis.de/datenbank/online/.
    2. Log in. The web interface shows your token under *Webservice-Schnittstelle (API)* (web service
       interface). Making a new token turns the old one off.
    3. In the repository folder, create a file named `.env` with one line: `GENESIS_TOKEN=` followed by
       your token. git ignores this file, so the token stays out of the repository.
    4. Start marimo as in the setup line. It reads `.env` when it starts.

    A user name and password work too (`GENESIS_USER` and `GENESIS_PASSWORD`); see
    [credentials](https://github.com/mloda-ai/mloda-plugin-govdata/blob/main/docs/credentials.md).
    """)
    return


@app.cell
def _():
    import altair as alt

    from mloda.user import Feature, mloda
    from mloda_plugin_govdata.feature_groups.destatis import (
        GENESIS_ONLINE,
        DestatisCredentials,
        DestatisLocator,
        DestatisReader,
        MissingCredentialsError,
        ParameterCache,
    )

    return (
        DestatisCredentials,
        DestatisLocator,
        DestatisReader,
        Feature,
        GENESIS_ONLINE,
        MissingCredentialsError,
        ParameterCache,
        alt,
        mloda,
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
    mo.stop(
        _why is not None,
        mo.md(f"**Stopped.** {_why} Follow *Get a token* above, then start marimo again."),
    )
    TABLE = "12411-0010"
    TABLE_BY_SEX = "12411-0011"  # the same count, split by sex (Step 4)
    return TABLE, TABLE_BY_SEX


@app.cell
def _(mo):
    mo.md("""
    ## Step 1: see the columns

    `DestatisReader` reads GENESIS tables. `peek` asks GENESIS for the table and lists the columns you can
    ask for. If it fails with an authentication or backend error, copy your token again.
    """)
    return


@app.cell
def _(DestatisReader, TABLE):
    DestatisReader.peek(TABLE)
    return


@app.cell
def _(mo):
    mo.md("""
    Every GENESIS table has the same kinds of columns:

    - `statistics_...`: which statistic the table belongs to.
    - `time`: the year, a whole number. `time_label` says what kind of time it is: here *Stichtag*, so the
      value is the count on 31 December of that year.
    - `1_variable_...`: the table's first variable, here the Land. `..._attribute_code` holds the Land's
      official two-digit key, `..._attribute_label` its name. A table with more variables has `2_...`, `3_...`.
    - `value`: the number. `value_unit` and `value_variable_...` say what it measures.
    - `value_marker`: empty when the cell held a number. Otherwise the sign GENESIS wrote instead.
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    ## Step 2: read it

    Ask for the columns as features, as in tutorial 1. The option `DestatisReader: TABLE` picks the reader
    and the table. GENESIS sends the rows in no fixed order, so sort them.
    """)
    return


@app.cell
def _(DestatisReader, Feature, TABLE, mloda):
    _columns = [
        "time",
        "time_label",
        "1_variable_attribute_code",
        "1_variable_attribute_label",
        "value",
        "value_marker",
    ]
    _result = mloda.run_all(
        [Feature(_name, options={DestatisReader: TABLE}) for _name in _columns],
        compute_frameworks=["PyArrowTable"],
        column_ordering="request_order",
    )
    population = _result[0].to_pandas().sort_values(["1_variable_attribute_code", "time"], ignore_index=True)
    population
    return (population,)


@app.cell
def _(mo, population):
    mo.md(f"""
    One row per Land and year. You did not say which years, so GENESIS chose: {population["time"].min()} to
    {population["time"].max()}.
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    ## Step 3: choose the years

    A `DestatisLocator` names the table plus what to select from it. `startyear` and `endyear` pick the
    years; leave one out and the range stays open on that side. Other fields pick regions or categories, see
    [Destatis options](https://github.com/mloda-ai/mloda-plugin-govdata/blob/main/docs/destatis-options.md).
    """)
    return


@app.cell
def _(DestatisLocator, DestatisReader, Feature, TABLE, mloda):
    since_1980 = DestatisLocator(TABLE, startyear=1980)
    _columns = ["time", "1_variable_attribute_code", "1_variable_attribute_label", "value", "value_marker"]
    _result = mloda.run_all(
        [Feature(_name, options={DestatisReader: since_1980}) for _name in _columns],
        compute_frameworks=["PyArrowTable"],
        column_ordering="request_order",
    )
    history = _result[0].to_pandas().sort_values(["1_variable_attribute_code", "time"], ignore_index=True)
    history
    return history, since_1980


@app.cell
def _(history, mo):
    mo.md(f"""
    {len(history)} rows: 16 Länder, {history["time"].min()} to {history["time"].max()}.
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    ## Step 4: choose a category

    Table `12411-0010` has no categories besides the Land. Its sibling table `12411-0011` holds the same
    count, split by sex (*Geschlecht*). A category is a *classifying variable* in GENESIS; this one has the
    code `GES`, and its values have codes too: `GESM` (male) and `GESW` (female). The codes are listed on the
    [table's page](https://genesis.destatis.de/datenbank/online/statistic/12411/table/12411-0011).

    `classifyingvariable1` names the category, `classifyingkey1` the values to keep. Here: women only.
    """)
    return


@app.cell
def _(DestatisLocator, DestatisReader, Feature, TABLE_BY_SEX, mloda):
    women = DestatisLocator(TABLE_BY_SEX, classifyingvariable1="GES", classifyingkey1=["GESW"])
    _columns = [
        "time",
        "1_variable_attribute_label",
        "2_variable_attribute_code",
        "2_variable_attribute_label",
        "value",
    ]
    _result = mloda.run_all(
        [Feature(_name, options={DestatisReader: women}) for _name in _columns],
        compute_frameworks=["PyArrowTable"],
        column_ordering="request_order",
    )
    by_sex = _result[0].to_pandas().sort_values(["1_variable_attribute_label", "value"], ignore_index=True)
    by_sex
    return by_sex, women


@app.cell
def _(by_sex, mo):
    mo.md(f"""
    The sex is the second variable, so its columns start with `2_`. You asked for women, yet there are
    {len(by_sex)} rows, two per Land: GENESIS adds the total, *Insgesamt*, too. Its code is missing (pandas
    shows `NaN`). Adding up the `value` column would add the whole population on top of the women. Keep the
    rows whose code you asked for:
    `by_sex[by_sex["2_variable_attribute_code"] == "GESW"]`.
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    ## Pitfall: a dash that means "did not exist"

    Here is Brandenburg, from Step 3, around 1990:
    """)
    return


@app.cell
def _(history):
    _brandenburg = history[history["1_variable_attribute_label"] == "Brandenburg"]
    _brandenburg[_brandenburg["time"].between(1987, 1992)]
    return


@app.cell
def _(mo):
    mo.md("""
    Until 1989 the value is 0 and `value_marker` is `-`. In GENESIS, `-` means "nothing there", so the
    plugin reads it as 0 and keeps the sign. Here it means the Land did not exist yet: Brandenburg and the
    other eastern Länder joined the count in 1990, after German reunification. Ask which Land was smallest
    in 1989:
    """)
    return


@app.cell
def _(history, mo):
    _year_1989 = history[history["time"] == 1989]
    _with_dashes = _year_1989.nsmallest(1, "value").iloc[0]
    _without_dashes = _year_1989[_year_1989["value_marker"] != "-"].nsmallest(1, "value").iloc[0]
    mo.md(f"""
    - All rows: {_with_dashes["1_variable_attribute_label"]}, {_with_dashes["value"]:,.0f} people.
    - Without the `-` rows: {_without_dashes["1_variable_attribute_label"]}, {_without_dashes["value"]:,.0f} people.
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    The table's page has a note that explains this, but the note does not come with the data. So look at
    `value_marker` before you compare or add up. The other signs (such as `.` for unknown or secret) are read
    as missing values; `value_marker` keeps them too.
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    ## Try it: pick a Land

    The chart shows the Land's population on 31 December of each year, without the `-` rows. It starts with
    Berlin: until 1989 it counts West Berlin only, so the line jumps in 1990. Every Land drops from 2010 to
    2011: from 2011 the counts rest on a new census, which corrected them. From 2022 a newer census is the
    base, so the step from 2021 to 2022 mixes a correction with real change.
    """)
    return


@app.cell
def _(history, mo):
    _names = sorted(history["1_variable_attribute_label"].unique())
    land = mo.ui.dropdown(options=_names, value="Berlin" if "Berlin" in _names else _names[0], label="Land")
    land
    return (land,)


@app.cell
def _(alt, history, land):
    _rows = history[(history["1_variable_attribute_label"] == land.value) & (history["value_marker"] != "-")]
    alt.Chart(_rows, title=f"Population of {land.value} on 31 December").mark_line(point=True).encode(
        x=alt.X("time:Q", title="Year", axis=alt.Axis(format="d")),
        y=alt.Y("value:Q", title="People"),
        tooltip=["time", "value"],
    )
    return


@app.cell
def _(mo):
    mo.md("""
    ## Where the data came from

    Every published number needs its source. Both tables come from Destatis under one license; the copy on
    your disk records when you downloaded each selection.
    """)
    return


@app.cell
def _(
    DestatisLocator,
    DestatisReader,
    GENESIS_ONLINE,
    ParameterCache,
    TABLE,
    TABLE_BY_SEX,
    mo,
    since_1980,
    women,
):
    _cache = ParameterCache(DestatisReader.cache_dir)

    def _retrieved(selection):
        # The copy each step read; a missing one means the cache was cleared since.
        _hit = _cache.lookup(GENESIS_ONLINE, "data/tablefile", selection.tablefile_fields())
        return f"{_hit.retrieved_at:%Y-%m-%d}" if _hit else "not in the local cache any more"

    _page = "https://genesis.destatis.de/datenbank/online/statistic/12411/table/"
    mo.md(f"""
    - **Source:** Statistisches Bundesamt (Destatis), GENESIS-Online
    - **License:** `{DestatisReader.LICENSE}`, the id the reader declares for Destatis data
    - **Table {TABLE}:** {_page}{TABLE}, retrieved {_retrieved(DestatisLocator(TABLE))} (Steps 1 and 2) and
      {_retrieved(since_1980)} (Step 3)
    - **Table {TABLE_BY_SEX}:** {_page}{TABLE_BY_SEX}, retrieved {_retrieved(women)} (Step 4)
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    The license, [Data License Germany, attribution, version 2.0](https://www.govdata.de/dl-de/by-2-0),
    lets you reuse the data if you name the source, link the license and say what you changed. The plugin
    changed two things for every table: each reference date became its year, and each `-` became 0 (the sign
    stays in `value_marker`). Here you also kept the years from 1980 of table 12411-0010 and left out its
    `-` rows in the chart.

    ## Next

    The next tutorial puts districts (*Kreise*) on today's borders, with the same account.
    [Destatis options](https://github.com/mloda-ai/mloda-plugin-govdata/blob/main/docs/destatis-options.md)
    lists everything a `DestatisLocator` can select and every output column.
    [Credentials](https://github.com/mloda-ai/mloda-plugin-govdata/blob/main/docs/credentials.md) covers
    the account, the token and the second GENESIS database, Regionalstatistik.
    """)
    return


if __name__ == "__main__":
    app.run()
