"""Marimo demo: Berlin election 2026, the waiting cell.

One set of reader options connects Berlin's open voting data: three past elections
(AGH 2023, EU 2024, BT 2025) per voting district, demographics per district,
and the official 2023 result on the 2026 district boundaries. After the election on
20 September 2026, one config slot holds the 2026 export URL, and the same
options read the new results.

Run with: uv run marimo edit demos/berlin_wahl_2026_demo.py (needs network access;
install the "demo" extra).
"""

import marimo

__generated_with = "0.23.11"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell
def _(mo):
    mo.md("""
    # Berlin election 2026: the waiting cell

    On **20 September 2026** Berlin elected its 20th state parliament, the
    *Abgeordnetenhaus* (AGH). This notebook connects the open voting data
    before and after that day through one set of reader options. At the end,
    one config slot holds the 2026 export URL, and the same options read the
    new results. A new election is configuration.

    Everything below runs on published open data, the 2026 results included.

    Part of the Prototype Fund project mloda-plugin-govdata (FKZ 16IS26S11).
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
        search_datasets,
    )
    from mloda_plugin_govdata.feature_groups.govdata.core.client import build_client, request_with_retry

    return (
        BundeswahlleiterinReader,
        ColumnType,
        Feature,
        OPTION_WAHL_HEADER_ROWS,
        OPTION_WAHL_LABEL_COLUMNS,
        OPTION_WAHL_SKIPROWS,
        OPTION_WAHL_VALUE_TYPE,
        alt,
        build_client,
        mloda,
        pd,
        request_with_retry,
        search_datasets,
    )


@app.cell
def _(mo):
    mo.md("""
    ## 1. Discover: what Berlin publishes

    Berlin's election datasets are harvested from daten.berlin.de into
    GovData, so the plugin's CKAN search finds them.
    """)
    return


@app.cell
def _(mo):
    election_query = mo.ui.text(value="wahlen berlin wahlbezirken", label="GovData search", full_width=True)
    election_query
    return (election_query,)


@app.cell
def _(build_client, election_query, pd, search_datasets):
    with build_client() as _client:
        _hits = list(search_datasets(_client, election_query.value, max_results=10))
    election_datasets = pd.DataFrame({"name": [d.name for d in _hits], "title": [d.title for d in _hits]})
    election_datasets
    return


@app.cell
def _(mo):
    mo.md("""
    An honest footnote: the statistics office relaunched its website in
    July 2026. In November 2026 the CSV links behind these catalog entries
    still returned a web page instead of data. Open data needs consumers
    that notice. The cells below therefore read the wahlen-berlin.de exports
    directly, which are alive and stable.
    """)
    return


@app.cell
def _(mo):
    mo.md("""
    ## 2. One set of options, three elections, one city

    The state returning officer (*Landeswahlleiter*) publishes every election
    in one export layout: a single header row, twelve label columns, then
    vote counts and percentages per party column. So one layout, passed as
    feature options, reads all of them; only the URL changes.
    """)
    return


@app.cell
def _(
    BundeswahlleiterinReader,
    ColumnType,
    OPTION_WAHL_HEADER_ROWS,
    OPTION_WAHL_LABEL_COLUMNS,
    OPTION_WAHL_SKIPROWS,
    OPTION_WAHL_VALUE_TYPE,
):
    BERLIN_EXPORTS = {
        "AGH 2023": "https://www.wahlen-berlin.de/wahlen/BE2023/AFSPRAES/agh/Datenexport_AGH2023_Zweitstimme_W_BE.csv",
        "EU 2024": "https://www.wahlen-berlin.de/wahlen/EU2024/AFSPRAES/Datenexport_EUROPAWAHL2024_Stimme_W_BE.csv",
        "BT 2025": (
            "https://www.wahlen-berlin.de/wahlen/BU2025/afspraes/Datenexport_BUNDESTAGSWAHL2025_Zweitstimme_W_BE.csv"
        ),
    }

    def berlin_options(url: str) -> dict[object, object]:
        # One layout for every export file: no preamble, one header row,
        # 12 label columns (Adresse..Zeit), float values (counts and percentages).
        return {
            BundeswahlleiterinReader: url,
            OPTION_WAHL_SKIPROWS: 0,
            OPTION_WAHL_HEADER_ROWS: 1,
            OPTION_WAHL_LABEL_COLUMNS: 12,
            OPTION_WAHL_VALUE_TYPE: ColumnType.FLOAT,
        }

    # The exports label parties by ballot position (P01, P02, ...). Decoded by
    # matching city-wide sums against the official results; see the proof cell
    # and, for 2026, the waiting cell's Votes column.
    PARTY_LEGEND = {
        "AGH 2023": {"P01": "SPD", "P02": "CDU", "P03": "GRÜNE", "P04": "Die Linke", "P05": "AfD", "P06": "FDP"},
        "EU 2024": {
            "P01": "GRÜNE",
            "P02": "CDU",
            "P03": "SPD",
            "P04": "Die Linke",
            "P05": "AfD",
            "P07": "FDP",
            "P28": "BSW",
        },
        "BT 2025": {
            "P01": "SPD",
            "P02": "GRÜNE",
            "P03": "CDU",
            "P04": "Die Linke",
            "P05": "AfD",
            "P06": "FDP",
            "P16": "BSW",
        },
        # Every position that received votes in 2026.
        "AGH 2026": {
            "P01": "CDU",
            "P02": "SPD",
            "P03": "GRÜNE",
            "P04": "Die Linke",
            "P05": "AfD",
            "P06": "FDP",
            "P07": "Tierschutzpartei",
            "P08": "Die PARTEI",
            "P09": "Volt",
            "P12": "Die Urbane.",
            "P13": "DKP",
            "P14": "ÖDP",
            "P15": "HEIMAT",
            "P16": "B*",
            "P17": "SGP",
            "P24": "BSW",
            "P27": "PdF",
        },
    }
    return BERLIN_EXPORTS, PARTY_LEGEND, berlin_options


@app.cell
def _(BERLIN_EXPORTS, Feature, PARTY_LEGEND, berlin_options, mloda, pd):
    _frames = []
    for _election, _url in BERLIN_EXPORTS.items():
        _opts = berlin_options(_url)
        _wanted = ["Bezirksname", "OstWest", "Gueltig", *PARTY_LEGEND[_election]]
        _table = mloda.run_all(
            [Feature(_column, options=_opts) for _column in _wanted],
            compute_frameworks=["PyArrowTable"],
        )[0]
        _frame = _table.to_pandas().rename(columns=PARTY_LEGEND[_election])
        _frame["election"] = _election
        _frames.append(_frame)
    elections = pd.concat(_frames, ignore_index=True)
    elections
    return (elections,)


@app.cell
def _(mo):
    mo.md("""
    ### Proof of the party legend

    The exports never name the parties. City-wide sums recover them: each
    column's share matches exactly one line of the official result. AGH 2023
    P01 sums to 279,017 votes and P03 to 278,964, which is the famous 53-vote
    gap between SPD and GRÜNE.
    """)
    return


@app.cell
def _(elections):
    party_cols = [_c for _c in elections.columns if _c not in ("Bezirksname", "OstWest", "Gueltig", "election")]
    # min_count=1: a party that did not run stays empty
    _sums = elections.groupby("election")[[*party_cols, "Gueltig"]].sum(min_count=1)
    party_shares = (100 * _sums[party_cols].div(_sums["Gueltig"], axis=0)).round(1)
    party_shares
    return (party_cols,)


@app.cell
def _(elections, mo):
    _boroughs = sorted(elections["Bezirksname"].unique())
    borough_pick = mo.ui.dropdown(
        options=_boroughs, value="Mitte" if "Mitte" in _boroughs else _boroughs[0], label="Borough (Bezirk)"
    )
    borough_pick
    return (borough_pick,)


@app.cell
def _(alt, borough_pick, elections, party_cols):
    _borough = elections[elections["Bezirksname"] == borough_pick.value]
    _sums = _borough.groupby("election")[[*party_cols, "Gueltig"]].sum(min_count=1)
    _long = (
        (100 * _sums[party_cols].div(_sums["Gueltig"], axis=0))
        .reset_index()
        .melt(id_vars=["election"], var_name="party", value_name="share")
        .dropna()
    )
    alt.Chart(_long, title=f"{borough_pick.value}: the same borough, three different parliaments").mark_bar().encode(
        x=alt.X("party:N", title=None, sort="-y"),
        xOffset="election:N",
        y=alt.Y("share:Q", title="Vote share %"),
        color=alt.Color("election:N", title="Election"),
        tooltip=["party", "election", alt.Tooltip("share:Q", format=".1f")],
    )
    return


@app.cell
def _(mo):
    mo.md("""
    ## 3. Neighborhood compass: demographics meet votes

    The statistics office publishes structural data (*Strukturdaten*) for the
    2026 voting districts and, crucially, the 2023 results recalculated onto
    the 2026 boundaries (the official baseline for the 2026 swing). Joined on
    the district key, demographics meet votes. The fact that every export
    still carries an East/West field (`OstWest`) is itself part of the story:
    color by it and the two clouds separate.
    """)
    return


@app.cell
def _(build_client, pd, request_with_retry):
    import io

    _structure_url = (
        "https://download.statistik-berlin-brandenburg.de/aa56eddd2ea25921/1dd6f94397c4/DL_BE_AH2026_Strukturdaten.xlsx"
    )
    _baseline_url = (
        "https://download.statistik-berlin-brandenburg.de/eddea71cdf4e6f2b/291e0923b0a7/DL_BE_AGH2026_AGH2023.xlsx"
    )
    with build_client() as _client:
        _structure_bytes = request_with_retry(_client, "GET", _structure_url).content
        _baseline_bytes = request_with_retry(_client, "GET", _baseline_url).content
    structure = pd.read_excel(io.BytesIO(_structure_bytes), sheet_name="Strukturdaten")
    baseline_2023 = pd.read_excel(io.BytesIO(_baseline_bytes), sheet_name="2023_Zweitstimme")
    districts = structure.merge(baseline_2023, on="Adresse", suffixes=("", "_2023"))
    districts = districts[districts["Wahlbezirksart"] == "W"].copy()  # polling station districts: residents live there
    districts["turnout"] = 100 * districts["Wählende"] / districts["Wahlberechtigte insgesamt"]
    districts.head(10)
    return (districts,)


@app.cell
def _(mo):
    compass_x = mo.ui.dropdown(
        options=[
            "Einwohner 65 und älter Prozent",
            "Einwohner 18 - 65 Prozent",
            "Ausländer Prozent",
            "EU-Bürger Prozent",
        ],
        value="Einwohner 65 und älter Prozent",
        label="Demographic share (x)",
    )
    compass_y = mo.ui.dropdown(
        options=[
            "CDU in Prozent",
            "SPD in Prozent",
            "GRÜNE in Prozent",
            "Die Linke in Prozent",
            "AfD in Prozent",
            "FDP in Prozent",
            "turnout",
        ],
        value="GRÜNE in Prozent",
        label="2023 result (y)",
    )
    mo.hstack([compass_x, compass_y])
    return compass_x, compass_y


@app.cell
def _(alt, compass_x, compass_y, districts):
    alt.Chart(districts, title="Each dot is a voting district (2026 boundaries)").mark_circle(opacity=0.45).encode(
        x=alt.X(f"{compass_x.value}:Q"),
        y=alt.Y(f"{compass_y.value}:Q"),
        color=alt.Color("OstWest:N", title="East/West"),
        tooltip=["Adresse", "Bezirksname", alt.Tooltip(f"{compass_y.value}:Q", format=".1f")],
    )
    return


@app.cell
def _(mo):
    mo.md("""
    ## 4. Election night, replayed

    The EU 2024 export carries genuine election-night count timestamps: the
    first voting district reported at 18:27, the last before midnight.
    Replaying the running shares shows the result stabilizing within an hour.
    (The AGH 2023 and BT 2025 timestamps reflect multi-day final data entry
    instead.)
    """)
    return


@app.cell
def _(BERLIN_EXPORTS, Feature, PARTY_LEGEND, alt, berlin_options, mloda, pd):
    _opts = berlin_options(BERLIN_EXPORTS["EU 2024"])
    _parties = PARTY_LEGEND["EU 2024"]
    _wanted = ["Zeit", "Gueltig", *_parties]
    _table = mloda.run_all(
        [Feature(_column, options=_opts) for _column in _wanted],
        compute_frameworks=["PyArrowTable"],
    )[0]
    _night = _table.to_pandas().rename(columns=_parties)
    _night["time"] = pd.to_datetime("2024-06-09 " + _night["Zeit"])
    _night = _night.sort_values("time").reset_index(drop=True)
    _cum = _night[[*_parties.values(), "Gueltig"]].cumsum()
    _running = 100 * _cum[list(_parties.values())].div(_cum["Gueltig"], axis=0)
    _running["time"] = _night["time"]
    _long = _running.melt(id_vars=["time"], var_name="party", value_name="running share")
    alt.Chart(_long, title="EU 2024 in Berlin: the running result on election night").mark_line().encode(
        x=alt.X("time:T", title="9 June 2024"),
        y=alt.Y("running share:Q", title="Vote share % (cumulative)"),
        color=alt.Color("party:N", title="Party"),
    )
    return


@app.cell
def _(mo):
    mo.md("""
    ## 5. The waiting cell

    This is the cell this notebook exists for. Before 20 September 2026 it
    held `None`; afterwards the Landeswahlleiter published the 2026 export
    at the path predicted from BE2023 and BU2025, with the same columns. The
    URL below is the only new input the reader needs: no release, no change
    to the reader.
    """)
    return


@app.cell
def _():
    ELECTION_2026_URL = (
        "https://www.wahlen-berlin.de/wahlen/BE2026/AFSPRAES/agh/Datenexport_AGH2026_Zweitstimme_W_BE.csv"
    )
    return (ELECTION_2026_URL,)


@app.cell
def _(ELECTION_2026_URL, Feature, PARTY_LEGEND, berlin_options, mloda, mo, pd):
    _opts = berlin_options(ELECTION_2026_URL)
    _parties = PARTY_LEGEND["AGH 2026"]
    _table = mloda.run_all(
        [Feature(_column, options=_opts) for _column in ["Bezirksname", "Gueltig", *_parties]],
        compute_frameworks=["PyArrowTable"],
    )[0]
    _frame = _table.to_pandas().rename(columns=_parties)
    _votes = _frame[list(_parties.values())].sum().sort_values(ascending=False)
    _valid = _frame["Gueltig"].sum()  # valid second votes
    _rest = int(_valid - _votes.sum())
    _check = "every valid vote is accounted for" if _rest == 0 else f"{_rest:,} valid votes sit in undecoded positions"
    waiting_cell = pd.DataFrame(
        {
            "Party": _votes.index,
            "Votes": _votes.astype(int).values,
            "Vote share %": (100 * _votes / _valid).round(1).values,
        }
    )
    mo.vstack(
        [
            mo.md(
                f"**AGH election 2026**: {len(_frame):,} voting districts in the export. "
                f"The {len(_parties)} parties hold {int(_votes.sum()):,} votes, the export {int(_valid):,} valid "
                f"votes: {_check}."
            ),
            waiting_cell,
        ]
    )
    return


@app.cell
def _(mo):
    mo.md("""
    The party names are a lookup added after the official final result,
    decoded as in section 2: each ballot
    position's city-wide sum matches one party in the official final result of
    12 October 2026 (*Amtliches Endergebnis*,
    [wahlen-berlin.de](https://www.wahlen-berlin.de/wahlen/BE2026/AFSPRAES/agh/index.html)),
    vote for vote.

    Sources: Der Landeswahlleiter für Berlin (wahlen-berlin.de) and the Amt
    für Statistik Berlin-Brandenburg, the statistics office of Berlin and
    Brandenburg.
    """)
    return


if __name__ == "__main__":
    app.run()
