# Recipes

A recipe is one JSON file naming the features a run needs, the joins between them, and where the data
came from. `load_recipe(path)` returns the mloda feature list, the `Link` objects, and the compliance
block; `write_recipe` produces the file from Python objects.

```python
from mloda.user import mloda
from mloda_plugin_govdata.recipes import load_recipe

recipe = load_recipe("recipes/land_population.json")
result = mloda.run_all(recipe.features, compute_frameworks=["PyArrowTable"], links=set(recipe.links))
recipe.compliance.sources[0].attribution  # what to print next to the result
```

## File shape

```json
{
  "features": [
    {"name": "value", "options": {"DestatisReader": {"name": "12411-0010", "startyear": 2024, "endyear": 2024}}},
    {"name": "Nr", "options": {"BundeswahlleiterinReader": "https://www.bundeswahlleiterin.de/.../kerg.csv"}}
  ],
  "links": [
    {
      "join": "inner",
      "left": {"feature_group": "GovDataFeature", "index": ["1_variable_attribute_code"],
               "discriminator": {"DestatisReader": {"name": "12411-0010", "startyear": 2024, "endyear": 2024}}},
      "right": {"feature_group": "GovDataFeature", "index": ["Nr"],
                "discriminator": {"BundeswahlleiterinReader": "https://www.bundeswahlleiterin.de/.../kerg.csv"}}
    }
  ],
  "compliance": {
    "sources": [
      {
        "license": "DL-DE-BY-2.0",
        "attribution": "(c) Statistisches Bundesamt (Destatis), 2026",
        "dataset_uri": "https://genesis.destatis.de/datenbank/online/statistic/12411/table/12411-0010",
        "retrieved_at": "2026-09-08T00:00:00Z",
        "sha256": "aba0f99e3b8eef1f4d975c0e2ed3d7323024dd8a798dbd875e35ae34447f3916",
        "modifications": ["ffcsv reply parsed into a typed table"],
        "credential_env": ["GENESIS_TOKEN"]
      }
    ],
    "notes": "optional: census breaks, caveats"
  }
}
```

- `features`: mloda's feature-config array, handed to `load_features_from_config` unchanged. Items are
  feature names or objects with `name`, `options` (or `group_options` plus `context_options`),
  `in_features`, `propagate_context_keys`, `column_index`, `feature_group` (a class name). Reader locators
  are strings or dicts (the `DestatisLocator` dict form). Any other key fails at load with the allowed set.
- `links`: joins the feature array cannot express. `join` is `inner`, `left`, `right`, `outer`, `append`,
  or `union`; each side names the FeatureGroup class, its key columns, and, when both sides share a class,
  a `discriminator` of option key/value pairs picking the node. mloda matches a discriminator by exact
  equality with the feature's option value, so use the same locator form on both sides. Two links that
  differ only by their discriminators stay distinct, so both can be in one recipe's `links` block.
- `compliance.sources`: one entry per data source with `license`, `attribution`, `dataset_uri`,
  `retrieved_at` (timezone-aware), the payload `sha256`, `modifications` (what the reader changes; dl-de/by-2-0
  requires marking changes), and `credential_env` (the env-var names of the source's default credential path,
  never values; a GENESIS source names `GENESIS_TOKEN`, the user plus password pair from
  [credentials.md](credentials.md) works the same).

## What round-trips

The writer covers the option values this plugin produces: strings, finite numbers, booleans, lists, dicts,
a `DestatisLocator` (its dict form, `None` fields omitted), a `GovDataLocator` with default `ckan_base` and
`resource_index` and one of slug or URL (that string), `in_features` (in the given order; a set is sorted),
the `feature_group` scope, and `propagate_context_keys`. Anything else raises instead of being dropped: a
tuple or set value (pass a list), a `Feature` with `data_type`, `index`, `initial_requested_data`,
`required_declarations`, a forwarding directive, or a
`compute_framework` set through the constructor that differs from the options, a nested `Feature` inside
`in_features`, or an `asof` link. A `domain`, from the constructor or the options, is written to the `domain`
option key, which mloda reads back. A link set on a `Feature` is hoisted into `links`. The writer runs its
output through the loader, so it never writes a file `load_recipe` refuses.

## Credentials never go in a recipe

