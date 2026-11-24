"""Base mloda source group for GovData distributions.

Each reader is a pointed-only ``SourceFeatureGroup``: ``options={Reader: value}`` makes ``find_sources`` coerce
the value into a locator, and ``load_neutral -> _read_table -> _fetch -> _parse`` fetches the payload through
the cache and parses it into a typed Arrow table. One module per data source implements ``_parse``;
``GovDataReader`` is the generic single-header German-CSV reader.
"""

from __future__ import annotations

import difflib
from abc import abstractmethod
from collections.abc import Mapping
from pathlib import Path
from typing import Any, ClassVar, Generic, TypeVar, cast

import pyarrow as pa
from mloda.provider import (
    ClaimRoute,
    FeatureSet,
    NamePolicy,
    PropertyValidationError,
    SourceMatch,
    record_match_rejection,
    scrub_credentials,
    validate_property_values,
)
from mloda.user import DataAccessCollection, DataType, Options
from mloda.user.pyarrow import PyArrowTable  # noqa: F401

from .core.cache import DEFAULT_CACHE_DIR, CachedFile, CacheMissError, DownloadCache
from .core.client import build_client
from .core.discovery import ResolvedDistribution, resolve_distribution
from .core.locator import GovDataLocator, Locator
from .core.parse import ColumnType, parse_german_csv
from .core.provenance import FetchedPayload, Provenance
from .feature import GovDataFeature

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


def is_scalar(value: Any) -> bool:
    """Match guard for single-valued options: mloda would otherwise validate a collection element-wise."""
    return not isinstance(value, (list, tuple, set, frozenset))


