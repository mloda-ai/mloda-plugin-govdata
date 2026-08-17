"""GovData connector: read German open-government data into mloda."""

from .bundeswahlleiterin import (
    OPTION_WAHL_HEADER_ROWS,
    OPTION_WAHL_LABEL_COLUMNS,
    OPTION_WAHL_SKIPROWS,
    OPTION_WAHL_VALUE_TYPE,
    BundeswahlleiterinReader,
)
from .core.client import build_client
from .core.discovery import (
    Dataset,
    ResolvedDistribution,
    Resource,
    normalize_license,
    resolve_distribution,
    search_datasets,
)
from .core.locator import GovDataLocator
from .core.parse import ColumnType, parse_german_csv, parse_german_csv_bytes, parse_multi_header_csv
from .feature import GovDataFeature
from .population import POPULATION_SCHEMA, POPULATION_SLUG, StuttgartPopulationReader
from .reader import BaseGovDataReader, GovDataReader
from .uba import (
    OPTION_UBA_COMPONENT,
    OPTION_UBA_DATE_FROM,
    OPTION_UBA_DATE_TO,
    OPTION_UBA_LANG,
    OPTION_UBA_SCOPE,
    OPTION_UBA_STATION,
    OPTION_UBA_TIME_FROM,
    OPTION_UBA_TIME_TO,
    UBA_AIR_BASE,
    UbaAirReader,
    parse_uba_measures,
    parse_uba_measures_bytes,
    uba_measures_url,
)

__all__ = [
    "OPTION_UBA_COMPONENT",
    "OPTION_UBA_DATE_FROM",
    "OPTION_UBA_DATE_TO",
    "OPTION_UBA_LANG",
    "OPTION_UBA_SCOPE",
    "OPTION_UBA_STATION",
    "OPTION_UBA_TIME_FROM",
    "OPTION_UBA_TIME_TO",
    "OPTION_WAHL_HEADER_ROWS",
    "OPTION_WAHL_LABEL_COLUMNS",
    "OPTION_WAHL_SKIPROWS",
    "OPTION_WAHL_VALUE_TYPE",
    "POPULATION_SCHEMA",
    "POPULATION_SLUG",
    "UBA_AIR_BASE",
    "BaseGovDataReader",
    "BundeswahlleiterinReader",
    "ColumnType",
    "Dataset",
    "GovDataFeature",
    "GovDataLocator",
    "GovDataReader",
    "ResolvedDistribution",
    "Resource",
    "StuttgartPopulationReader",
    "UbaAirReader",
    "build_client",
    "normalize_license",
    "parse_german_csv",
    "parse_german_csv_bytes",
    "parse_multi_header_csv",
    "parse_uba_measures",
    "parse_uba_measures_bytes",
    "resolve_distribution",
    "search_datasets",
    "uba_measures_url",
]
