"""mloda reader for a GENESIS ``data/tablefile`` selection (ffcsv).

Flow, on the shared ``BaseGovDataReader`` seam:
    _source_locator             pointer value -> DestatisLocator; declines chained and ``~part`` names
    find_sources                binds the run's DataAccessCollection credentials for the host to the match
    _fetch                      locator.tablefile_fields() -> ParameterCache hit, or a GenesisClient POST
                                on a miss (credentials: Options.context, then the collection, then env)
    _parse                      zip on disk -> parse_ffcsv_zip -> typed Arrow table
"""

from __future__ import annotations

import functools
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

import pyarrow as pa
from mloda.provider import (
    CHAIN_SEPARATOR,
    COLUMN_SEPARATOR,
    ClaimRoute,
    FeatureSet,
    SourceMatch,
)
from mloda.user import DataAccessCollection, Options

from ..govdata.core.discovery import DL_DE_BY_2_0
from ..govdata.core.provenance import FetchedPayload, Provenance
from ..govdata.reader import BaseGovDataReader
from .core.api import GenesisClient, fetch_tablefile
from .core.auth import DestatisCredentials, credentials_from_collection, explicit_credentials_from_options
from .core.cache import ParameterCache
from .core.errors import GenesisAuthError
from .core.hosts import resolve_host
from .core.parse import parse_ffcsv_zip
from .locator import DestatisLocator


@dataclass(frozen=True)
class _CollectionAccess:
    """A matched selection with the run's collection credentials; the source and every repr leave them out."""

    locator: DestatisLocator
    credentials: DestatisCredentials = field(repr=False)

    def describe(self) -> str:
        return self.locator.describe()


class DestatisReader(BaseGovDataReader[DestatisLocator]):
    """Reads one GENESIS table selection into a typed Arrow table, ffcsv parsed."""

    # The reader resolves only the known GENESIS hosts, and both publish under DL-DE-BY-2.0.
    LICENSE: ClassVar[str | None] = DL_DE_BY_2_0

    @classmethod
    def locator_type(cls) -> type[DestatisLocator]:
        return DestatisLocator

    @classmethod
    def _source_locator(cls, value: Any, feature_name: str, options: Options) -> DestatisLocator | None:
        # An ffcsv column never carries mloda's chain or part separator, so such a name (``value__rebased``,
        # ``kreise~key``) belongs to a derived group.
        if CHAIN_SEPARATOR in feature_name or COLUMN_SEPARATOR in feature_name:
            return None
        return super()._source_locator(value, feature_name, options)

    @classmethod
    def find_sources(
        cls,
        route: ClaimRoute,
        feature_name: str,
        options: Options,
        data_access_collection: DataAccessCollection | None,
    ) -> list[SourceMatch]:
        matches = super().find_sources(route, feature_name, options, data_access_collection)
        if not matches or explicit_credentials_from_options(options) is not None:
            return matches
        (match,) = matches
        try:
            found = credentials_from_collection(data_access_collection, resolve_host(match.access.host))
        except (ValueError, GenesisAuthError) as exc:
            # Raises a marked abort, or declines with the reason inside mloda's global filter probe.
            cls._abort(ValueError(str(exc)))
            return []
        return matches if found is None else [SourceMatch(match.source, _CollectionAccess(match.access, found))]

    @classmethod
    def load_neutral(cls, match: SourceMatch, features: FeatureSet) -> Any:
        # Context never splits a batch, and mloda hands over one feature's options, so explicit credentials are
        # gathered from every feature; otherwise which one wins would depend on set order.
        explicit = {
            found
            for feature in features.get_sorted_features()
            if (found := explicit_credentials_from_options(feature.options)) is not None
        }
        if len(explicit) > 1:
            raise ValueError("Features read together from one GENESIS selection carry different explicit credentials.")
        if explicit:
            locator = match.access.locator if isinstance(match.access, _CollectionAccess) else match.access
            match = SourceMatch(match.source, _CollectionAccess(locator, explicit.pop()))
        return super().load_neutral(match, features)

    @classmethod
    def _read_table(cls, locator: DestatisLocator | _CollectionAccess, options: Options | None = None) -> pa.Table:
        bound = locator.credentials if isinstance(locator, _CollectionAccess) else None
        target = locator.locator if isinstance(locator, _CollectionAccess) else locator
        payload = cls._fetch(target, options=options, collection_credentials=bound)
        return cls._parse(payload.path, target, options=options)

    @classmethod
    def _fetch(
        cls,
        locator: DestatisLocator,
        *,
        options: Options | None = None,
        collection_credentials: DestatisCredentials | None = None,
    ) -> FetchedPayload:
        """POSTs (or reuses a cached reply for) the selection; credentials resolve lazily on a miss only."""
        host = resolve_host(locator.host)
        explicit = explicit_credentials_from_options(options) or collection_credentials
        fields = locator.tablefile_fields()
        cache = ParameterCache(cls.cache_dir)
        with GenesisClient(host, credentials=explicit, lock_dir=cls.cache_dir) as client:
            fetch = functools.partial(fetch_tablefile, client)
            cached = cache.get_or_fetch(host, "data/tablefile", fields, fetch)
        provenance = Provenance(
            source="genesis", url=host.url("data/tablefile"), parameters=cached.parameters, license=cls.LICENSE
        )
        return FetchedPayload(
            path=cached.path, sha256=cached.sha256, retrieved_at=cached.retrieved_at, provenance=provenance
        )

    @classmethod
    def _parse(cls, path: Path, locator: DestatisLocator, *, options: Options | None = None) -> pa.Table:
        return parse_ffcsv_zip(path.read_bytes())
