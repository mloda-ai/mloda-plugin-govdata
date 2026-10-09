# Harmonization features

Three derived FeatureGroups turn a reader's columns into comparable ones. Each is a chained feature
(`<column>__<operation>`) that sits on top of the reader features: the reader locator you set on the
harmonized feature travels to the reader columns it needs, so one `Feature` describes the whole chain.

## Terms

| Term | Meaning |
| --- | --- |
| Land | One of the 16 federal states; 2-digit AGS (`03` Niedersachsen). |
| Kreis | A district (Landkreis or kreisfreie Stadt) within a Land; 5-digit AGS (`03159` Goettingen). |
| AGS | Amtlicher Gemeindeschluessel, the official area key: 2 digits for a Land, 5 for a Kreis, 8 for a Gemeinde. Kept as a string, since leading zeros matter. |
| Gebietsstand | The territorial layout on a reference date: which keys exist and what each covers. A merger ends one Gebietsstand and starts the next. |
| Stichtag | The reference date of a snapshot value, such as the population on 31 December. |
| LAU | Local Administrative Units, Eurostat's municipality level; in Germany the Gemeinde or gemeindefreies Gebiet, coded by its 8-digit AGS. |
| NUTS | Eurostat's regional classification: NUTS-1 (the Laender), NUTS-2, NUTS-3 (the Kreise). Eurostat revises it every few years; the NUTS version (`2024`) names which classification a code belongs to. The LAU-to-NUTS crosswalk maps each LAU to its NUTS-3 code for one Gebietsstand and one NUTS version. |
| BBSR Umsteigeschluessel | The BBSR's conversion keys between Gebietsstaende: one key sheet per consecutive pair of years (`2015-2016`), giving the population and area share (and, on later sheets, the employee share) each old Kreis passes to each new one. |
| GV-ISys | Destatis' Gemeindeverzeichnis; its yearly change files list mergers and key changes with their effective dates. |
| ffcsv | The GENESIS flat-file CSV: one row per value cell, with `time`, numbered variable blocks (`1_variable_attribute_code` holds the key) and `value`. |
| JAHR / STAG | GENESIS time labels: a plain year (`2015`) or a 31 December Stichtag (`2015-12-31`); both parse to the same annual `time`. |
| `value_marker` | The raw GENESIS sign of a `value` cell, empty for a number: `-` (nichts vorhanden) reads as 0, though `value__rebased` excludes one where the key sheet says the Kreis did not exist and reports one it sums; `.`, `...`, `/`, `x` and `()` (unknown, withheld, not yet available, not meaningful) read as null. |
| census break | Zensus 2011 and Zensus 2022 re-based the population figures; values across a break are not comparable. Listed in `~provenance` when the years span one, never smoothed. |

## Usage

