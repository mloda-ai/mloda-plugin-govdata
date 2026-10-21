"""Tutorial 2: read election results and hourly air measurements, steering each reader with options.

Run with: uv run marimo edit tutorials/02_elections_and_air_quality.py (needs network access, no account).
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
    # Tutorial 2: elections and air quality

    **Goal:** read two more sources, election results and hourly air measurements, and use *options* to
    tell each reader what to read.

    **Time:** about 15 minutes. **You need:** basic Python and a network connection. No account.

    **Setup:** clone the repository and run `uv sync --all-extras` (see the README), then
    `uv run marimo edit tutorials/02_elections_and_air_quality.py`.

    In [tutorial 1](https://github.com/mloda-ai/mloda-plugin-govdata/blob/main/tutorials/01_first_table.py)
    the reader already knew how its file is laid out. Here you pass more options: for a file, how it is laid out; for a web
    service, what to ask it.
    """)
    return


@app.cell
def _():
    import datetime

    import altair as alt
    import pandas as pd

    from mloda.user import Feature, mloda
    from mloda_plugin_govdata.feature_groups.govdata import (
        OPTION_UBA_COMPONENT,
        OPTION_UBA_DATE_FROM,
        OPTION_UBA_DATE_TO,
        OPTION_UBA_SCOPE,
        OPTION_UBA_STATION,
        OPTION_WAHL_HEADER_ROWS,
        OPTION_WAHL_LABEL_COLUMNS,
        OPTION_WAHL_SKIPROWS,
        BundeswahlleiterinReader,
        DownloadCache,
        UbaAirReader,
        build_client,
        uba_measures_url,
    )

    return (
        BundeswahlleiterinReader,
        DownloadCache,
        Feature,
        OPTION_UBA_COMPONENT,
        OPTION_UBA_DATE_FROM,
        OPTION_UBA_DATE_TO,
        OPTION_UBA_SCOPE,
        OPTION_UBA_STATION,
        OPTION_WAHL_HEADER_ROWS,
        OPTION_WAHL_LABEL_COLUMNS,
        OPTION_WAHL_SKIPROWS,
        UbaAirReader,
        alt,
        build_client,
        datetime,
        mloda,
        pd,
        uba_measures_url,
    )


@app.cell
def _(mo):
    mo.md("""
    # Part 1: election results

    Germany elected its federal parliament, the *Bundestag*, on 23 February 2025. The Federal Returning
    Officer (*Bundeswahlleiterin*), who runs federal elections, publishes the results as one CSV file,
    `kerg.csv`. It has a row for each constituency (*Wahlkreis*), for each of the 16 federal states
    (*Länder*, one *Land*) and for the whole country.
    """)
    return


@app.cell
def _():
    KERG = "https://www.bundeswahlleiterin.de/bundestagswahlen/2025/ergebnisse/opendata/btw25/csv/kerg.csv"
    return (KERG,)


@app.cell
def _(mo):
    mo.md("""
    ## Step 1: look at the file

    Before you read a file, look at its first lines. This cell downloads it, keeps a copy on your disk and
    shows the first nine lines, each cut to 100 characters. Values are separated by `;`.
    """)
    return


@app.cell
def _(BundeswahlleiterinReader, DownloadCache, KERG, build_client, mo):
    with build_client() as _client, DownloadCache(BundeswahlleiterinReader.cache_dir, client=_client) as _cache:
        _path = _cache.get_or_download(KERG).path
    kerg_lines = _path.read_text(encoding="utf-8-sig").splitlines()
    mo.plain_text("\n".join(_line[:100] for _line in kerg_lines[:9]))
    return (kerg_lines,)


