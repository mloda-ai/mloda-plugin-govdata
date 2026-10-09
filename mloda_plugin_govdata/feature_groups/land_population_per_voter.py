"""The consumer FeatureGroup a same-class ``GovDataFeature`` link needs: mloda executes such a join
only when a consumer needs a column from each side."""

from __future__ import annotations

from datetime import date
from typing import Any, ClassVar

import pyarrow as pa
import pyarrow.compute as pc
from mloda.provider import ComputeFramework, FeatureGroup, FeatureSet
from mloda.user import Feature, FeatureName, JoinSpec, Link, Options
from mloda.user.pyarrow import PyArrowTable

from .destatis.core.period import stichtag_period
from .destatis.reader import DestatisReader
from .govdata.bundeswahlleiterin import BundeswahlleiterinReader
from .govdata.feature import GovDataFeature
from .harmonization.core.land_codes import land_name

# GENESIS-Online 12411-0010 (Bevölkerung nach Ländern) at the last Stichtag on or before the
# Bundestagswahl 2025 (btw25) election day, joined with its kerg.csv.
BTW25_ELECTION_DATE = date(2025, 2, 23)
LAND_YEAR = stichtag_period(BTW25_ELECTION_DATE).start.year
LAND_LOCATOR = {"name": "12411-0010", "startyear": LAND_YEAR, "endyear": LAND_YEAR}
KERG_URL = "https://www.bundeswahlleiterin.de/bundestagswahlen/2025/ergebnisse/opendata/btw25/csv/kerg.csv"
VOTERS = "Wahlberechtigte Erststimmen Endgültig"
PARTS: tuple[str, ...] = ("code", "land", "population", "voters", "value")

LAND_LINK = Link.inner(
    JoinSpec(GovDataFeature, "1_variable_attribute_code"),
    JoinSpec(GovDataFeature, "Nr"),
    left_discriminator={DestatisReader.__name__: LAND_LOCATOR},
    right_discriminator={BundeswahlleiterinReader.__name__: KERG_URL},
)


class LandPopulationPerVoter(FeatureGroup):
    """Population per eligible voter by Land, joined on the DLAND / ``Nr`` Land codes.

    Pinned to one GENESIS-Online table and one kerg file (``LAND_LOCATOR``, ``KERG_URL``); not
    parameterized by year or election. One row per Land, sorted by AGS-2 code: ``~code``, ``~land``
    (the name, from ``harmonization.core.land_codes``), ``~population``, ``~voters``, and the computed
    ``~value``. The population input carries ``LAND_LINK``, so ``mloda.run_all`` needs no ``links=`` for it.
    """

    NAME: ClassVar[str] = "land_population_per_voter"

    @classmethod
    def compute_framework_rule(cls) -> set[type[ComputeFramework]] | None:
        return {PyArrowTable}

    @classmethod
    def feature_names_supported(cls) -> set[str]:
        return {cls.NAME}

    def input_features(self, options: Options, feature_name: FeatureName) -> set[Feature] | None:
        return {
            Feature("value", options={DestatisReader.__name__: LAND_LOCATOR}, link=LAND_LINK),
            Feature(VOTERS, options={BundeswahlleiterinReader.__name__: KERG_URL}),
        }

    @classmethod
    def calculate_feature(cls, data: Any, features: FeatureSet) -> Any:
        order = pc.sort_indices(data.column("1_variable_attribute_code"))
        codes = data.column("1_variable_attribute_code").take(order)
        population = pc.cast(data.column("value"), "float64").take(order)
        voters = pc.cast(data.column(VOTERS), "float64").take(order)
        land = pa.array([land_name(code) for code in codes.to_pylist()], pa.string())
        return pa.table(
            {
                f"{cls.NAME}~code": codes,
                f"{cls.NAME}~land": land,
                f"{cls.NAME}~population": population,
                f"{cls.NAME}~voters": voters,
                f"{cls.NAME}~value": pc.divide(population, voters),
            }
        )
