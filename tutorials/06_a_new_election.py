"""Tutorial 6: read four Berlin elections with one set of reader options; the next election is one more URL.

Run with: uv run marimo edit tutorials/06_a_new_election.py (needs network access, no account).
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
    # Tutorial 6: a new election

    **Goal:** read four Berlin elections with one set of reader options, and see that the next election
    takes one more URL.

    **Time:** about 15 minutes. **You need:** basic Python and a network connection. No account.

    **Setup:** clone the repository and run `uv sync --all-extras` (see the README), then
    `uv run marimo edit tutorials/06_a_new_election.py`.

    In [tutorial 2](https://github.com/mloda-ai/mloda-plugin-govdata/blob/main/tutorials/02_elections_and_air_quality.py)
    you told the election reader how the federal results file is laid out. Berlin publishes its own
    results files, laid out differently. But every Berlin election uses the same layout, so you describe
    it once.

    Berlin is a city and one of Germany's 16 federal states (*Länder*). Its state parliament is the
    *Abgeordnetenhaus* (AGH). The state returning officer (*Landeswahlleiter*) runs the elections in
    Berlin and publishes the results for each voting district in the city's 12 boroughs (*Bezirke*).
    """)
    return


@app.cell
def _():
    import altair as alt
    import pandas as pd

    from mloda.user import Feature, mloda
    from mloda_plugin_govdata.feature_groups.govdata import (
        OPTION_WAHL_HEADER_ROWS,
        OPTION_WAHL_LABEL_COLUMNS,
        OPTION_WAHL_SKIPROWS,
        OPTION_WAHL_VALUE_TYPE,
        BundeswahlleiterinReader,
        ColumnType,
        DownloadCache,
        build_client,
    )

    return (
        BundeswahlleiterinReader,
        ColumnType,
        DownloadCache,
        Feature,
        OPTION_WAHL_HEADER_ROWS,
        OPTION_WAHL_LABEL_COLUMNS,
        OPTION_WAHL_SKIPROWS,
        OPTION_WAHL_VALUE_TYPE,
        alt,
        build_client,
        mloda,
        pd,
    )


@app.cell
def _(mo):
    mo.md("""
    ## Step 1: look at the file

    Start with the Abgeordnetenhaus election of 12 February 2023. It repeated the 2021 election, which a
    court had declared invalid. Each voter has two votes: the first for a local candidate, the second
    (*Zweitstimme*) for a party. The file holds the second votes. This cell downloads it, keeps a copy on
    your disk and shows the first three lines, each cut to 150 characters.
    """)
    return


@app.cell
def _():
    AGH_2023_URL = "https://www.wahlen-berlin.de/wahlen/BE2023/AFSPRAES/agh/Datenexport_AGH2023_Zweitstimme_W_BE.csv"
    return (AGH_2023_URL,)


@app.cell
def _(AGH_2023_URL, BundeswahlleiterinReader, DownloadCache, build_client, mo):
    with build_client() as _client, DownloadCache(BundeswahlleiterinReader.cache_dir, client=_client) as _cache:
        _path = _cache.get_or_download(AGH_2023_URL).path
    _lines = _path.read_text(encoding="utf-8-sig").splitlines()
    mo.plain_text("\n".join(_line[:150] for _line in _lines[:3]))
    return


@app.cell
def _(mo):
    mo.md("""
    The first line is the header, with nothing before it. Then comes one row per voting district.

    - The first 12 columns are text. `Bezirksname` is the borough's name. `WBezArt` is the kind of
      district: `W` for a polling station, `B` for postal votes (*Briefwahl*).
    - The rest are numbers. `WberIns` counts the eligible voters (*Wahlberechtigte insgesamt*), `Waehler`
      the people who voted (*Wähler*) and `Gueltig` the valid votes (*gültige Stimmen*). `P01`, `P02` and
      so on count the votes for each party; more on them below.
    - A column ending in `p` is a percentage, written with a decimal comma (`64,9`). So read the numbers
      as decimal numbers.
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    ## Step 2: describe the layout, then read

    Four options describe what you just saw: skip 0 lines, 1 header row, 12 text columns, the rest decimal
    numbers. `BundeswahlleiterinReader` is named after the federal returning officer (*Bundeswahlleiterin*).
    Her results file sets the reader's default layout; these four options replace it.
    """)
    return


@app.cell
def _(
    ColumnType,
    OPTION_WAHL_HEADER_ROWS,
    OPTION_WAHL_LABEL_COLUMNS,
    OPTION_WAHL_SKIPROWS,
    OPTION_WAHL_VALUE_TYPE,
):
    BERLIN_LAYOUT = {
        OPTION_WAHL_SKIPROWS: 0,
        OPTION_WAHL_HEADER_ROWS: 1,
        OPTION_WAHL_LABEL_COLUMNS: 12,
        OPTION_WAHL_VALUE_TYPE: ColumnType.FLOAT,
    }
    return (BERLIN_LAYOUT,)