@app.cell
def _(mo):
    mo.md("""
    The first five lines are not data: copyright, license, an empty line, a title and a subtitle
    (*Amtliches Endergebnis*, official final result). Then comes a header spread over three rows. Read one
    column top to bottom:

    1. what is counted: *Wahlberechtigte* (eligible voters), *Wählende* (people who voted), *Ungültige* or
       *Gültige Stimmen* (invalid or valid votes), or a party;
    2. which vote: each voter has two. *Erststimmen* (first votes) elect a local candidate,
       *Zweitstimmen* (second votes) go to a party;
    3. which election: *Endgültig* is the final 2025 result, *Vorperiode* the previous election.

    After the header, one row per area. The first four columns are text: *Nr* (the area's number),
    *Gebiet* (its name), *gehört zu* ("belongs to") and *Gewählt* (elected: the party of the
    constituency's winner). The rest are counts. In *Gewählt*, a dash means the winner did not get a seat
    in the Bundestag: a marker, where you might expect a party.
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    ## Step 2: tell the reader the layout, then read

    Three options describe what you just saw: skip 5 lines, join 3 header rows, read the first 4 columns
    as text (the rest are whole numbers). The reader joins the three header rows with spaces, so the column
    for eligible voters' second votes in 2025 is `Wahlberechtigte Zweitstimmen Endgültig`.
    """)
    return


@app.cell
def _(
    BundeswahlleiterinReader,
    Feature,
    KERG,
    OPTION_WAHL_HEADER_ROWS,
    OPTION_WAHL_LABEL_COLUMNS,
    OPTION_WAHL_SKIPROWS,
    mloda,
):
    kerg_options = {
        BundeswahlleiterinReader: KERG,
        OPTION_WAHL_SKIPROWS: 5,
        OPTION_WAHL_HEADER_ROWS: 3,
        OPTION_WAHL_LABEL_COLUMNS: 4,
    }
    _result = mloda.run_all(
        [
            Feature("Gebiet", options=kerg_options),
            Feature("gehört zu", options=kerg_options),
            Feature("Wahlberechtigte Zweitstimmen Endgültig", options=kerg_options),
            Feature("Wählende Zweitstimmen Endgültig", options=kerg_options),
        ],
        compute_frameworks=["PyArrowTable"],
        column_ordering="request_order",
    )
    election = _result[0].to_pandas()
    election
    return election, kerg_options


@app.cell
def _(mo):
    mo.md("""
    The three layout values are the reader's defaults, made for this file; they are written out here so you can see
    them. If the next election's file is laid out differently, you change the numbers.
    `BundeswahlleiterinReader.peek(KERG)` lists all the columns you can ask for.
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    ## Step 3: keep one level

    The file mixes three levels: constituencies, *Länder* and the whole country (*Bundesgebiet*). The
    column *gehört zu* tells them apart: a constituency belongs to its Land's number, a Land belongs to
    99, the Bundesgebiet, and the Bundesgebiet belongs to nothing.
    """)
    return


@app.cell
def _(election, mo):
    _eligible = "Wahlberechtigte Zweitstimmen Endgültig"
    _belongs_to = election["gehört zu"]
    _country = election.loc[_belongs_to.isna(), _eligible].iloc[0]
    mo.md(f"""
    - {(_belongs_to.notna() & (_belongs_to != "99")).sum()} constituencies,
      {(_belongs_to == "99").sum()} Länder, {_belongs_to.isna().sum()} Bundesgebiet.
    - Eligible voters, summed over every row: {election[_eligible].sum():,}. In the Bundesgebiet row:
      {_country:,}. Each voter is counted once per level, three times in all.
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    So keep one level. Here, the 16 Länder, with their turnout: the share of eligible voters who voted.
    """)
    return


@app.cell
def _(election):
    _laender = election[election["gehört zu"] == "99"]
    turnout = _laender.assign(
        turnout=_laender["Wählende Zweitstimmen Endgültig"] / _laender["Wahlberechtigte Zweitstimmen Endgültig"]
    ).sort_values("turnout", ascending=False)[["Gebiet", "turnout"]]
    turnout.style.format({"turnout": "{:.1%}"}).hide(axis="index")
    return


