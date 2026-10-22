"""Tutorial 4: put a district's population series on today's borders, then label it with EU region codes.

Run with: uv run marimo edit tutorials/04_todays_borders.py (needs network access and a free GENESIS-Online account).
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
    # Tutorial 4: districts on today's borders

    **Goal:** put a district's population series on today's borders, then label it with EU region codes.

    **Time:** about 15 minutes. The first run downloads about 20 MB of reference files. **You need:** basic
    Python, a network connection and the GENESIS-Online token from tutorial 3.

    **Setup:** clone the repository and run `uv sync --all-extras` (see the README), put your token in
    `.env` as in tutorial 3, then `uv run marimo edit tutorials/04_todays_borders.py`.

    Germany is split into about 400 districts, *Kreise* (singular *Kreis*). Their borders change: on
    1 November 2016 the districts of Göttingen and Osterode am Harz, in the *Land* (federal state) of
    Lower Saxony, merged into one new district, also named Göttingen. A population series per district then
    breaks in two. This tutorial joins it back together.
    """)
    return


@app.cell
def _():
    import json

    import altair as alt
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
    from mloda_plugin_govdata.feature_groups.govdata import DownloadCache
    from mloda_plugin_govdata.feature_groups.harmonization import AgsToNutsFeature, KreisRebaseFeature

    return (
        AgsToNutsFeature,
        DestatisCredentials,
        DestatisLocator,
        DestatisReader,
        DownloadCache,
        Feature,
        GENESIS_ONLINE,
        KreisRebaseFeature,
        MissingCredentialsError,
        ParameterCache,
        alt,
        json,
        mloda,
        pd,
    )


@app.cell
def _(DestatisCredentials, DestatisLocator, GENESIS_ONLINE, MissingCredentialsError, mo):
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
        mo.md(f"**Stopped.** {_why} See *Get a token* in tutorial 3, then start marimo again."),
    )
    TABLE = "12411-0015"
    goettingen = DestatisLocator(
        TABLE, regionalvariable="KREISE", regionalkey=["03152", "03156", "03159"], startyear=2011
    )
    return TABLE, goettingen


@app.cell
def _(mo):
    mo.md("""
    ## Step 1: read the three districts

    Destatis table `12411-0015` counts the population of every district on 31 December of each year. Each
    district has an official five-digit key, the first digits of its *AGS* (the official region key):
    `03152` (Göttingen before the merger), `03156` (Osterode am Harz) and `03159` (the new Göttingen). `regionalvariable="KREISE"` and
    `regionalkey` pick these three. The years start in 2011 and run to the latest one GENESIS has.
    """)
    return


@app.cell
def _(DestatisReader, Feature, goettingen, mloda):
    _columns = ["time", "1_variable_attribute_code", "1_variable_attribute_label", "value", "value_marker"]
    _result = mloda.run_all(
        [Feature(_name, options={DestatisReader: goettingen}) for _name in _columns],
        compute_frameworks=["PyArrowTable"],
        column_ordering="request_order",
    )
    raw = _result[0].to_pandas()
    raw.pivot(index="time", columns="1_variable_attribute_label", values="value")  # one column per district
    return (raw,)


@app.cell
def _(mo, raw):
    _merged = raw[(raw["1_variable_attribute_code"] == "03159") & (raw["value_marker"] != "-")]
    _first = _merged["time"].min()
    _jump = _merged[_merged["time"] == _first]["value"].iloc[0]
    mo.md(f"""
    Three columns. The two old districts have numbers until {_first - 1}, the new one from {_first}. Every
    other cell is a 0 with the sign `-` in `value_marker`: the district did not exist on that 31 December
    (tutorial 3 met the same sign). Drawn per district, the new Göttingen would seem to grow from 0 to
    {_jump:,.0f} people in one year.
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    ## Step 2: put every year on today's borders

    The *BBSR*, a federal research office for regional planning, publishes conversion keys between the
    borders of consecutive years: which share of each old district's population went to which new
    district. Each pair of years is one sheet of its key file. Sheet 2015-2016 converts the borders of 31
    December 2015 into those of 31 December 2016. These districts kept their borders from 2011 to 2015, so
    the same sheet serves those years too; the plugin checks this and raises an error if a district changed
    earlier.

    `KreisRebaseFeature.fetch_reference()` downloads the key file on the first run and reads it from disk
    afterwards. It checks the file against a fixed fingerprint, so a changed file raises an error instead
    of silently changing your numbers.

    Then ask for `value__rebased`: the feature `value`, re-based. You do not ask for `value` itself; the
    re-basing asks the reader for it. The result has several columns, one per part, named
    `value__rebased~<part>`.
    """)
    return


@app.cell
def _(DestatisReader, Feature, KreisRebaseFeature, goettingen, mloda):
    KreisRebaseFeature.fetch_reference()
    rebase_options = {DestatisReader: goettingen, "rebase_from_year": 2015, "rebase_to_year": 2016}
    _result = mloda.run_all([Feature("value__rebased", options=rebase_options)], compute_frameworks=["PyArrowTable"])
    rebased = _result[0].to_pandas().sort_values("value__rebased~year", ignore_index=True)
    rebased[[f"value__rebased~{_part}" for _part in ("key", "year", "value", "flag", "sources")]]
    return rebase_options, rebased


