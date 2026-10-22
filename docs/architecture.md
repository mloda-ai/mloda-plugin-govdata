# Architecture

How the packages fit together and where to start reading for a change. Paths are relative to
`mloda_plugin_govdata/` unless they start at the repository root.

## Packages

| Path | Holds |
| --- | --- |
| `feature_groups/govdata/` | The root `GovDataFeature`, `BaseGovDataReader`, and the GET readers (GovData CKAN, Bundeswahlleiterin `kerg.csv`, UBA Air Data JSON). `core/` is the shared plumbing: HTTP client, download cache, CKAN discovery, locator, CSV parsing, provenance. |
| `feature_groups/destatis/` | `DestatisReader` and `DestatisLocator` for GENESIS tables. `core/` holds the POST client, credentials, reply envelope, parameter-keyed cache, the ffcsv parser, and the JAHR/STAG time-label model (`period.py`). |
| `feature_groups/harmonization/` | The chained FeatureGroups on `HarmonizationFeature`: `value__rebased`, `<key>__nuts2024`, `<time>__year_period`. `core/` holds the logic behind the re-basing and NUTS groups (keys, NUTS crosswalk, NUTS mapping, re-basing) and the Land codes `land_population_per_voter.py` uses; `core/reference/` holds the BBSR, GV-ISys and Eurostat loaders. `<time>__year_period` wraps the Destatis time-label model. |
| `feature_groups/land_population_per_voter.py` | `LandPopulationPerVoter`, the consumer FeatureGroup that makes mloda run the Land-level join of a Destatis table and `kerg.csv`. |
| `recipes/` | The recipe model, JSON load and write, the credential scan, `frames_by_column`. |
| `recipes/*.json` (repository root) | The shipped recipe files, generated from their definitions in the repository-root `scripts/write_recipes.py`. |
| `recipes/locks/*.json` (repository root) | One mloda plan lock per shipped recipe, written by the same script. |

## Dependency direction

Each entry imports only from entries before it:

1. `feature_groups/govdata/core/`
2. the GovData readers and `GovDataFeature`
3. `feature_groups/destatis/` (the reader base and the shared core)
4. `feature_groups/harmonization/core/` (the shared download cache only)
5. the harmonization FeatureGroups (their `core/`, the shared cache, the Destatis credential option and
   time-label model)
6. `feature_groups/land_population_per_voter.py` (`GovDataFeature`, the readers, `core/land_codes.py`)
7. the `recipes` package, which imports every FeatureGroup package to register it; the JSON files are data it
   loads by path

Importing a `core/` module runs its parent package's `__init__.py` first, so importing anything under
`feature_groups/harmonization/core/` also loads and registers the harmonization FeatureGroups. A
fresh-interpreter test in `feature_groups/destatis/tests/test_reader.py` checks that importing the Destatis
reader loads nothing outside entries 1 to 3.

## mloda mechanisms

- **Reader selection by option key.** `GovDataFeature` is the one root FeatureGroup and `BaseGovDataReader`
  its input data, so every reader, `DestatisReader` included, is a sibling under it. A feature picks its
  reader with an option keyed by the reader class or its class name; the value is what the reader's locator
  coerces. Guide: [input-data readers](https://github.com/mloda-ai/mloda-registry/blob/main/docs/guides/feature-group-patterns/27-input-data-readers.md).
- **`__` chaining.** The harmonization groups use `FeatureChainParserMixin`: `value__rebased` names the
  source column and the operation; the configuration-based form carries the source in `in_features`. The
  reader option on the chained feature is forwarded to its source column. Only `DestatisReader` declines
  chained names, so a chained feature over another reader names its group (see
  [harmonization.md](harmonization.md#over-other-readers)). Guides: [chained features](https://github.com/mloda-ai/mloda-registry/blob/main/docs/guides/feature-group-patterns/03-chained-features.md),
  [input feature forwarding](https://github.com/mloda-ai/mloda-registry/blob/main/docs/guides/feature-group-patterns/26-input-feature-forwarding.md).
- **`~` multi-output columns.** A result with several parts comes back as `<name>~<part>` columns
  (`value__rebased~key`, `value__rebased~flag`). Request one part alone, or chain onto a part
  (`value__rebased~key__nuts2024`). `LandPopulationPerVoter` returns the same shape. Every name form:
  [harmonization.md](harmonization.md#feature-names). Guide:
  [multi-output features](https://github.com/mloda-ai/mloda-registry/blob/main/docs/guides/feature-group-patterns/05-multi-output-features.md).

## Where to start

- **Add a reader:** [adding-a-reader.md](adding-a-reader.md), then `feature_groups/govdata/reader.py`.
- **Add a harmonization:** the logic goes in `feature_groups/harmonization/core/` and returns new rows, never
  a mutated input, with its reference-data provenance as data and what it could not use as structured issues;
  it raises by default when the output would be wrong, with a policy option to flag instead. The wrapper is a
  `HarmonizationFeature` subclass in `feature_groups/harmonization/` (model it on `nuts.py`, which wraps
  `core/nuts.py`), exported from that package's `__init__.py`, since importing it is what registers it.
  Document it in [harmonization.md](harmonization.md).
- **Add a recipe:** [recipes.md](recipes.md). Add its definition to `RECIPES` in the repository-root `scripts/write_recipes.py`
  and run `uv run python scripts/write_recipes.py`; `recipes/tests/test_shipped.py` pins each file to its
  definition and its plan to its lock, and fails on a file under the root `recipes/` that has none.

## Outside the wheel

The wheel ships code only: no package data and no `tests` packages.

- **Reference tables** (BBSR, GV-ISys, Eurostat) are third-party files (dl-de/by-2-0, CC BY 4.0); the
  Eurostat LAU-to-NUTS file alone is about 20 MB. A bundled subset would answer for the keys it holds and
  report every other key as unmatched, indistinguishable from a real gap. Each is fetched once with its group's
  `fetch_reference()` (`KreisRebaseFeature.fetch_reference()` and the like), checked against its pinned sha256
  where `core/reference/sources.py` has one (a body with another hash is refused, never cached), and read
  offline afterwards; `calculate_feature` never fetches and raises with that call on an empty cache. Tests read
  small extracts in `feature_groups/harmonization/core/reference/tests/fixtures/`, each source and license
  named in the `NOTICE` there.
- **Recipes** are data, not library code: each pins the payload sha256 and retrieval time of one run, and
  `load_recipe` takes a path, so they live in the repository to copy and run from a checkout.