@app.cell
def _(mo):
    mo.md("""
    ## Pitfall: an empty cell is not a zero

    The CDU (*Christlich Demokratische Union Deutschlands*, Christian Democratic Union) runs candidates in
    every Land but Bavaria (*Bayern*, Land number 09). In Bavaria its sister party runs instead, the CSU
    (*Christlich-Soziale Union in Bayern*, Christian Social Union). So in Bavaria's constituencies the CDU
    cells are empty. Here are both parties' first votes there:
    """)
    return


@app.cell
def _(Feature, kerg_options, mloda):
    _cdu = "Christlich Demokratische Union Deutschlands Erststimmen Endgültig"
    _csu = "Christlich-Soziale Union in Bayern e.V. Erststimmen Endgültig"
    _result = mloda.run_all(
        [Feature(_name, options=kerg_options) for _name in ("Gebiet", "gehört zu", _cdu, _csu)],
        compute_frameworks=["PyArrowTable"],
        column_ordering="request_order",
    )
    parties = _result[0].to_pandas().rename(columns={_cdu: "CDU", _csu: "CSU"})
    parties[parties["gehört zu"] == "09"]
    return (parties,)


@app.cell
def _(mo):
    mo.md("""
    The reader turns an empty cell into a missing value, which pandas shows as `NaN`. It does not turn it
    into 0. That is right: the CDU did not get zero votes
    in Bavaria, it had no candidate there. See what a 0 would do to the CDU's average result:
    """)
    return


@app.cell
def _(mo, parties):
    _cdu = parties.loc[parties["gehört zu"].notna() & (parties["gehört zu"] != "99"), "CDU"]
    mo.md(f"""
    - Average CDU first votes per constituency, empty cells left out: {_cdu.mean():,.0f}
    - The same with empty cells as 0: {_cdu.fillna(0).mean():,.0f}
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    Other German files have more traps: a decimal comma (`1,5` means 1.5), a `-` that means exactly zero,
    a `.` that means the number is unknown. In columns read as numbers, this plugin's CSV readers handle
    those too.
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    # Part 2: air quality

    The federal environment agency, the *Umweltbundesamt* (UBA), measures air quality at stations all
    over Germany. It publishes the measurements through a web service. So the options are your question:

    - which station: 143 is Berlin Grunewald, in a forest on the edge of the city;
    - which pollutant: component 3 is ozone, measured in µg/m³ (millionths of a gram per cubic metre of air);
    - which average: scope 2 is the average over one hour;
    - which days: from and to, as `YYYY-MM-DD`.

    The ids come from the UBA's own lists (its `stations`, `components` and `scopes` endpoints).
    `UbaAirReader: True` only picks the reader; the other options are
    the question.
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    ## Step 4: read one day of ozone
    """)
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
    STATION, OZONE, ONE_HOUR, DAY = 143, 3, 2, "2025-07-01"
    ozone_options = {
        UbaAirReader: True,
        OPTION_UBA_STATION: STATION,
        OPTION_UBA_COMPONENT: OZONE,
        OPTION_UBA_SCOPE: ONE_HOUR,
        OPTION_UBA_DATE_FROM: DAY,
        OPTION_UBA_DATE_TO: DAY,
    }
    _result = mloda.run_all(
        [Feature("date_start", options=ozone_options), Feature("value", options=ozone_options)],
        compute_frameworks=["PyArrowTable"],
        column_ordering="request_order",
    )
    _result[0].to_pandas()
    return DAY, ONE_HOUR, OZONE, STATION, ozone_options


@app.cell
def _(mo):
    mo.md("""
    One row per hour: when the hour starts and the average ozone over it. The UBA gives times "in the time
    zone valid at the measurement time (CET or CEST)"; every day has 24 rows, even when the clocks change.
    The reader also has a
    `date_end` column; the day's last hour ends at `24:00`, which pandas cannot read as a time, so use
    `date_start`.
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    ## Try it: pick a day

    Ozone forms in sunlight, so on a summer day it usually peaks in the afternoon. Pick a day; the chart
    below shows that day's hourly ozone at the same station.
    """)
    return