`HarmonizationFeature.cache_dir` holds the reference-table cache (BBSR keys, NUTS/LAU crosswalk,
GV-ISys changes) that `KreisRebaseFeature` and `AgsToNutsFeature` read; independent of
`BaseGovDataReader.cache_dir` (the reader's download cache), though both default to the same
location. `AnnualPeriodFeature` inherits the attribute but reads no reference table. Set
`HarmonizationFeature.cache_dir` itself, not one subclass's, to move every group's cache at once.

```python
from mloda.user import Feature, Options, mloda
from mloda_plugin_govdata.feature_groups.destatis import DestatisReader
from mloda_plugin_govdata.feature_groups.govdata import CacheMissError, DownloadCache
from mloda_plugin_govdata.feature_groups.harmonization import KreisRebaseFeature  # registers the groups
from mloda_plugin_govdata.feature_groups.harmonization.core.reference.bbsr import load_bbsr_kreise

with DownloadCache(KreisRebaseFeature.cache_dir) as cache:
    try:
        load_bbsr_kreise(cache)  # offline: the cached key file, checked against its pinned sha256
    except CacheMissError:
        load_bbsr_kreise(cache, revalidate=True)  # first run: fetch it once

goettingen = {
    "name": "12411-0015",
    "regionalvariable": "KREISE",
    "regionalkey": ["03152", "03156", "03159"],
    "startyear": 2013,
    "endyear": 2017,
}
result = mloda.run_all(
    [
        Feature(
            "value__rebased",
            options={DestatisReader.__name__: goettingen, "rebase_from_year": 2015, "rebase_to_year": 2016},
        )
    ],
    compute_frameworks=["PyArrowTable"],
)
result[0]  # value__rebased~key, ~year, ~value, ~flag, ~sources, ~marker, ~issues, ~provenance
```

Every group also takes a configuration-based name with the source column in `in_features` and the
parameters in the group options, the form a recipe file carries:

```python
Feature(
    "destatis__bevoelkerung__kreise",
    Options(
        group={DestatisReader.__name__: goettingen, "rebase_from_year": 2015, "rebase_to_year": 2016},
        context={"in_features": "value"},
    ),
)
```

## Feature names

| Name | Group | Result |
| --- | --- | --- |
| `<col>__rebased` | `KreisRebaseFeature` | one row per Kreis and year, as the parts `~key` to `~provenance` |
| `<key>__nuts2024` | `AgsToNutsFeature` | row-aligned parts `~key`, `~nuts1`, `~nuts2`, `~nuts3`, `~version`, `~unmatched` |
| `<time>__year_period` | `AnnualPeriodFeature` | one `date32` column, no parts |
| `<name>~<part>` | the group of `<name>` | that part alone (`value__rebased~flag`) |
| `<name>~key__nuts2024` | `AgsToNutsFeature` | NUTS codes for a part's keys (`value__rebased~key__nuts2024`) |
| configuration-based name | the group its options select | the same parts under that name (`destatis__bevoelkerung__kreise~value`); the source column goes in `in_features`, the parameters in the group options |

- Names are ASCII (`bevoelkerung`, not `Bevölkerung`).
- A part is lowercase letters and digits. An unknown one (`value__rebased~edition`) fails at match time,
  before any fetch, and the error lists the group's parts.
- Over `DestatisReader`, a configuration-based name must contain `__`: the reader claims every other name its
  option is set for, and mloda then finds two groups. Over the other readers, name the group instead (see
  [Over other readers](#over-other-readers)).
- mloda returns one frame per FeatureGroup, so a reader column requested next to a harmonized feature lands
  in its own frame.

## `value__rebased` (`KreisRebaseFeature`)

Re-bases Kreis observations onto a later Gebietsstand with the BBSR Umsteigeschluessel
(`mloda_plugin_govdata/feature_groups/harmonization/core/rebase.py`). Reads the ffcsv columns
`1_variable_attribute_code` (variable block 1 must be `KREISE`), `time`, the value column and
`value_marker`; the key sheet comes from the BBSR file in the cache
(`load_bbsr_kreise(cache, revalidate=True)` once, offline afterwards).

| Option | Meaning |
| --- | --- |
| `rebase_from_year`, `rebase_to_year` | the key sheet (`2015` and `2016` pick sheet `2015-2016`); required |
| `rebase_share` | `population` (default), `area`, or `employees` |
| `rebase_tolerance` | share-sum tolerance, renormalized inside, raises beyond |
| `rebase_on_unmatched`, `rebase_on_incomplete` | `raise` (default), `flag`, or `drop` |

Output, one row per Kreis and year: `~key`, `~year`, `~value` (float, never rounded), `~flag`
(`observed` or `rebased`), `~sources` (the contributing keys), `~marker` (the raw GENESIS sign of an
observed cell), `~issues` (the records of the issues that touch that row: `kind`, `key`, `year`, `detail`,
`target`), and `~provenance`. `~sources` is a list of strings, `~issues` and `~provenance` are JSON strings.
The input rows do not survive; a partial sum or a key the sheet does not know raises unless the policy says
otherwise.

`~provenance` is the same on every row: the key sheet's `source`, `url`, `sha256`, `from_year`, `to_year`,
`sheet` and `share`, the `census_breaks` the years span, and `issues_elsewhere`, the records of the issues no
row carries. Abridged (the cell is one line, the URL is cut, and only one record is shown):

```json
{
  "census_breaks": [],
  "from_year": 2015,
  "issues_elsewhere": [
    {"detail": "03152 does not exist from 31.12.2016 on per key sheet 2015-2016; its 2016 cell ('-') is excluded",
     "key": "03152", "kind": "not_applicable", "target": null, "year": 2016}
  ],
  "sha256": "b7250207cae01268667426ba416312577ba207f0acd8df8048d80db8206a01af",
  "share": "population",
  "sheet": "2015-2016",
  "source": "BBSR Umsteigeschluessel Kreise",
  "to_year": 2016,
  "url": "https://www.bbsr.bund.de/.../ref-kreise-1990-2024.xlsx?__blob=publicationFile&v=2"
}
```

## `<key>__nuts2024` (`AgsToNutsFeature`)

Maps AGS keys through the pinned Eurostat LAU-to-NUTS crosswalk
(`mloda_plugin_govdata/feature_groups/harmonization/core/nuts.py`). The NUTS version is part of the name
(or the `nuts_version` option) and must be the cached crosswalk's
(`load_nuts_crosswalk(cache, revalidate=True)` once). Kreis keys retired before the crosswalk's
Gebietsstand resolve through the GV-ISys change files named in `AgsToNutsFeature.history_years` (the
pinned year, fetched once with `load_gv_isys_changes(year, cache, revalidate=True)`); Land keys are out
of scope.

| Option | Meaning |
| --- | --- |
| `nuts_version` | `2024`; required in the configuration-based form |
| `nuts_on_unmatched` | `raise` (default) or `flag` (null codes, the reason in `~unmatched`) |

Output, row-aligned with the input: `~key`, `~nuts1`, `~nuts2`, `~nuts3`, `~version`, `~unmatched`.

## `<time>__year_period` (`AnnualPeriodFeature`)

Turns a time column into the annual period start as `date32`: an integer year, a GENESIS JAHR or STAG
label, or a date on the 31 December reference date. A date inside the year (a 30 June Stichtag, an
election date) is refused: the year a snapshot joins to is chosen where the join is defined (see
`stichtag_period` in [recipes](recipes.md)), not here. `period_freq` is `year`; quarter and month are not built.

## Over other readers

`DestatisReader` leaves chained and `~part` names to these groups. The other readers claim any name their option
key is set for, so a harmonized feature over them names its group: `Feature("Stichtag__year_period",
options={StuttgartPopulationReader.__name__: slug}, feature_group=AnnualPeriodFeature)`.
