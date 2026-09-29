"""Base mloda reader for GovData distributions.

``BaseGovDataReader`` follows the ``CsvReader`` pattern (a ``ReadFile`` subclass). Every reader
flows ``load_data -> _read_table -> _fetch -> _parse``: coerce a locator, fetch the payload through
the cache, parse it into a typed Arrow table. One module per data source implements ``_parse``;
``GovDataReader`` is the generic single-header German-CSV reader.
"""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any, ClassVar, Generic, TypeVar, cast

import pyarrow as pa
from mloda.provider import FeatureSet
from mloda.user import DataType, Options
from mloda.user.pyarrow import PyArrowTable  # noqa: F401
from mloda_plugins.feature_group.input_data.read_file import ReadFile

from .core.cache import DEFAULT_CACHE_DIR, DownloadCache
from .core.client import build_client
from .core.discovery import resolve_distribution
from .core.locator import GovDataLocator, Locator
from .core.parse import ColumnType, parse_german_csv
from .core.provenance import FetchedPayload, Provenance

LocatorT = TypeVar("LocatorT", bound=Locator)


def _unknown_features_message(missing: list[str], available: list[str], locator: Locator) -> str:
    """Name the missing features, list what the distribution offers, and suggest close matches."""
    target = locator.describe()
    parts = [
        f"Unknown feature(s) {', '.join(repr(name) for name in missing)} for {target!r}.",
        f"Available: {', '.join(sorted(available))}.",
    ]
    for name in missing:
        close = difflib.get_close_matches(name, available, n=1)
        if close:
            parts.append(f"Did you mean {close[0]!r} instead of {name!r}?")
    return " ".join(parts)


class BaseGovDataReader(ReadFile, Generic[LocatorT]):
    """Plumbing shared by every GovData reader, generic over its locator type.

    The base handles GovData locators; a reader over another locator type overrides
    ``locator_type`` and ``_fetch``. Every reader implements ``_parse``.
    """

    # Persistent, content-addressed cache location (override per environment).
    cache_dir: ClassVar[str] = str(DEFAULT_CACHE_DIR)

    @classmethod
    def suffix(cls) -> tuple[str, ...]:
        return (".csv",)

    @classmethod
    def locator_type(cls) -> type[LocatorT]:
        """Locator type this reader coerces option values into; the base reads GovData locators."""
        return cast("type[LocatorT]", GovDataLocator)

    @classmethod
    def _coerce_or_none(cls, data_access: Any) -> LocatorT | None:
        locator_type = cls.locator_type()
        if isinstance(data_access, locator_type):
            return data_access
        return locator_type.coerce(data_access)

    @classmethod
    def match_subclass_data_access(cls, data_access: Any, feature_names: list[str], options: Any) -> LocatorT | None:
        return cls._coerce_or_none(data_access)

    @classmethod
    def load_data(cls, data_access: Any, features: FeatureSet) -> Any:
        # Overriding load_data wholesale classifies this as a final reader (mloda's is_final_reader,
        # structural, no runtime probe).
        # get_all_names() is a sorted tuple (deterministic column order) of FeatureName, a str subclass;
        # normalized so messages print plain names.
        requested = [str(name) for name in features.get_all_names()]
        locator = cls._coerce_locator(data_access)
        table = cls._read_table(locator, features.options)
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
    def describe_columns(cls, data_access: Any) -> dict[str, DataType | None]:
        """``peek`` as mloda's column discovery (lineage extenders call it); downloads through the cache too."""
        table = cls._read_table(cls._coerce_locator(data_access))
        return {field.name: DataType.from_arrow_type_safe(field.type) for field in table.schema}

    @classmethod
    def data_access_identity(cls, data_access: Any) -> str:
        """The dataset name in lineage and audit records: the locator label, a URL cut to scheme, host and path.

        mloda's default names every locator by its type alone. The selection (years, keys, a URL query) is left out.
        """
        if not isinstance(data_access, cls.locator_type()):
            return super().data_access_identity(data_access)
        label = data_access.describe()
        return super().data_access_identity(label) if label.startswith(("http://", "https://")) else label

    @classmethod
    def _scalar_reader_option(cls, key: str, options: Any) -> Any:
        """Reject a collection value, since strict_validation only checks list elements individually."""
        value = cls.reader_option(key, options)
        if isinstance(value, (list, tuple, set, frozenset)):
            raise ValueError(f"{cls.__name__} option '{key}' takes a single value, got {value!r}.")  # noqa: TRY004
        return value

    @classmethod
    def _coerce_locator(cls, data_access: Any) -> LocatorT:
        locator = cls._coerce_or_none(data_access)
        if locator is None:
            raise ValueError(f"{cls.__name__} cannot handle data access {data_access!r}")
        return locator

    @classmethod
    def _read_table(cls, locator: LocatorT, options: Options | None = None) -> pa.Table:
        payload = cls._fetch(locator, options=options)
        return cls._parse(payload.path, locator, options=options)

    @classmethod
    def _fetch(cls, locator: LocatorT, *, options: Options | None = None) -> FetchedPayload:
        """CKAN discovery plus a cached GET for GovData locators."""
        if not isinstance(locator, GovDataLocator):
            raise NotImplementedError(f"{cls.__name__} must implement _fetch for {type(locator).__name__}")
        with build_client() as client:
            distribution = resolve_distribution(locator, client)
            cached = DownloadCache(cls.cache_dir, client=client).get_or_download(distribution.url)
        return FetchedPayload(
            path=cached.path,
            sha256=cached.sha256,
            retrieved_at=cached.retrieved_at,
            provenance=Provenance.from_distribution(distribution),
        )

    @classmethod
    def _parse(cls, path: Path, locator: LocatorT, *, options: Options | None = None) -> pa.Table:
        raise NotImplementedError(f"{cls.__name__} must implement _parse")


class GovDataReader(BaseGovDataReader[GovDataLocator]):
    """Reads a single-header German-CSV distribution into a typed Arrow table.

    ``schema`` maps column name to type; ``None`` reads every column as a string.
    Subclass and set ``schema`` for a dataset with known typed columns.
    """

    schema: ClassVar[dict[str, ColumnType] | None] = None

    @classmethod
    def _parse(cls, path: Path, locator: GovDataLocator, *, options: Options | None = None) -> pa.Table:
        return parse_german_csv(path, cls.schema)