@app.cell
def _(datetime, mo):
    _yesterday = datetime.date.today() - datetime.timedelta(days=1)
    day = mo.ui.date(start="2016-01-01", stop=_yesterday.isoformat(), value="2025-07-01", label="Day")
    day
    return (day,)


@app.cell
def _(
    Feature,
    OPTION_UBA_DATE_FROM,
    OPTION_UBA_DATE_TO,
    alt,
    day,
    mloda,
    mo,
    ozone_options,
    pd,
):
    # Step 4's question for the picked day, written as "YYYY-MM-DD".
    _options = {**ozone_options, OPTION_UBA_DATE_FROM: day.value.isoformat(), OPTION_UBA_DATE_TO: day.value.isoformat()}
    _result = mloda.run_all(
        [Feature("date_start", options=_options), Feature("value", options=_options)],
        compute_frameworks=["PyArrowTable"],
        column_ordering="request_order",
    )
    _ozone = _result[0].to_pandas()
    mo.stop(_ozone.empty, mo.md(f"No measurements for {day.value}. Pick another day."))
    alt.Chart(
        _ozone.assign(hour=pd.to_datetime(_ozone["date_start"]).dt.hour), title=f"Ozone on {day.value}"
    ).mark_line(point=True).encode(
        x=alt.X("hour:Q", title="Hour the measurement starts"),
        y=alt.Y("value:Q", title="Ozone (µg/m³)"),
        tooltip=["date_start", "value"],
    )
    return


@app.cell
def _(mo):
    mo.md("""
    ## Where the data came from

    The election file names its publisher and license in its own first two lines. For both sources, the
    copy on your disk records when you downloaded it.
    """)
    return


@app.cell
def _(
    BundeswahlleiterinReader,
    DAY,
    DownloadCache,
    KERG,
    ONE_HOUR,
    OZONE,
    STATION,
    UbaAirReader,
    build_client,
    kerg_lines,
    mo,
    uba_measures_url,
):
    # The same address the reader built in Step 4, so the cache finds that copy.
    _ozone_url = uba_measures_url(station=STATION, component=OZONE, scope=ONE_HOUR, date_from=DAY, date_to=DAY)
    with build_client() as _client:
        with DownloadCache(BundeswahlleiterinReader.cache_dir, client=_client) as _cache:
            _kerg_retrieved = _cache.get_or_download(KERG, revalidate=False).retrieved_at
        with DownloadCache(UbaAirReader.cache_dir, client=_client) as _cache:
            _ozone_retrieved = _cache.get_or_download(_ozone_url, revalidate=False).retrieved_at
    mo.md(f"""
    **Election results**

    - **Publisher:** `{kerg_lines[0].strip(";")}`
    - **License:** `{kerg_lines[1].strip(";")}`
    - **File:** {KERG}
    - **Retrieved:** {_kerg_retrieved:%Y-%m-%d}

    **Ozone (Step 4)**

    - **Source:** Umweltbundesamt (German Federal Environment Agency),
      https://www.umweltbundesamt.de/daten/luft/luftdaten
    - **License:** `{UbaAirReader.LICENSE}`, the id the reader declares for the UBA's terms (see Readers)
    - **Query:** {_ozone_url}
    - **Retrieved:** {_ozone_retrieved:%Y-%m-%d}
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    Name the source when you reuse the data. The election license (*Datenlizenz Deutschland*, Data
    License Germany, attribution, version 2.0) also asks you to say what you changed:
    here, you kept only the Länder rows and computed the turnout. The ozone values are shown as read.

    ## Next

    [Tutorial 3](https://github.com/mloda-ai/mloda-plugin-govdata/blob/main/tutorials/03_destatis_table.py)
    reads a table from Destatis, the federal statistical office (it needs a free account).
    [Readers](https://github.com/mloda-ai/mloda-plugin-govdata/blob/main/docs/readers.md)
    describes the election and air quality readers and their options.
    """)
    return


if __name__ == "__main__":
    app.run()
