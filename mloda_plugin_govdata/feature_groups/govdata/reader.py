"""Base mloda reader for GovData distributions.

``BaseGovDataReader`` follows the ``CsvReader`` pattern (a ``ReadFile`` subclass):
it resolves a locator to a distribution, downloads it through the cache, and lets
the subclass parse the payload into a typed Arrow table. One module per data
source implements ``_parse``; ``GovDataReader`` is the generic single-header
German-CSV reader.
"""

from __future__ import annotations

import difflib
import tempfile
from pathlib import Path
from typing import Any, ClassVar

import pyarrow as pa

from mloda.provider import FeatureSet

# Imported for its registration side effect so "PyArrowTable" resolves; the reader returns a pyarrow Table.
# Public path since mloda 0.10.0 (lazy export); resolving it imports and registers the framework class.
from mloda.user import PyArrowTable  # noqa: F401
from mloda_plugins.feature_group.input_data.read_file import ReadFile

from .core.cache import DownloadCache
from .core.client import build_client
from .core.discovery import ResolvedDistribution, resolve_distribution
from .core.locator import GovDataLocator
from .core.parse import ColumnType, parse_german_csv


def _unknown_features_message(missing: list[str], available: list[str], locator: GovDataLocator) -> str:
    """Name the missing features, list what the distribution offers, and suggest close matches."""
    target = locator.dataset_id or locator.distribution_url
    parts = [
        f"Unknown feature(s) {', '.join(repr(name) for name in missing)} for {target!r}.",
        f"Available: {', '.join(sorted(available))}.",
    ]
    for name in missing:
        close = difflib.get_close_matches(name, available, n=1)
        if close:
            parts.append(f"Did you mean {close[0]!r} instead of {name!r}?")
    return " ".join(parts)


class BaseGovDataReader(ReadFile):
    """Plumbing shared by every GovData reader.

    Handles locator coercion, CKAN discovery, cached download with retries, and
    column selection. Subclasses implement ``_parse`` (and override ``suffix``
    when the payload is not CSV).
    """

    # Persistent, content-addressed cache location (override per environment).
    cache_dir: ClassVar[str] = str(Path(tempfile.gettempdir()) / "mloda-govdata-cache")

    @classmethod
    def suffix(cls) -> tuple[str, ...]:
        return (".csv",)

    @classmethod
    def match_subclass_data_access(cls, data_access: Any, feature_names: list[str], options: Any) -> Any:
        return GovDataLocator.coerce(data_access)

    @classmethod
    def load_data(cls, data_access: Any, features: FeatureSet) -> Any:
        # Overriding load_data wholesale classifies this as a final reader (mloda >=0.10.0
        # is_final_reader, structural, no runtime probe).
        requested = list(features.get_all_names())  # sorted tuple since mloda 0.10.0; deterministic column order
        locator = cls._coerce_locator(data_access)
        table = cls._read_table(locator)
        available = set(table.column_names)
        missing = [name for name in requested if name not in available]
        if missing:
            raise ValueError(_unknown_features_message(missing, table.column_names, locator))
        return table.select(requested)

    @classmethod
    def peek(cls, data_access: Any) -> dict[str, str]:
        """Columns selectable as features for this locator, as name to Arrow type.

        Downloads through the cache, so a following feature request reuses the file.
        """
        table = cls._read_table(cls._coerce_locator(data_access))
        return {field.name: str(field.type) for field in table.schema}

    @classmethod
    def _coerce_locator(cls, data_access: Any) -> GovDataLocator:
        locator = GovDataLocator.coerce(data_access)
        if locator is None:
            raise ValueError(f"{cls.__name__} cannot handle data access {data_access!r}")
        return locator

    @classmethod
    def _read_table(cls, locator: GovDataLocator) -> pa.Table:
        with build_client() as client:
            distribution = resolve_distribution(locator, client)
            cache = DownloadCache(cls.cache_dir, client=client)
            cached = cache.get_or_download(distribution.url)
            return cls._parse(cached.path, locator, distribution)

    @classmethod
    def _parse(cls, path: Path, locator: GovDataLocator, distribution: ResolvedDistribution) -> pa.Table:
        raise NotImplementedError(f"{cls.__name__} must implement _parse")


class GovDataReader(BaseGovDataReader):
    """Reads a single-header German-CSV distribution into a typed Arrow table.

    ``schema`` maps column name to type; ``None`` reads every column as a string.
    Subclass and set ``schema`` for a dataset with known typed columns.
    """

    schema: ClassVar[dict[str, ColumnType] | None] = None

    @classmethod
    def _parse(cls, path: Path, locator: GovDataLocator, distribution: ResolvedDistribution) -> pa.Table:
        return parse_german_csv(path, cls.schema)