@app.cell
def _(mo, raw, rebased):
    _flag = rebased["value__rebased~flag"]
    _years = rebased["value__rebased~year"]
    _old = raw[(raw["time"] == 2015) & raw["1_variable_attribute_code"].isin(["03152", "03156"])]
    _old = _old.sort_values("1_variable_attribute_code")["value"]
    _rebased_2015 = rebased[_years == 2015]["value__rebased~value"].iloc[0]
    mo.md(f"""
    One row per year, all on the key `03159`. `~flag` says how each value came about: `rebased` for
    {_years[_flag == "rebased"].min()} to {_years[_flag == "rebased"].max()}, built from the districts in
    `~sources`; `observed` from {_years[_flag == "observed"].min()}, counted by GENESIS for the new district
    itself. Both old districts went in whole, so a re-based year is their sum: for 2015,
    {_old.iloc[0]:,.0f} + {_old.iloc[1]:,.0f} = {_old.sum():,.0f}, and the re-based 2015 value is
    {_rebased_2015:,.0f}.
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    ## Step 3: add EU region codes

    Outside Germany, regions go by *NUTS* codes, Eurostat's classification of the EU's regions. A code
    grows by one character per level: `DE` is Germany, NUTS-1 the Länder, NUTS-2 regions within them,
    NUTS-3 the districts. Eurostat revises the codes every few years, so a code belongs to a version, here
    2024.

    `AgsToNutsFeature.fetch_reference()` downloads Eurostat's table from municipalities to NUTS codes
    (about 20 MB, once) and a Destatis file of the 2016 border changes, which leads an old key such as
    `03152` to its successor. Then chain the mapping onto the re-based keys. Read
    `value__rebased~key__nuts2024` from left to right: re-base `value`, take the `key` part, map it to NUTS
    2024.
    """)
    return


@app.cell
def _(AgsToNutsFeature, Feature, mloda, rebase_options):
    AgsToNutsFeature.fetch_reference()
    _name = "value__rebased~key__nuts2024"
    _result = mloda.run_all([Feature(_name, options=rebase_options)], compute_frameworks=["PyArrowTable"])
    nuts = _result[0].to_pandas()
    nuts[[f"{_name}~{_part}" for _part in ("key", "nuts1", "nuts2", "nuts3", "version")]].drop_duplicates()
    return (nuts,)


@app.cell
def _(mo, nuts):
    _codes = nuts.iloc[0]
    _prefix = "value__rebased~key__nuts2024~"
    mo.md(f"""
    {len(nuts)} rows, one per year, all with the same codes, so the table shows one. `{_codes[_prefix + "nuts1"]}`
    is Lower Saxony, `{_codes[_prefix + "nuts2"]}` the region of Braunschweig (named after a former
    administrative region) and `{_codes[_prefix + "nuts3"]}` the district of Göttingen. With these codes, the series can be compared with regions in other EU countries.
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    ## Pitfall: new borders, not new counting

    Re-basing fixes the borders. It cannot fix a change in how people were counted. About every ten years
    a census (*Zensus*) counts the population afresh, and the yearly numbers after it start from the new
    count. The `~provenance` column records which census changes fall inside your years, as
    `census_breaks`. Nothing in `~value` marks them.
    """)
    return


@app.cell
def _(json, mo, rebased):
    _breaks = json.loads(rebased["value__rebased~provenance"].iloc[0])["census_breaks"]
    _value = rebased.set_index("value__rebased~year")["value__rebased~value"]
    _lines = [
        f"- {_year}: {_value[_year - 1]:,.0f} people in {_year - 1}, {_value[_year]:,.0f} in {_year}. Part of "
        "this step comes from the new census, not from people moving."
        for _year in _breaks
        if _year - 1 in _value.index
    ]
    mo.md(f"""
    `census_breaks`: {_breaks}

    {chr(10).join(_lines) or "No census change inside these years."}

    Compare years on both sides of a break with care, and say so when you publish such a comparison.
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    ## Try it: another merger

    On 1 July 2021 the town of Eisenach (`16056`), until then a district of its own (*kreisfreie Stadt*),
    joined the Wartburgkreis (`16063`) in the Land of Thuringia. This time the bigger district kept its key,
    so its raw line jumps instead of starting from zero. Pick a merger; the chart shows the raw districts
    (without the `-` rows) and the re-based series.
    """)
    return


@app.cell
def _(DestatisLocator, TABLE, goettingen, mo):
    # Each choice: the districts to read and the first year of its key sheet.
    _eisenach = DestatisLocator(TABLE, regionalvariable="KREISE", regionalkey=["16056", "16063"], startyear=2019)
    merger = mo.ui.dropdown(
        options={
            "Göttingen and Osterode am Harz (2016)": (goettingen, 2015),
            "Eisenach into the Wartburgkreis (2021)": (_eisenach, 2020),
        },
        value="Göttingen and Osterode am Harz (2016)",
        label="Merger",
    )
    merger
    return (merger,)


