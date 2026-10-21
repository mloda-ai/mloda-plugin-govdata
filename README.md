[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://github.com/mloda-ai/mloda-plugin-govdata/blob/main/LICENSE)
[![mloda](https://img.shields.io/badge/built%20with-mloda-blue.svg)](https://github.com/mloda-ai/mloda)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Tests](https://github.com/mloda-ai/mloda-plugin-govdata/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/mloda-ai/mloda-plugin-govdata/actions/workflows/test.yml?query=branch%3Amain)
[![Prototype Fund](https://img.shields.io/badge/Prototype%20Fund-Jahrgang%2002-f1c40f.svg)](https://prototypefund.de)

# mloda-plugin-govdata

German open government data as typed tables you can trust: found, downloaded, parsed, made comparable, and traceable to its source. A plugin for [mloda](https://github.com/mloda-ai/mloda): you name the columns, it does the rest.

## Why

The data is open, but every team rewrites the same scripts:

- **German CSV.** Decimal commas, multi-row headers, and signs like `-` and `.` that mean different things.
- **Changing borders.** Göttingen and Osterode merged in 2016. The raw Destatis table shows three districts, and zeros for the years each one did not exist.
- **Lost provenance.** Which file, which license, which attribution: gone by the time the chart is done.

## What's inside

| | |
| --- | --- |
| **Sources** | GovData.de, Destatis GENESIS (GENESIS-Online, Regionalstatistik), Bundeswahlleiterin election results, UBA air quality |
| **Harmonization** | district series on today's borders, NUTS codes for German region keys, typed years |
| **Recipes** | JSON files that pin the features, joins, source, license, and checksum of one result |

## Install

```bash
pip install mloda-plugin-govdata
```

## Quick start

Auf Deutsch: [Schnellstart](https://github.com/mloda-ai/mloda-plugin-govdata/blob/main/docs/schnellstart.md).

No account needed for GovData:

```python
from mloda.user import Feature, mloda
from mloda_plugin_govdata.feature_groups.govdata import StuttgartPopulationReader

slug = "einwohner-nach-altersgruppen-und-stadtbezirken"
result = mloda.run_all(
    [Feature("Einwohner", options={StuttgartPopulationReader: slug})],
    compute_frameworks=["PyArrowTable"],
)
```

Destatis, with a free [GENESIS account](https://github.com/mloda-ai/mloda-plugin-govdata/blob/main/docs/credentials.md):

```python
from mloda_plugin_govdata.feature_groups.destatis import DestatisReader

result = mloda.run_all(
    [Feature("value", options={DestatisReader: "12411-0010"})],  # population by Land
    compute_frameworks=["PyArrowTable"],
)
```

Göttingen on today's borders, with `value__rebased` ([full example](https://github.com/mloda-ai/mloda-plugin-govdata/blob/main/docs/harmonization.md#usage)):

```
~key   ~year  ~value    ~flag     ~sources
03159  2013   322616.0  rebased   [03152, 03156]
03159  2015   329538.0  rebased   [03152, 03156]
03159  2016   327065.0  observed  []
```

## Tutorials and demos

Step-by-step [marimo](https://marimo.io) notebooks. Set up once:

```bash
git clone https://github.com/mloda-ai/mloda-plugin-govdata.git
cd mloda-plugin-govdata
uv sync --all-extras
```

Tutorials, about 15 minutes each:

1. [Your first table](https://github.com/mloda-ai/mloda-plugin-govdata/blob/main/tutorials/01_first_table.py): find a GovData dataset, see its columns, read it. No account. `uv run marimo edit tutorials/01_first_table.py`
2. [Elections and air quality](https://github.com/mloda-ai/mloda-plugin-govdata/blob/main/tutorials/02_elections_and_air_quality.py): read the 2025 Bundestag election results and hourly ozone, steering each reader with options. No account. `uv run marimo edit tutorials/02_elections_and_air_quality.py`
3. [A table from Destatis](https://github.com/mloda-ai/mloda-plugin-govdata/blob/main/tutorials/03_destatis_table.py): read population by Land from GENESIS-Online, choose years and categories, read the signs that replace numbers. Free GENESIS-Online account, token in `.env`. `uv run marimo edit tutorials/03_destatis_table.py`

Demos: `uv run marimo edit demos/govdata_demo.py` walks through every source, the Göttingen series, and a join of population and eligible voters for all 16 Länder; its Destatis chapters skip themselves without GENESIS credentials. `demos/berlin_wahl_2026_demo.py` reads four Berlin elections with one set of reader options.

## Docs

- [Readers](https://github.com/mloda-ai/mloda-plugin-govdata/blob/main/docs/readers.md): every source, dataset search, `peek`
- [Destatis options](https://github.com/mloda-ai/mloda-plugin-govdata/blob/main/docs/destatis-options.md) and [credentials](https://github.com/mloda-ai/mloda-plugin-govdata/blob/main/docs/credentials.md)
- [Harmonization](https://github.com/mloda-ai/mloda-plugin-govdata/blob/main/docs/harmonization.md)
- [Recipes](https://github.com/mloda-ai/mloda-plugin-govdata/blob/main/docs/recipes.md)
- [Architecture](https://github.com/mloda-ai/mloda-plugin-govdata/blob/main/docs/architecture.md) and [adding a reader](https://github.com/mloda-ai/mloda-plugin-govdata/blob/main/docs/adding-a-reader.md)

## Status

Young but working, built during a Prototype Fund stage (June to November 2026). The API may still change; the [release notes](https://github.com/mloda-ai/mloda-plugin-govdata/releases) give a migration for every breaking change.

## Funding

Funded by the German Federal Ministry of Research, Technology and Space (BMFTR) through the [Prototype Fund](https://prototypefund.de), supported by the [Open Knowledge Foundation Deutschland](https://okfn.de). Funding code: **16IS26S11**.

<p>
  <img src="https://raw.githubusercontent.com/mloda-ai/mloda-plugin-govdata/main/logos/bmftr.png" alt="Funded by the Federal Ministry of Research, Technology and Space (BMFTR)" height="110">
  &nbsp;&nbsp;&nbsp;
  <img src="https://raw.githubusercontent.com/mloda-ai/mloda-plugin-govdata/main/logos/prototypefund.png" alt="Supported by the Prototype Fund" height="110">
</p>
