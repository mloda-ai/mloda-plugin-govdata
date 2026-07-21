"""GovData connector: read German open-government data into mloda."""

from .bundeswahlleiterin import BundeswahlleiterinReader
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
from .uba import UBA_AIR_BASE, UbaAirReader, parse_uba_measures, parse_uba_measures_bytes, uba_measures_url

__all__ = [
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
    "Resource",
    "ResolvedDistribution",
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
