"""mloda reader for a GENESIS ``data/tablefile`` selection (ffcsv).

Flow, on the shared ``BaseGovDataReader`` seam:
    _source_locator             pointer value -> DestatisLocator; declines chained and ``~part`` names
    _fetch                      locator.tablefile_fields() -> ParameterCache hit, or a
                                GenesisClient POST on a miss (credentials: Options.context, then env)
    _parse                      zip on disk -> parse_ffcsv_zip -> typed Arrow table
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any, ClassVar

import pyarrow as pa
from mloda.provider import CHAIN_SEPARATOR, COLUMN_SEPARATOR
from mloda.user import Options

from ..govdata.core.discovery import DL_DE_BY_2_0
from ..govdata.core.provenance import FetchedPayload, Provenance
from ..govdata.reader import BaseGovDataReader
from .core.api import GenesisClient, fetch_tablefile
from .core.auth import explicit_credentials_from_options
from .core.cache import ParameterCache
from .core.hosts import resolve_host
from .core.parse import parse_ffcsv_zip
from .locator import DestatisLocator


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
    def _fetch(cls, locator: DestatisLocator, *, options: Options | None = None) -> FetchedPayload:
        """POSTs (or reuses a cached reply for) the selection; credentials resolve lazily on a miss only."""
        host = resolve_host(locator.host)
        explicit = explicit_credentials_from_options(options)
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