@app.cell
def _(DestatisReader, Feature, alt, merger, mloda, pd, rebased):
    _after_step_2 = rebased  # Step 2 fetched the key file this cell needs
    _locator, _from_year = merger.value
    _options = {DestatisReader: _locator}
    _columns = ["time", "1_variable_attribute_label", "value", "value_marker"]
    _raw = mloda.run_all(
        [Feature(_name, options=_options) for _name in _columns],
        compute_frameworks=["PyArrowTable"],
        column_ordering="request_order",
    )[0].to_pandas()
    _years = {"rebase_from_year": _from_year, "rebase_to_year": _from_year + 1}
    _rebased = mloda.run_all(
        [Feature("value__rebased", options={**_options, **_years})], compute_frameworks=["PyArrowTable"]
    )[0].to_pandas()
    # Formatting only: one long table, one line per series.
    _lines = pd.concat(
        [
            _raw[_raw["value_marker"] != "-"].rename(columns={"1_variable_attribute_label": "series"}),
            pd.DataFrame(
                {
                    "time": _rebased["value__rebased~year"],
                    "value": _rebased["value__rebased~value"],
                    "series": "re-based onto today's borders",
                }
            ),
        ]
    )
    alt.Chart(_lines, title="Population on 31 December").mark_line(point=True).encode(
        x=alt.X("time:Q", title="Year", axis=alt.Axis(format="d")),
        y=alt.Y("value:Q", title="People"),
        color=alt.Color("series:N", title=None, legend=alt.Legend(orient="bottom", columns=1)),
        tooltip=["series", "time", "value"],
    )
    return


@app.cell
def _(mo):
    mo.md("""
    ## Where the data came from

    Every published number needs its sources. Steps 1 to 3 read four files; the copies on your disk record
    when you downloaded each one.
    """)
    return


@app.cell
def _(
    AgsToNutsFeature,
    DestatisReader,
    DownloadCache,
    GENESIS_ONLINE,
    KreisRebaseFeature,
    ParameterCache,
    TABLE,
    goettingen,
    json,
    mo,
    nuts,
    rebased,
):
    _hit = ParameterCache(DestatisReader.cache_dir).lookup(
        GENESIS_ONLINE, "data/tablefile", goettingen.tablefile_fields()
    )
    _keys = json.loads(rebased["value__rebased~provenance"].iloc[0])  # the key file Step 2 used
    _version = nuts["value__rebased~key__nuts2024~version"].iloc[0]
    _crosswalk = AgsToNutsFeature.load_crosswalk()  # the table Step 3 used; reading it takes a few seconds
    with DownloadCache(KreisRebaseFeature.cache_dir) as _cache:
        _keys_retrieved = _cache.get_or_download(_keys["url"], revalidate=False).retrieved_at
    with DownloadCache(AgsToNutsFeature.cache_dir) as _cache:
        _crosswalk_retrieved = _cache.get_or_download(_crosswalk.url, revalidate=False).retrieved_at
    _table_retrieved = f"{_hit.retrieved_at:%Y-%m-%d}" if _hit else "not in the local cache any more"
    mo.md(f"""
    - **Population:** Statistisches Bundesamt (Destatis), GENESIS-Online, table {TABLE},
      https://genesis.destatis.de/datenbank/online/statistic/12411/table/{TABLE}, retrieved {_table_retrieved}.
      License `{DestatisReader.LICENSE}`.
    - **Conversion keys:** {_keys["source"]}, sheet {_keys["sheet"]}, {_keys["url"]}, retrieved
      {_keys_retrieved:%Y-%m-%d}. Attribution: "Laufende Raumbeobachtung des BBSR". License `DL-DE-BY-2.0`.
    - **NUTS {_version} codes:** {_crosswalk.source}, {_crosswalk.url}, retrieved
      {_crosswalk_retrieved:%Y-%m-%d}. Attribution: "Source: Eurostat." License `CC-BY-4.0`.
    - **Border changes of 2016:** Destatis municipality register (*Gemeindeverzeichnis*), change file 2016,
      https://www.destatis.de/DE/Themen/Laender-Regionen/Regionales/Gemeindeverzeichnis/_inhalt.html,
      fetched together with the NUTS codes. Attribution: "(c) Statistisches Bundesamt (Destatis)". License
      `DL-DE-BY-2.0`.
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    Both licenses ([Data License Germany, attribution, version 2.0](https://www.govdata.de/dl-de/by-2-0)
    and [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)) let you reuse the data if you name the
    source, link the license and say what you changed. Here: each reference date became its year and each
    `-` became 0 (the plugin does this for every Destatis table), the years before 2016 were summed onto the
    2016 borders with the BBSR population shares, and the district keys were mapped to NUTS 2024 codes.

    ## Next

    The next tutorial runs a recipe: a file that holds the features, options and sources of a result, so
    someone else can run it again. [Harmonization](https://github.com/mloda-ai/mloda-plugin-govdata/blob/main/docs/harmonization.md)
    lists every option of `value__rebased` and the NUTS mapping, and every part they return.
    """)
    return


if __name__ == "__main__":
    app.run()