@app.cell
def _(mo):
    mo.md("""
    In tutorials 1 and 2, `peek` listed the columns you can ask for. Give it the layout, and it does the
    same for this file:
    """)
    return


@app.cell
def _(AGH_2023_URL, BERLIN_LAYOUT, BundeswahlleiterinReader):
    BundeswahlleiterinReader.peek(AGH_2023_URL, options=BERLIN_LAYOUT)
    return


@app.cell
def _(AGH_2023_URL, BERLIN_LAYOUT, BundeswahlleiterinReader, Feature, mloda):
    COLUMNS = ["Bezirksname", "WBezArt", "WberIns", "Waehler", "Gueltig", "P01"]
    _options = {BundeswahlleiterinReader: AGH_2023_URL, **BERLIN_LAYOUT}
    _result = mloda.run_all(
        [Feature(_name, options=_options) for _name in COLUMNS],
        compute_frameworks=["PyArrowTable"],
        column_ordering="request_order",
    )
    agh_2023 = _result[0].to_pandas()
    agh_2023
    return COLUMNS, agh_2023


@app.cell
def _(agh_2023, mo):
    _kinds = agh_2023["WBezArt"].value_counts()
    mo.md(f"""
    {len(agh_2023):,} rows in {agh_2023["Bezirksname"].nunique()} boroughs: {_kinds.get("W", 0):,} polling
    station districts and {_kinds.get("B", 0):,} postal vote districts.
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    ## Step 3: a new election is a new URL

    Berlin published three more elections in the same layout:

    - **EU 2024:** the election to the European Parliament on 9 June 2024.
    - **BT 2025:** the election to the federal parliament, the *Bundestag* (BT), on 23 February 2025.
    - **AGH 2026:** the Abgeordnetenhaus election on 20 September 2026.

    Each one is a URL. The layout options stay as they are.
    """)
    return


@app.cell
def _(AGH_2023_URL):
    ELECTIONS = {
        "AGH 2023": AGH_2023_URL,
        "EU 2024": "https://www.wahlen-berlin.de/wahlen/EU2024/AFSPRAES/Datenexport_EUROPAWAHL2024_Stimme_W_BE.csv",
        "BT 2025": (
            "https://www.wahlen-berlin.de/wahlen/BU2025/afspraes/Datenexport_BUNDESTAGSWAHL2025_Zweitstimme_W_BE.csv"
        ),
        "AGH 2026": "https://www.wahlen-berlin.de/wahlen/BE2026/AFSPRAES/agh/Datenexport_AGH2026_Zweitstimme_W_BE.csv",
    }
    return (ELECTIONS,)


@app.cell
def _(BERLIN_LAYOUT, BundeswahlleiterinReader, COLUMNS, ELECTIONS, Feature, mloda, pd):
    _frames = []
    for _election, _url in ELECTIONS.items():
        _options = {BundeswahlleiterinReader: _url, **BERLIN_LAYOUT}
        _result = mloda.run_all(
            [Feature(_name, options=_options) for _name in COLUMNS],
            compute_frameworks=["PyArrowTable"],
            column_ordering="request_order",
        )
        _frames.append(_result[0].to_pandas().assign(election=_election))
    elections = pd.concat(_frames, ignore_index=True)
    _totals = elections.groupby("election", sort=False).agg(
        rows=("WBezArt", "size"), eligible_voters=("WberIns", "sum"), voters=("Waehler", "sum")
    )
    _totals.style.format("{:,.0f}")
    return (elections,)


@app.cell
def _(mo):
    mo.md("""
    Four elections, one layout. When Berlin publishes the next one, add a line to `ELECTIONS` and run the
    cells again.

    Two things do differ between elections:

    - The voting districts. Berlin redraws them, so the number of rows changes. The 12 boroughs stay the
      same, so compare boroughs.
    - Who may vote. At the 2024 European election the minimum age was 16 and citizens of other EU
      countries could vote. At the 2025 Bundestag election the minimum age was 18.
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    ## Pitfall: postal votes are in their own rows

    Turnout is the share of eligible voters who voted: `Waehler` divided by `WberIns`. Before you divide,
    look at the two kinds of district in the 2023 election:
    """)
    return


@app.cell
def _(agh_2023):
    agh_2023.groupby("WBezArt")[["WberIns", "Waehler"]].sum().style.format("{:,.0f}")
    return


