"""Write the shipped recipe files from their definitions below, the source of truth (repo tooling, not shipped),
and each recipe's plan lock under ``locks/``.

Usage:
    uv run python scripts/write_recipes.py [--out DIR]
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mloda.steward import write_plan_lock
from mloda.user import Feature, Link, Options, ParallelizationMode, PlanStep, mloda

from mloda_plugin_govdata.feature_groups.destatis import DestatisReader
from mloda_plugin_govdata.feature_groups.govdata import (
    OPTION_UBA_COMPONENT,
    OPTION_UBA_DATE_FROM,
    OPTION_UBA_DATE_TO,
    OPTION_UBA_SCOPE,
    OPTION_UBA_STATION,
    POPULATION_SLUG,
    BundeswahlleiterinReader,
    StuttgartPopulationReader,
    UbaAirReader,
    uba_measures_url,
)
from mloda_plugin_govdata.feature_groups.govdata.core.discovery import CC_BY_4_0, DL_DE_BY_2_0
from mloda_plugin_govdata.feature_groups.govdata.uba import UBA_LICENSE
from mloda_plugin_govdata.feature_groups.harmonization.core.reference.sources import BBSR_KREISE
from mloda_plugin_govdata.feature_groups.land_population_per_voter import (
    BTW25_ELECTION_DATE,
    LAND_LINK,
    LAND_LOCATOR,
    LAND_YEAR,
)
from mloda_plugin_govdata.recipes import Compliance, LoadedRecipe, SourceCompliance, load_recipe, write_recipe

RECIPES_DIR = Path(__file__).resolve().parents[1] / "recipes"
DESTATIS_ATTRIBUTION = "(c) Statistisches Bundesamt (Destatis), 2026"
DESTATIS_MODIFICATIONS = [
    "ffcsv reply parsed into a typed table; the raw value sign is kept in value_marker",
    "time normalized to the calendar year of the Stichtag",
]
KERG_URL = "https://www.bundeswahlleiterin.de/bundestagswahlen/2025/ergebnisse/opendata/btw25/csv/kerg.csv"
STUTTGART_URL = (
    "https://opendata.stuttgart.de/dataset/85a06c70-d65e-46fd-861b-2de52c008579/resource/"
    "2842140d-8787-475d-b1b9-35a496b503e3/download/einwohner-in-stuttgart-nach-altersgruppen-und-stadtbezirken-seit-1986.csv"
)
UBA_URL = uba_measures_url(station=143, component=3, scope=2, date_from="2025-01-01", date_to="2025-01-01")
UBA_OPTIONS: dict[str, Any] = {
    UbaAirReader.__name__: True,
    OPTION_UBA_STATION: 143,
    OPTION_UBA_COMPONENT: 3,
    OPTION_UBA_SCOPE: 2,
    OPTION_UBA_DATE_FROM: "2025-01-01",
    OPTION_UBA_DATE_TO: "2025-01-01",
}

CONFIGURATION_BASED_NAME = "destatis__bevoelkerung__kreise"
GOETTINGEN_KEYS = ["03152", "03156", "03159"]
GOETTINGEN: dict[str, Any] = {
    "name": "12411-0015",
    "regionalvariable": "KREISE",
    "regionalkey": GOETTINGEN_KEYS,
    "startyear": 2013,
    "endyear": 2017,
}
FOREIGNERS: dict[str, Any] = {**GOETTINGEN, "name": "12521-0040"}
REBASE = {"rebase_from_year": 2015, "rebase_to_year": 2016}

GOETTINGEN_SHA256 = "39e590f654fd92f20306ef5a52ed59ef04bb757b1331e5216df2cfafcddd7411"
FOREIGNERS_SHA256 = "d678a529575b6f550d44b403d260a25eeccdba8ca4178e465d1778dee35b4023"
LAND_SHA256 = "aba0f99e3b8eef1f4d975c0e2ed3d7323024dd8a798dbd875e35ae34447f3916"
KERG_SHA256 = "31ab27391d5753a6a972936d436092879f5c9cca11570272cd72e3e272d16731"
STUTTGART_SHA256 = "f3c190288370eb3e4421eaed9d996aa157ee0f710cb382ef10ea1a07fde899e3"
UBA_SHA256 = "befda29b594c110d5f982dc41e2fe83ead231dbbec4baa99735c02db1e9a321d"

VOTERS = "Wahlberechtigte Erststimmen Endgültig"
CSU_ZWEITSTIMMEN = "Christlich-Soziale Union in Bayern e.V. Zweitstimmen Endgültig"
UEBRIGE_VORPERIODE = "Übrige Erststimmen Vorperiode"
KEY = "1_variable_attribute_code"


@dataclass(frozen=True)
class ShippedRecipe:
    file: str
    features: list[Feature]
    compliance: Compliance
    links: list[Link] = field(default_factory=list)


def _at(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _destatis(table: str, retrieved_at: datetime, sha256: str, *extra: str) -> SourceCompliance:
    statistic = table.split("-")[0]
    return SourceCompliance(
        license=DL_DE_BY_2_0,
        attribution=DESTATIS_ATTRIBUTION,
        dataset_uri=f"https://genesis.destatis.de/datenbank/online/statistic/{statistic}/table/{table}",
        retrieved_at=retrieved_at,
        sha256=sha256,
        modifications=[*DESTATIS_MODIFICATIONS, *extra],
        credential_env=["GENESIS_TOKEN"],
    )


def _destatis_features(locator: dict[str, Any], *names: str) -> list[Feature]:
    return [Feature(name, options={DestatisReader.__name__: locator}) for name in names]


KERG_SOURCE = SourceCompliance(
    license=DL_DE_BY_2_0,
    attribution="(c) Die Bundeswahlleiterin, Wiesbaden 2025",
    dataset_uri=KERG_URL,
    retrieved_at=_at(2026, 9, 12),
    sha256=KERG_SHA256,
    modifications=["three-row merged header flattened to one column name per measure", "vote counts read as integers"],
)

KREIS_POPULATION_REBASED = ShippedRecipe(
    "kreis_population_rebased.json",
    [
        Feature(
            CONFIGURATION_BASED_NAME,
            Options(group={DestatisReader.__name__: GOETTINGEN, **REBASE}, context={"in_features": "value"}),
        )
    ],
    Compliance(
        sources=[
            _destatis(
                "12411-0015",
                _at(2026, 9, 12),
                GOETTINGEN_SHA256,
                "re-based onto the 31.12.2016 Gebietsstand with the BBSR key sheet 2015-2016; every row carries its "
                "flag, source keys, issues, and the key-sheet provenance",
            ),
            SourceCompliance(
                license=BBSR_KREISE.license,
                attribution=BBSR_KREISE.attribution,
                dataset_uri=BBSR_KREISE.url,
                retrieved_at=_at(2026, 9, 24),
                sha256=BBSR_KREISE.sha256 or "",
                modifications=["sheet 2015-2016 read; population-proportional shares applied to the source keys"],
            ),
        ],
        notes=(
            "Fortschreibung des Bevölkerungsstandes on the Zensus 2011 base throughout 2013 to 2017, no census "
            "break inside the range. The Landkreise Göttingen (03152) and Osterode am Harz (03156) merged into the "
            "Landkreis Göttingen (03159) on 01.11.2016: before that Stichtag 03159 carries '-' (not applicable, "
            "never a zero) and its 2013 to 2015 rows are re-based sums of the two feeders. The BBSR key file must "
            "be in the cache: load_bbsr_kreise(cache, revalidate=True) once."
        ),
    ),
)

KREIS_FOREIGNERS_SHARE = ShippedRecipe(
    "kreis_foreigners_share.json",
    [
        *_destatis_features(
            FOREIGNERS, KEY, "2_variable_attribute_code", "2_variable_attribute_label", "time", "value", "value_marker"
        ),
        *_destatis_features(GOETTINGEN, KEY, "time", "value", "value_marker"),
    ],
    Compliance(
        sources=[
            _destatis("12521-0040", _at(2026, 9, 12), FOREIGNERS_SHA256),
            _destatis("12411-0015", _at(2026, 9, 12), GOETTINGEN_SHA256),
        ],
        notes=(
            "Rate with denominator: Ausländer (BEV027) over Bevölkerungsstand (BEVSTD) per Kreis and Stichtag, the "
            "same three Göttingen keys and years as the re-basing recipe, so both sides carry '-' for a key outside "
            "its validity: the parser reads it as 0 with value_marker '-', a genuine count has an empty marker, so "
            "a consumer checks the marker before dividing. The foreigners table breaks down by "
            "sex: the total rows have an empty 2_variable_attribute_code and the label Insgesamt, GESM and GESW are "
            "the parts. The two selections come back as two frames; dividing is a consumer's job."
        ),
    ),
)

LAND_POPULATION_PER_VOTER = ShippedRecipe(
    "land_population_per_voter.json",
    [
        *_destatis_features(LAND_LOCATOR, KEY, "1_variable_attribute_label", "time", "value", "value_marker"),
        *(
            Feature(name, options={BundeswahlleiterinReader.__name__: KERG_URL})
            for name in ("Nr", "Gebiet", "gehört zu", VOTERS, CSU_ZWEITSTIMMEN)
        ),
    ],
    Compliance(
        sources=[_destatis("12411-0010", _at(2026, 9, 8), LAND_SHA256), KERG_SOURCE],
        notes=(
            "Population per eligible voter by Land. Join year: an election joins the last Destatis Stichtag on or "
            f"before its date, so the Bundestagswahl of {BTW25_ELECTION_DATE.strftime('%d.%m.%Y')} joins the "
            f"population of 31.12.{LAND_YEAR} (time = {LAND_YEAR}). "
            "The kerg Land rows (gehört zu = 99) carry the AGS-2 in Nr, which equals the Destatis DLAND code, so "
            "the join needs no name mapping; check the names on both sides with "
            "mloda_plugin_govdata.feature_groups.harmonization.core.land_codes. A party column is empty where the "
            "party was not on the ballot (the CSU outside Bayern), which is not a zero. The links block lets a "
            "consumer FeatureGroup needing a column from each side join them "
            "(mloda_plugin_govdata.feature_groups.land_population_per_voter.LandPopulationPerVoter is one); "
            "requesting this recipe's own raw features returns them unjoined, one frame per source. "
            "kerg.csv re-fetched on 2026-09-12: unchanged since the first capture."
        ),
    ),
    [LAND_LINK],
)

LAND_POPULATION = ShippedRecipe(
    "land_population.json",
    _destatis_features(LAND_LOCATOR, KEY, "value"),
    Compliance(
        sources=[_destatis("12411-0010", _at(2026, 9, 8), LAND_SHA256)],
        notes=f"Fortschreibung des Bevölkerungsstandes, Stichtag {LAND_YEAR}-12-31, all 16 Länder (DLAND 01 to 16).",
    ),
)

STUTTGART_POPULATION = ShippedRecipe(
    "stuttgart_population.json",
    [
        Feature(name, options={StuttgartPopulationReader.__name__: POPULATION_SLUG})
        for name in ("Stichtag", "Stadtbezirk", "Alter in 10 Gruppen", "Einwohner")
    ],
    Compliance(
        sources=[
            SourceCompliance(
                license=CC_BY_4_0,
                attribution="Statistisches Amt der Landeshauptstadt Stuttgart",
                dataset_uri=STUTTGART_URL,
                retrieved_at=_at(2026, 9, 12),
                sha256=STUTTGART_SHA256,
                modifications=["German CSV parsed into a typed table: Stichtag as a date, Einwohner as an integer"],
            )
        ],
        notes=(
            "Residents by age group and city district since 1986 (GovData dataset "
            f"{POPULATION_SLUG}, distribution resolved through CKAN). The Stichtag is 30 June; which annual "
            "period a mid-year Stichtag joins to is not decided here."
        ),
    ),
)

BUNDESTAGSWAHL_2025 = ShippedRecipe(
    "bundestagswahl_2025.json",
    [
        Feature(name, options={BundeswahlleiterinReader.__name__: KERG_URL})
        for name in (
            "Nr",
            "Gebiet",
            "gehört zu",
            VOTERS,
            "Wählende Erststimmen Endgültig",
            "Gültige Stimmen Zweitstimmen Endgültig",
            CSU_ZWEITSTIMMEN,
            UEBRIGE_VORPERIODE,
        )
    ],
    Compliance(
        sources=[KERG_SOURCE],
        notes=(
            "Amtliches Endergebnis of the Bundestagswahl 2025. Wahlkreis rows carry a three-digit Nr and their Land "
            "in gehört zu, Land rows have gehört zu = 99, the Bundesgebiet row has Nr 99. An empty vote cell means "
            "the party was not on the ballot there and stays null; Übrige is 0 where no other candidates ran. "
            "Re-fetched on 2026-09-12: unchanged since the first capture on 2026-09-08."
        ),
    ),
)

UBA_OZONE_STATION_143 = ShippedRecipe(
    "uba_ozone_station_143.json",
    [Feature(name, options=UBA_OPTIONS) for name in ("station_id", "date_start", "value", "index")],
    Compliance(
        sources=[
            SourceCompliance(
                license=UBA_LICENSE,
                attribution="Umweltbundesamt, Luftdaten API v4",
                dataset_uri=UBA_URL,
                retrieved_at=_at(2026, 8, 16),
                sha256=UBA_SHA256,
                modifications=[
                    "JSON flattened to one row per station and hour; value as a float, ids and index as integers"
                ],
            )
        ],
        notes=(
            "Hourly ozone (component 3, scope 2) at station 143 on 2025-01-01. The endpoint re-serves revised "
            "values: a re-fetch on 2026-09-12 differed from the pinned payload in most hours by one unit, so the "
            "sha256 identifies this retrieval, not the series. Licensed under the UBA data terms (§ 12a EGovG), "
            "attribution required."
        ),
    ),
)

RECIPES: tuple[ShippedRecipe, ...] = (
    KREIS_POPULATION_REBASED,
    KREIS_FOREIGNERS_SHARE,
    LAND_POPULATION_PER_VOTER,
    LAND_POPULATION,
    STUTTGART_POPULATION,
    BUNDESTAGSWAHL_2025,
    UBA_OZONE_STATION_143,
)


def recipe_plan(recipe: LoadedRecipe) -> list[PlanStep]:
    """The plan of the documented run call (PyArrowTable, run_all's SYNC mode), without running it."""
    return mloda.explain(
        recipe.features,
        compute_frameworks=["PyArrowTable"],
        links=set(recipe.links),
        parallelization_modes={ParallelizationMode.SYNC},
    )


def lock_path(recipes_dir: Path, file: str) -> Path:
    return recipes_dir / "locks" / file


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--out", type=Path, default=RECIPES_DIR, help="output directory (default: the repo-root recipes/)"
    )
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    for recipe in RECIPES:
        path = write_recipe(args.out / recipe.file, recipe.features, recipe.compliance, recipe.links)
        print(path)
        lock = lock_path(args.out, recipe.file)
        write_plan_lock(recipe_plan(load_recipe(path)), lock)
        print(lock)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
