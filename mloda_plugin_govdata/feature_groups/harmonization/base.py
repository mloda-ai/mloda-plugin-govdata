"""Shared base for the harmonization FeatureGroups: chained derived groups over reader columns, PyArrow only."""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from mloda.provider import (
    NAME_STAGE,
    ComputeFramework,
    FeatureChainParserMixin,
    FeatureGroup,
    FeatureSet,
    record_match_rejection,
)
from mloda.user import Feature, FeatureName, Options
from mloda.user.pyarrow import PyArrowTable

from ..destatis.core.auth import OPTION_GENESIS_CREDENTIALS
from ..govdata.core.cache import DEFAULT_CACHE_DIR, CacheMissError, DownloadCache
from .core.reference.download import fetch_pinned
from .core.reference.sources import ReferenceCopy, ReferenceSource


def _source_names(options: Options) -> set[str]:
    try:
        return {str(source.name) for source in options.get_in_features()}
    except (TypeError, ValueError):  # no in_features: a chained name
        return set()


class HarmonizationFeature(FeatureChainParserMixin, FeatureGroup):
    """Chained derived FeatureGroup over reader columns; the base matches nothing by itself.

    Children are explicit ``Feature`` objects: the consumer's reader locator forwards to them by
    default and this group's own option keys are carved out, so a chained request resolves without
    the caller touching the reader features.
    """

    cache_dir: ClassVar[str] = str(DEFAULT_CACHE_DIR)  # reference tables are read offline from here
    # Context keys the children pull from the consumer: the retired credential key, so the reader refuses it.
    inherited_context_keys: ClassVar[frozenset[str]] = frozenset({OPTION_GENESIS_CREDENTIALS})

    @classmethod
    def fetch_reference(cls) -> None:
        """Puts this group's reference files in ``cache_dir`` unparsed: kept when cached, else fetched once.

        A fetched file that does not match its pinned sha256 raises ``SourceIntegrityError``; an unpinned file
        is not checked until the first run reads it.
        """
        files = cls._reference_files()
        if not files:
            raise NotImplementedError(f"{cls.__name__} reads no reference table")
        with DownloadCache(Path(cls.cache_dir)) as cache:
            for source in files:
                try:
                    fetch_pinned(cache, source)
                except CacheMissError:
                    fetch_pinned(cache, source, revalidate=True)

    @classmethod
    def reference_sources(cls) -> list[ReferenceCopy]:
        """Each reference file's source with its cached copy's sha256 and download time; offline."""
        copies = []
        with DownloadCache(Path(cls.cache_dir)) as cache:
            for source in cls._reference_files():
                try:
                    cached = cache.get_or_download(source.url, revalidate=False, sha256=source.sha256)
                except CacheMissError:
                    copies.append(ReferenceCopy(source, None, None))
                else:
                    copies.append(ReferenceCopy(source, cached.sha256, cached.retrieved_at))
        return copies

    @classmethod
    def _reference_files(cls) -> tuple[ReferenceSource, ...]:
        """Every file ``_read_reference`` reads; ``fetch_reference`` fetches exactly these."""
        return ()

    @classmethod
    def _read_reference(cls, cache: DownloadCache) -> Any:
        """The group's reference tables, parsed from ``cache`` offline; a miss raises ``CacheMissError``."""
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
        A configuration name equal to its source column is refused with a reason.
        """
        if cls.OUTPUT_PARTS and FeatureGroup.split_output_part(str(feature_name)) is not None:
            return False
        if not super().match_feature_group_criteria(feature_name, options, data_access_collection):
            return False
        if str(feature_name) in _source_names(options):
            reason = f"'{feature_name}' equals its source column (in_features); give the output another name"
            record_match_rejection(cls.__name__, reason, stage=NAME_STAGE)
            return False
        return True

    @classmethod
    def validate_input_features(cls, data: Any, features: FeatureSet) -> None:
        """An output column already in the input: the same name requested again under separate options."""
        present = set(data.column_names)
        for feature in features.get_sorted_features():
            name = str(feature.name)
            outputs = [f"{name}~{part}" for part in cls.OUTPUT_PARTS] if cls.OUTPUT_PARTS else [name]
            if not present.isdisjoint(outputs):
                keys = sorted(cls.declared_option_keys())
                shown = ", ".join(f"{k}={feature.options.get(k)!r}" for k in keys if feature.options.get(k) is not None)
                raise ValueError(
                    f"{cls.__name__}: '{name}' is requested more than once in this run under separate options "
                    f"(this set: {shown or 'none'}), or a source column has its name; request it once, "
                    "or give each set of options its own configured name"
                )

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
