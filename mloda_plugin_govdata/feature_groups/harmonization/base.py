"""Shared base for the harmonization FeatureGroups: chained derived groups over reader columns, PyArrow only."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar, TypeVar

from mloda.provider import (
    ComputeFramework,
    FeatureChainParserMixin,
    FeatureGroup,
    FeatureSet,
)
from mloda.user import Feature, FeatureName, Options
from mloda.user.pyarrow import PyArrowTable

from ..destatis.core.auth import OPTION_GENESIS_CREDENTIALS
from ..govdata.core.cache import DEFAULT_CACHE_DIR, CacheMissError, DownloadCache

_T = TypeVar("_T")


def offline_first(load: Callable[..., _T], *, fetch: bool) -> _T:
    """One pinned file through ``load(revalidate=...)``: offline first; with ``fetch``, a cache miss is fetched once."""
    try:
        return load(revalidate=False)
    except CacheMissError:
        if not fetch:
            raise
        return load(revalidate=True)


class HarmonizationFeature(FeatureChainParserMixin, FeatureGroup):
    """Chained derived FeatureGroup over reader columns; the base matches nothing by itself.

    Children are explicit ``Feature`` objects: the consumer's reader locator forwards to them by
    default, this group's own option keys are carved out, and the GENESIS credentials are pulled
    from context, so a chained request resolves without the caller touching the reader features.
    """

    cache_dir: ClassVar[str] = str(DEFAULT_CACHE_DIR)  # reference tables are read offline from here
    # Context keys the children pull from the consumer; context never enters the feature hash.
    inherited_context_keys: ClassVar[frozenset[str]] = frozenset({OPTION_GENESIS_CREDENTIALS})

    @classmethod
    def fetch_reference(cls) -> None:
        """Puts this group's reference tables in ``cache_dir``: read offline when cached, else fetched once.

        A fetched file that does not match its pinned sha256 raises ``SourceIntegrityError``.
        """
        with DownloadCache(Path(cls.cache_dir)) as cache:
            cls._read_reference(cache, fetch=True)

    @classmethod
    def _read_reference(cls, cache: DownloadCache, *, fetch: bool = False) -> Any:
        """The group's reference tables from ``cache``, each file through ``offline_first``."""
        raise NotImplementedError(f"{cls.__name__} reads no reference table")

    @classmethod
    def compute_framework_rule(cls) -> set[type[ComputeFramework]] | None:
        return {PyArrowTable}

    @classmethod
    def match_feature_group_criteria(
        cls, feature_name: str | FeatureName, options: Options, data_access_collection: Any = None
    ) -> bool:
        """A ``~part`` name never matches whole, so mloda reads it against OUTPUT_PARTS.

        Needed for configuration names, which match any name: mloda strips only a numeric ``~N`` before matching.
        """
        if cls.OUTPUT_PARTS and FeatureGroup.split_output_part(str(feature_name)) is not None:
            return False
        return super().match_feature_group_criteria(feature_name, options, data_access_collection)

    @classmethod
    def child(cls, name: str) -> Feature:
        return Feature(
            name,
            forward_group_exclude=cls.declared_option_keys(),
            inherit_context_keys=cls.inherited_context_keys,
        )

    def single_source_child(self, options: Options, feature_name: FeatureName) -> set[Feature] | None:
        """The one parsed source column, re-wrapped as this group's own child.

        Shared by the groups whose ``input_features`` does nothing beyond that re-wrap; a group
        with more to add (extra sibling children, for example) still parses its own way.
        """
        parsed = FeatureChainParserMixin.input_features(self, options, feature_name) or set()
        return {self.child(str(source.name)) for source in parsed}

    @classmethod
    def source_column(cls, feature: Feature) -> str:
        """The one input column, from the chained name (``x__op``) or from ``in_features``."""
        return cls._extract_single_source_feature(feature)

    @classmethod
    def by_name(cls, features: FeatureSet) -> dict[str, Feature]:
        """One feature per output, in name order; mloda hands a ``~part`` request over as its base name."""
        return {str(feature.name): feature for feature in features.get_sorted_features()}

    @classmethod
    def declared(cls, feature: Feature, key: str) -> str:
        """The operation from the name (named captures bind by ``key``) or the options; the name wins."""
        operation = cls._resolve_operation(feature, key)
        if operation is None:
            raise ValueError(f"{feature.name}: {key} is neither in the name nor in the options")
        return operation