class BaseGovDataReader(GovDataFeature, Generic[LocatorT]):
    """Plumbing shared by every GovData reader, generic over its locator type.

    The base handles GovData locators; a reader over another locator type overrides
    ``locator_type`` and ``_fetch``. Every reader implements ``_parse``.
    """

    # Pointed only: a reader claims a feature when its class (or class name) is an option key; matching never fetches.
    CLAIM_ROUTES: ClassVar[tuple[ClaimRoute, ...]] = (ClaimRoute("locator", NamePolicy.OPEN, searched=False),)
    # Persistent, content-addressed cache location (override per environment).
    cache_dir: ClassVar[str] = str(DEFAULT_CACHE_DIR)
    # The one license every payload of this reader carries, as normalize_license labels it; None when it varies.
    LICENSE: ClassVar[str | None] = None

    @classmethod
    def pointer_keys(cls) -> tuple[str, ...]:
        # Own name only: mloda would also route a parent reader's key to a subclass with another schema or license.
        return (cls.__name__,)

    @classmethod
    def locator_type(cls) -> type[LocatorT]:
        """Locator type this reader coerces option values into; the base reads GovData locators."""
        return cast("type[LocatorT]", GovDataLocator)

    @classmethod
    def _coerce_or_none(cls, value: Any) -> LocatorT | None:
        locator_type = cls.locator_type()
        if isinstance(value, locator_type):
            return value
        return locator_type.coerce(value)

    @classmethod
    def _source_locator(cls, value: Any, feature_name: str, options: Options) -> LocatorT | None:
        """The locator a pointer value selects for this feature, None to decline."""
        return cls._coerce_or_none(value)

    @classmethod
    def find_sources(
        cls,
        route: ClaimRoute,
        feature_name: str,
        options: Options,
        data_access_collection: DataAccessCollection | None,
    ) -> list[SourceMatch]:
        key = next((key for key in cls.pointer_keys() if key in options), None)
        if key is not None and "in_features" in options:  # mloda's in_features: a derived group's name, never a column
            reason = "carries in_features, so only a derived group computes it, and none matched; check its options"
            record_match_rejection(cls.__name__, f"'{feature_name}' {reason}")
            return []
        locator = None if key is None else cls._source_locator(options.get(key), feature_name, options)
        # The full selection is the source, so different years or query windows stay different sources.
        return [] if locator is None else [SourceMatch(source=repr(locator), access=locator)]

    @classmethod
    def load_neutral(cls, match: SourceMatch, features: FeatureSet) -> Any:
        requested = list(features.get_all_names())  # sorted: deterministic column order
        locator = match.access
        table = cls._read_table(locator, features.options)
        available = set(table.column_names)
        missing = [name for name in requested if name not in available]
        if missing:
            raise ValueError(_unknown_features_message(missing, table.column_names, locator))
        return table.select(requested)

    @classmethod
    def peek(cls, value: Any, *, options: Mapping[str, Any] | None = None) -> dict[str, str]:
        """Columns selectable as features for a pointer value, as name to Arrow type.

        ``options`` are the reader options a feature would carry (e.g. a file layout), validated the same way.
        Downloads through the cache, so a following feature request reuses the file.
        """
        table = cls._read_table(cls._coerce_locator(value), cls._peek_options(options))
        return {field.name: str(field.type) for field in table.schema}

    @classmethod
    def retrieval(cls, value: Any) -> FetchedPayload | None:
        """The cached copy's record for a pointer value, None when not cached; never makes a request.

        Provenance is URL-level: a file first read through CKAN loses its dataset record and CKAN license.
        """
        locator = cls._coerce_locator(value)
        if not isinstance(locator, GovDataLocator):
            raise NotImplementedError(f"{cls.__name__} must implement retrieval for {type(locator).__name__}")
        if locator.distribution_url is None:
            raise ValueError(
                f"{cls.__name__}.retrieval needs a distribution URL: CKAN resolves {locator.describe()!r} online. "
                "A read's provenance.url or a recipe's dataset_uri holds it."
            )
        with build_client() as client, DownloadCache(cls.cache_dir, client=client) as cache:
            distribution = resolve_distribution(locator, client)  # a direct URL: no request
            try:
                cached = cache.get_or_download(distribution.url, revalidate=False)
            except CacheMissError:
                return None
        return cls._payload(cached, distribution)

    @classmethod
    def describe_columns(cls, match: SourceMatch) -> dict[str, DataType | None]:
        """``peek`` as mloda's column discovery (lineage extenders call it), with the reader's default options."""
        table = cls._read_table(match.access)
        return {field.name: DataType.from_arrow_type_safe(field.type) for field in table.schema}

    @classmethod
    def data_access_identity(cls, match: SourceMatch) -> str:
        """The dataset name in lineage and audit records: the locator label, a URL cut to scheme, host and path.

        The selection (years, keys, a URL query) is left out.
        """
        label = match.access.describe()
        return scrub_credentials(label) if label.startswith(("http://", "https://")) else label

    @classmethod
    def declared_attributes(cls, features: FeatureSet | None) -> Mapping[str, str | int | float | bool]:
        """``license`` for extenders and ``required_declarations``, the same at plan and load time."""
        return {"license": cls.LICENSE} if cls.LICENSE else {}

    @classmethod
    def _option(cls, key: str, options: Options | None) -> Any:
        """``read_option`` that accepts ``None`` options (``describe_columns``, a bare ``peek``)."""
        return cls.read_option(key, options if options is not None else Options())

    @classmethod
    def _peek_options(cls, options: Mapping[str, Any] | None) -> Options | None:
        if options is None:
            return None
        values = dict(options)
        # Only the keys given: a reader may require options that peek never reads (UBA's query).
        specs = {key: spec for key, spec in (cls.PROPERTY_MAPPING or {}).items() if key in values}
        validate_property_values(values, specs, closed_world=False)
        for key, spec in specs.items():
            if spec.match_guard is not None and not spec.match_guard(values[key]):
                raise PropertyValidationError(key, f"must be {spec.expected or 'accepted by its match guard'}")
        return Options(values)

    @classmethod
    def _coerce_locator(cls, value: Any) -> LocatorT:
        locator = cls._coerce_or_none(value)
        if locator is None:
            raise ValueError(f"{cls.__name__} cannot handle data access {value!r}")
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
            if cls.LICENSE and distribution.license and distribution.license != cls.LICENSE:
                raise ValueError(
                    f"{cls.__name__} declares license {cls.LICENSE!r}, but {locator.describe()!r} is published "
                    f"under {distribution.license!r}; read it with a reader that declares no license."
                )
            cached = DownloadCache(cls.cache_dir, client=client).get_or_download(distribution.url)
        return cls._payload(cached, distribution)

    @classmethod
    def _payload(cls, cached: CachedFile, distribution: ResolvedDistribution) -> FetchedPayload:
        return FetchedPayload(
            path=cached.path,
            sha256=cached.sha256,
            retrieved_at=cached.retrieved_at,
            provenance=Provenance.from_distribution(distribution, cls.LICENSE),
        )

    @classmethod
    @abstractmethod
    def _parse(cls, path: Path, locator: LocatorT, *, options: Options | None = None) -> pa.Table:
        """Parse the fetched payload into a typed Arrow table."""


class GovDataReader(BaseGovDataReader[GovDataLocator]):
    """Reads a single-header German-CSV distribution into a typed Arrow table.

    ``schema`` maps column name to type; ``None`` reads every column as a string.
    Subclass and set ``schema`` for a dataset with known typed columns.
    """

    schema: ClassVar[dict[str, ColumnType] | None] = None

    @classmethod
    def _parse(cls, path: Path, locator: GovDataLocator, *, options: Options | None = None) -> pa.Table:
        return parse_german_csv(path, cls.schema)
