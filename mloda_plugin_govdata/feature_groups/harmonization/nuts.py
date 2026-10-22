"""AGS-to-NUTS FeatureGroup: ``<key>__nuts2024`` over any AGS key column."""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Any, ClassVar, Literal, cast

import pyarrow as pa
from mloda.provider import DefaultOptionKeys, FeatureSet, property_spec
from mloda.user import Feature, FeatureName, Options

from ..govdata.core.cache import CacheMissError, DownloadCache
from .base import OPTIONAL_PART, HarmonizationFeature, offline_first
from .core.crosswalk import NUTS_VERSION, NutsCrosswalk, load_nuts_crosswalk
from .core.nuts import map_ags_to_nuts
from .core.reference.gv_isys import load_gv_isys_changes

NULL_KEY = "null key cell"
_POLICIES = {"raise": "fail loud", "flag": "null codes, the reason in ~unmatched"}


class AgsToNutsFeature(HarmonizationFeature):
    """``<key>__nuts2024``: NUTS codes for AGS keys from the pinned LAU-to-NUTS crosswalk.

    Appends, row-aligned, ``~key`` (the input key), ``~nuts1``, ``~nuts2``, ``~nuts3``, ``~version``
    (null when unmatched) and ``~unmatched`` (the reason, empty when matched). The NUTS version in the
    name (or ``nuts_version``) must be the cached crosswalk's, so a result names what it was mapped with.
    """

    PREFIX_PATTERN = rf".*__nuts(?P<nuts_version>{NUTS_VERSION}){OPTIONAL_PART}$"
    MIN_IN_FEATURES = 1
    MAX_IN_FEATURES = 1
    PARTS: ClassVar = ("key", "nuts1", "nuts2", "nuts3", "version", "unmatched")
    PROPERTY_MAPPING: ClassVar = {
        "nuts_version": property_spec(
            "NUTS version the keys resolve against",
            strict=True,
            allowed_values={NUTS_VERSION: "the pinned Eurostat LAU-to-NUTS crosswalk"},
            context=False,
        ),
        "nuts_on_unmatched": property_spec(
            "Keys the crosswalk cannot map", strict=True, allowed_values=_POLICIES, default="raise", context=False
        ),
        DefaultOptionKeys.in_features: property_spec("The AGS key column"),
    }
    # GV-ISys change files that redirect a retired Kreis key to its successor; the pinned years.
    history_years: ClassVar[tuple[int, ...]] = (2016,)

    @classmethod
    def _read_reference(cls, cache: DownloadCache, *, fetch: bool = False) -> NutsCrosswalk:
        changes = [
            change
            for year in cls.history_years
            for change in offline_first(partial(load_gv_isys_changes, year, cache), fetch=fetch)
        ]
        return offline_first(partial(load_nuts_crosswalk, cache, gv_isys_changes=changes), fetch=fetch)

    @classmethod
    def load_crosswalk(cls) -> NutsCrosswalk:
        """The crosswalk plus the pinned history, from the offline cache; a miss names the fetch call."""
        with DownloadCache(Path(cls.cache_dir)) as cache:
            try:
                return cls._read_reference(cache)
            except CacheMissError as exc:
                raise CacheMissError(
                    f"{exc}. Call {cls.__name__}.fetch_reference() once to fetch and cache the crosswalk and the "
                    f"GV-ISys change files for {cls.history_years}. If the reference tables live elsewhere, set "
                    f"HarmonizationFeature.cache_dir (or {cls.__name__}.cache_dir for this group alone), "
                    "independent of any reader's cache_dir."
                ) from exc

    def input_features(self, options: Options, feature_name: FeatureName) -> set[Feature] | None:
        return self.single_source_child(options, feature_name)

    @classmethod
    def calculate_feature(cls, data: Any, features: FeatureSet) -> Any:
        table: pa.Table = data
        crosswalk = cls.load_crosswalk()
        for name, feature in cls.by_base(features).items():
            version = cls.declared(feature, "nuts_version")
            if version != crosswalk.nuts_version:
                raise ValueError(
                    f"{feature.name} asks for NUTS {version}, the cached crosswalk is NUTS {crosswalk.nuts_version}"
                )
            source = cls.source_column(feature)
            column = table.column(source)
            if not (pa.types.is_string(column.type) or pa.types.is_large_string(column.type)):
                raise TypeError(
                    f"{source} must be a string column of AGS keys (leading zeros matter), got {column.type}"
                )
            raw: list[str | None] = column.to_pylist()
            policy = _policy(feature.options)
            nulls = [row for row, key in enumerate(raw) if key is None]
            if nulls and policy == "raise":
                raise ValueError(f"{source}, row {nulls[0]}: {NULL_KEY}; nuts_on_unmatched='flag' keeps such rows")
            present = list(dict.fromkeys(key for key in raw if key is not None))
            result = map_ags_to_nuts(present, crosswalk=crosswalk, on_unmatched=policy)
            matched = {m.key: m for m in result.matched}
            reasons = {u.key: u.reason for u in result.unmatched}
            parts = {
                "key": raw,
                "nuts1": [matched[k].nuts1 if k in matched else None for k in raw],
                "nuts2": [matched[k].nuts2 if k in matched else None for k in raw],
                "nuts3": [matched[k].nuts3 if k in matched else None for k in raw],
                "version": [crosswalk.nuts_version if k in matched else None for k in raw],
                "unmatched": [NULL_KEY if k is None else reasons.get(k, "") for k in raw],
            }
            for part in cls.PARTS:
                table = table.append_column(f"{name}~{part}", pa.array(parts[part], pa.string()))
        return table


def _policy(options: Options) -> Literal["raise", "flag"]:
    value = options.get("nuts_on_unmatched")
    if value is None:
        return "raise"
    if value not in ("raise", "flag"):
        raise ValueError(f"nuts_on_unmatched must be 'raise' or 'flag', got {value!r}")
    return cast(Literal["raise", "flag"], value)
