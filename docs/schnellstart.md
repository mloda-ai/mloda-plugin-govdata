# Schnellstart

Offene Verwaltungsdaten aus Deutschland als typisierte Tabellen: gefunden, heruntergeladen, eingelesen, vergleichbar gemacht und bis zur Quelle nachvollziehbar. Ein Plugin für [mloda](https://github.com/mloda-ai/mloda): Sie nennen die Spalten, den Rest erledigt das Plugin.

## Installation

```bash
pip install mloda-plugin-govdata
```

## GovData, ohne Konto

```python
from mloda.user import Feature, mloda
from mloda_plugin_govdata.feature_groups.govdata import StuttgartPopulationReader

slug = "einwohner-nach-altersgruppen-und-stadtbezirken"
result = mloda.run_all(
    [Feature("Einwohner", options={StuttgartPopulationReader: slug})],
    compute_frameworks=["PyArrowTable"],
)
```

Der Feature-Name ist die gewünschte Spalte, die Option wählt Reader und Datensatz. `result[0]` ist eine PyArrow-Tabelle.

## Destatis, mit kostenlosem GENESIS-Konto

Registrieren Sie sich bei [GENESIS-Online](https://genesis.destatis.de/datenbank/online/) und setzen Sie den Token, den die Weboberfläche unter „Webservice-Schnittstelle (API)“ zeigt, als Umgebungsvariable `GENESIS_TOKEN` ([Details auf Englisch](credentials.md)).

```python
from mloda.user import Feature, mloda
from mloda_plugin_govdata.feature_groups.destatis import DestatisReader

result = mloda.run_all(
    [Feature("value", options={DestatisReader: "12411-0010"})],  # Bevölkerung nach Ländern
    compute_frameworks=["PyArrowTable"],
)
```

## Kreise auf heutigem Gebietsstand

Die Landkreise Göttingen und Osterode am Harz wurden 2016 zusammengelegt. `value__rebased` rechnet die Jahre davor auf die heutigen Grenzen um ([vollständiges Beispiel, englisch](harmonization.md#usage)):

```
~key   ~year  ~value    ~flag     ~sources
03159  2013   322616.0  rebased   [03152, 03156]
03159  2015   329538.0  rebased   [03152, 03156]
03159  2016   327065.0  observed  []
```

## Tutorials und Demos

Schritt-für-Schritt-Notebooks mit [marimo](https://marimo.io). Einmal einrichten:

```bash
git clone https://github.com/mloda-ai/mloda-plugin-govdata.git
cd mloda-plugin-govdata
uv sync --all-extras
```

Tutorials (englisch), je etwa 15 Minuten:

1. [Your first table](../tutorials/01_first_table.py): einen GovData-Datensatz finden, seine Spalten ansehen, ihn einlesen. Ohne Konto. `uv run marimo edit tutorials/01_first_table.py`
2. [Elections and air quality](../tutorials/02_elections_and_air_quality.py): die Ergebnisse der Bundestagswahl 2025 und stündliche Ozonwerte einlesen, jeden Reader über Optionen steuern. Ohne Konto. `uv run marimo edit tutorials/02_elections_and_air_quality.py`

Demos: `uv run marimo edit demos/govdata_demo.py` führt durch alle Quellen, die Göttinger Reihe und eine Verknüpfung von Bevölkerung und Wahlberechtigten für alle Länder; ohne GENESIS-Zugang werden die Destatis-Kapitel übersprungen. `demos/berlin_wahl_2026_demo.py` liest vier Berliner Wahlen mit denselben Reader-Optionen.

## Weiterlesen (englisch)

- [Readers](readers.md): alle Quellen, Datensatzsuche, `peek`
- [Destatis options](destatis-options.md) und [credentials](credentials.md)
- [Harmonization](harmonization.md)
- [Recipes](recipes.md)
- [Architecture](architecture.md) und [adding a reader](adding-a-reader.md)