@app.cell
def _(agh_2023, mo):
    _stations = agh_2023[agh_2023["WBezArt"] == "W"]
    mo.md(f"""
    Every eligible voter is listed in a polling station district (`W`). A person who votes by post is
    counted as a voter in a postal vote district (`B`), which lists no eligible voters. So a turnout per
    row is wrong: in a `W` row the postal voters are missing, in a `B` row you divide by zero. Add up a
    whole borough, or the whole city, before you divide. For the whole city:

    - Polling station rows only (too low): {_stations["Waehler"].sum() / _stations["WberIns"].sum():.1%}
    - All rows (the turnout the Landeswahlleiter reported):
      {agh_2023["Waehler"].sum() / agh_2023["WberIns"].sum():.1%}
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    ## Try it: pick a borough

    The chart shows the borough's turnout in the four elections.
    """)
    return


@app.cell
def _(elections, mo):
    _names = sorted(elections["Bezirksname"].unique())
    borough = mo.ui.dropdown(
        options=_names, value="Mitte" if "Mitte" in _names else _names[0], label="Borough (Bezirk)"
    )
    borough
    return (borough,)


@app.cell
def _(alt, borough, elections):
    _sums = (
        elections[elections["Bezirksname"] == borough.value]
        .groupby("election", sort=False)[["WberIns", "Waehler"]]
        .sum()
        .reset_index()
    )
    _sums["turnout"] = _sums["Waehler"] / _sums["WberIns"]
    alt.Chart(_sums, title=f"Turnout in {borough.value}").mark_bar().encode(
        x=alt.X("election:N", title=None, sort=None),
        y=alt.Y("turnout:Q", title="Turnout", axis=alt.Axis(format="%")),
        tooltip=["election", alt.Tooltip("turnout:Q", format=".1%")],
    )
    return


@app.cell
def _(mo):
    mo.md("""
    ## What the P columns are

    `P01` holds the votes for the party in first place on the ballot paper, `P02` for the second, and so
    on. The place is not the party. Here is the share of the valid votes that went to `P01`:
    """)
    return


@app.cell
def _(elections):
    _sums = elections.groupby("election", sort=False)[["P01", "Gueltig"]].sum()
    (_sums["P01"] / _sums["Gueltig"]).rename("P01 share of valid votes").to_frame().style.format("{:.1%}")
    return


@app.cell
def _(mo):
    mo.md("""
    Each election has its own ballot paper. The files do not name the parties; the official results do.
    Matched against them, `P01` is the Social Democrats (SPD) in the 2023 file and the Greens (*GRÜNE*) in
    the 2024 file. The Berlin demo (see Next) shows the matching.
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    ## Where the data came from

    The files name neither a publisher nor a license. The website they come from does: its footer names the
    Landeswahlleiter and the statistics office of Berlin and Brandenburg (*Amt für Statistik*), and its
    imprint names the statistics office as publisher and states the terms. The copy on your disk records
    when you downloaded each file.
    """)
    return


@app.cell
def _(BundeswahlleiterinReader, ELECTIONS, elections, mo):
    def _retrieved(url):
        # The copy Step 3 read; a missing one means the cache was cleared since.
        _copy = BundeswahlleiterinReader.retrieval(url)
        return f"{_copy.retrieved_at:%Y-%m-%d}" if _copy else "not in the local cache any more"

    _lines = [
        "- **Publisher:** Der Landeswahlleiter für Berlin / Amt für Statistik Berlin-Brandenburg",
        "- **Website:** https://www.wahlen-berlin.de",
        *(
            f"- **{_election}:** {ELECTIONS[_election]}, retrieved {_retrieved(ELECTIONS[_election])}"
            for _election in elections["election"].unique()  # the elections Step 3 read
        ),
    ]
    mo.md("\n".join(_lines))
    return


@app.cell
def _(mo):
    mo.md("""
    The website names no open license. Its [imprint](https://www.wahlen-berlin.de/impressum.asp) allows
    reuse with a source note: "Vervielfältigung und Verbreitung, auch auszugsweise, mit Quellenangabe
    gestattet" (copying and distribution, also of extracts, permitted with source attribution). So name
    the publisher when you reuse the data, and say what you changed: here, you kept six columns and added
    up the voting districts of each borough.

    ## Next

    The Berlin demo goes further with the same files:
    party names, the people living in each voting district and an election night replayed. Run it with
    `uv run marimo edit demos/berlin_wahl_2026_demo.py`.
    [Readers](https://github.com/mloda-ai/mloda-plugin-govdata/blob/main/docs/readers.md) describes the
    election reader and its options.
    """)
    return


if __name__ == "__main__":
    app.run()