Validation rejects a credential-named key anywhere (`username`, `password`, `token`, `genesis_credentials`,
`user`, `auth`, ...), a token-shaped value or key (24 or more letters and digits with no separator; the
GENESIS token is one such run; only the compliance `sha256` field is exempt), a URL with `user:password@`
in front of the host, an entry in `credential_env` that is not an env-var name, and any value of the
process's own `GENESIS_*` or `REGIONALSTATISTIK_*` token and password variables found in the file (a user
name too, when it carries a digit or `@`). Errors raised by `load_recipe`, `parse_recipe`, and
`build_recipe` name the location, never the value. Credentials resolve from the environment at run time;
see [credentials.md](credentials.md).

## Where recipe files live

Repo-root `recipes/`, outside the wheel: the package ships code only (no tests, no recipe files), the same
policy as the reference tables in the harmonization package. The shipped files are listed below.

## Plan locks

`recipes/locks/` holds one mloda plan lock per shipped recipe: the feature group, compute framework and reader
of each step that the documented call (`compute_frameworks=["PyArrowTable"]`) resolves to. The offline tests
fail with a diff when a plan changes, a mloda upgrade included. Regenerate the recipes and locks with
`uv run python scripts/write_recipes.py` and review the lock diff before committing.

## Shipped recipes

| File | Reads | Scenario |
| --- | --- | --- |
| `kreis_population_rebased.json` | GENESIS-Online `12411-0015`, Kreise 03152, 03156, 03159, 2013 to 2017, plus the BBSR key file | the re-based series as `destatis__bevoelkerung__kreise` (a configuration-based name with `in_features` and the re-basing options) |
| `kreis_foreigners_share.json` | GENESIS-Online `12521-0040` and `12411-0015`, same keys and years | a rate with its denominator; two selections, two frames |
| `land_population_per_voter.json` | GENESIS-Online `12411-0010` and the Bundeswahlleiterin `kerg.csv` | population per eligible voter by Land, the links block on `1_variable_attribute_code` = `Nr` |
| `land_population.json` | GENESIS-Online `12411-0010` | the 16 Land rows |
| `stuttgart_population.json` | GovData CSV via CKAN | residents by age group and district |
| `bundestagswahl_2025.json` | Bundeswahlleiterin `kerg.csv` | the merged-header election file |
| `uba_ozone_station_143.json` | UBA Air Data JSON | hourly ozone at one station |

The re-based recipe needs the BBSR key file in the cache (`load_bbsr_kreise(cache, revalidate=True)`
once). Running the Land recipe's own features returns them unjoined, one frame per source;
`frames = frames_by_column(result)` picks a PyArrow frame by a column only it carries (`frames["value"]`,
`frames["Nr"]`) and raises on a shared one, so for `kreis_foreigners_share.json`, whose two frames carry
the same columns, iterate `result.frames()` instead. Check the Land names on each side with
`feature_groups.harmonization.core.land_codes.check_land_names`. The links block lets a consumer
FeatureGroup that needs a column from each side join them instead (mloda executes a join only for such a
consumer); `feature_groups.land_population_per_voter.LandPopulationPerVoter` is one, computing population
per voter; its population input carries the link, so it also runs without `links=`.
An election joins the last Destatis 31 December Stichtag on or before its date
(`feature_groups.destatis.core.period.stichtag_period`): the Bundestagswahl of 23.02.2025 joins the population of 31.12.2024,
and the recipe's `time` column shows that year.
A `-` in a GENESIS cell arrives as 0 with the sign kept in
`value_marker`; only the harmonization step, which knows the validity windows, turns it into not applicable,
so a consumer of raw columns reads the marker before taking a 0 as a count. Each recipe except
`land_population.json` has a test pinning its zero-versus-missing case, and each pins the sha256 of the payload
it was run against (the kerg and Stuttgart files are too large to commit; a `live`-marked test checks their pins
against the source).

The definitions in `scripts/write_recipes.py` are the source of truth: edit a definition, never the JSON, and
regenerate every file with `uv run python scripts/write_recipes.py`. A test fails on a file that differs from
its definition or has none.

The demo notebook (`demos/govdata_demo.py`) runs `land_population_per_voter.json` and `kreis_population_rebased.json`
live, with the attribution lines and change markers from their compliance blocks.
