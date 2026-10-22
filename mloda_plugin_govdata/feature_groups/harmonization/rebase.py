"""Re-basing FeatureGroup: ``value__rebased`` over a Destatis Kreis table."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict
from functools import partial
from pathlib import Path
from typing import Any, ClassVar

import pyarrow as pa
from mloda.provider import DefaultOptionKeys, FeatureSet, property_spec
from mloda.user import Feature, FeatureName, Options

from ..govdata.core.cache import CacheMissError, DownloadCache
from .base import OPTIONAL_PART, HarmonizationFeature, offline_first
from .core.rebase import (
    DEFAULT_TOLERANCE,
    KeySheet,
    Policy,
    RebasedRow,
    RebaseIssue,
    RebaseResult,
    ShareKind,
    observations_from_columns,
    rebase,
)
from .core.reference.bbsr import UmsteigeschluesselRow, load_bbsr_kreise
from .core.reference.sources import BBSR_KREISE, ReferenceSource

KREIS_VARIABLE = "KREISE"
VARIABLE_COLUMN = "1_variable_code"
KEY_COLUMN = "1_variable_attribute_code"
TIME_COLUMN = "time"
MARKER_COLUMN = "value_marker"

_POLICIES = {"raise": "fail loud", "flag": "keep the row, report the issue", "drop": "drop the row"}
_SHARES = {kind.value: f"{kind.value}-proportional key" for kind in ShareKind}


class KreisRebaseFeature(HarmonizationFeature):
    """``<value>__rebased``: Kreis observations re-based onto the ``rebase_to_year`` Gebietsstand.

    Reads the ffcsv key (``1_variable_attribute_code`` with ``1_variable_code == KREISE``), ``time``,
    the value column and ``value_marker``; the key sheets come from the BBSR file in the cache.
    Returns one row per (Kreis, year): ``~key``, ``~year``, ``~value``, ``~flag``, ``~sources`` (the
    contributing keys), ``~marker``, ``~issues`` (the issue records touching that row) and ``~provenance``
    (the key sheet's source identity, census breaks and the issues no row carries). ``~sources`` is a list
    of strings, ``~issues`` and ``~provenance`` are JSON. The input rows do not survive.
    """

    PREFIX_PATTERN = rf".*__rebased{OPTIONAL_PART}$"
    RECOGNITION_ONLY_PATTERN = True  # no capture: the name identifies the group, every value comes from Options
    MIN_IN_FEATURES = 1
    MAX_IN_FEATURES = 1
    PARTS: ClassVar = ("key", "year", "value", "flag", "sources", "marker", "issues", "provenance")
    PROPERTY_MAPPING: ClassVar = {
        "rebase_from_year": property_spec("Source Gebietsstand year, the key sheet's first year", context=False),
        "rebase_to_year": property_spec("Target Gebietsstand year, the key sheet's second year", context=False),
        "rebase_share": property_spec(
            "BBSR share to re-base with",
            strict=True,
            allowed_values=_SHARES,
            default=ShareKind.POPULATION.value,
            context=False,
        ),
        "rebase_tolerance": property_spec("Share-sum tolerance", default=DEFAULT_TOLERANCE, context=False),
        "rebase_on_unmatched": property_spec(
            "Keys absent from the key sheet", strict=True, allowed_values=_POLICIES, default="raise", context=False
        ),
        "rebase_on_incomplete": property_spec(
            "Targets with an unobserved feeding key",
            strict=True,
            allowed_values=_POLICIES,
            default="raise",
            context=False,
        ),
        DefaultOptionKeys.in_features: property_spec("The value column to re-base"),
    }

    @classmethod
    def _read_reference(cls, cache: DownloadCache, *, fetch: bool = False) -> list[UmsteigeschluesselRow]:
        return offline_first(partial(load_bbsr_kreise, cache), fetch=fetch)

    @classmethod
    def load_keys(cls) -> tuple[Sequence[UmsteigeschluesselRow], ReferenceSource]:
        """The BBSR Kreise key sheets from the offline cache and the source they are cited as."""
        with DownloadCache(Path(cls.cache_dir)) as cache:
            try:
                return cls._read_reference(cache), BBSR_KREISE
            except CacheMissError as exc:
                raise CacheMissError(
                    f"{exc}. Call {cls.__name__}.fetch_reference() once to fetch and cache it. If the "
                    f"key sheet lives elsewhere, set HarmonizationFeature.cache_dir (or {cls.__name__}.cache_dir "
                    "for this group alone), independent of any reader's cache_dir."
                ) from exc

    def input_features(self, options: Options, feature_name: FeatureName) -> set[Feature] | None:
        parsed = super().input_features(options, feature_name) or set()
        (value,) = parsed
        return {self.child(str(value.name))} | {
            self.child(name) for name in (VARIABLE_COLUMN, KEY_COLUMN, TIME_COLUMN, MARKER_COLUMN)
        }

    @classmethod
    def calculate_feature(cls, data: Any, features: FeatureSet) -> Any:
        table: pa.Table = data
        keys, source = cls.load_keys()
        results = {
            name: cls._rebase(table, cls.source_column(feature), feature.options, keys, source)
            for name, feature in cls.by_base(features).items()
        }
        cls._check_aligned(results)
        columns: dict[str, pa.Array] = {}
        for name, result in results.items():
            columns.update(cls._columns(name, result))
        return pa.table(columns)

    @classmethod
    def _check_aligned(cls, results: dict[str, RebaseResult]) -> None:
        """Every output re-based in the same call must land on one (Kreis, year) row space.

        ``pa.table`` only checks that column lengths match: two outputs independently re-based
        to the same row count but different rows would still be stacked, silently pairing the
        wrong Kreis/year. Different options (years, share, unmatched/incomplete policy) per
        output can make their surviving rows diverge, so check the actual keys, not just counts.
        """
        names = iter(results)
        first = next(names, None)
        if first is None:
            return
        reference = [(row.key, row.year) for row in results[first].rows]
        for name in names:
            rows = [(row.key, row.year) for row in results[name].rows]
            if rows != reference:
                raise ValueError(
                    f"{cls.__name__}: {name!r} and {first!r} re-base to different (Kreis, year) rows; "
                    "requested together, they must share rebase_from_year, rebase_to_year, rebase_share, "
                    "rebase_on_unmatched and rebase_on_incomplete"
                )

    @classmethod
    def _rebase(
        cls,
        table: pa.Table,
        value_column: str,
        options: Options,
        keys: Sequence[UmsteigeschluesselRow],
        source: ReferenceSource,
    ) -> RebaseResult:
        from_year, to_year = _year(options, "rebase_from_year"), _year(options, "rebase_to_year")
        share = ShareKind(_option(options, "rebase_share", ShareKind.POPULATION.value))
        if table.num_rows == 0:  # an empty selection is an empty result with its schema, not a wrong one
            key_sheet = KeySheet(source.name, source.url, source.sha256, from_year, to_year, share)
            return RebaseResult((), key_sheet, (), ())
        variables = sorted(set(table.column(VARIABLE_COLUMN).to_pylist()))
        if variables != [KREIS_VARIABLE]:
            raise ValueError(
                f"{cls.__name__} re-bases Kreis tables only: variable block 1 holds {variables}, not {KREIS_VARIABLE!r}"
            )
        observations = observations_from_columns(
            table.column(KEY_COLUMN).to_pylist(),
            table.column(TIME_COLUMN).to_pylist(),
            table.column(value_column).to_pylist(),
            table.column(MARKER_COLUMN).to_pylist(),
        )
        return rebase(
            observations,
            keys=keys,
            source=source,
            from_year=from_year,
            to_year=to_year,
            share=share,
            tolerance=_option(options, "rebase_tolerance", DEFAULT_TOLERANCE),
            on_unmatched=_policy(options, "rebase_on_unmatched"),
            on_incomplete=_policy(options, "rebase_on_incomplete"),
        )

    @classmethod
    def _columns(cls, name: str, result: RebaseResult) -> dict[str, pa.Array]:
        rows = result.rows
        attached: set[RebaseIssue] = set()
        issues = [_issues_for(row, result.issues, attached) for row in rows]
        provenance = {
            **asdict(result.key_sheet),
            "share": result.key_sheet.share.value,
            "sheet": result.key_sheet.sheet,
            "census_breaks": list(result.census_breaks),
            "issues_elsewhere": [_issue_record(issue) for issue in result.issues if issue not in attached],
        }
        provenance_json = json.dumps(provenance, sort_keys=True)
        return {
            f"{name}~key": pa.array([r.key for r in rows], pa.string()),
            f"{name}~year": pa.array([r.year for r in rows], pa.int64()),
            f"{name}~value": pa.array([r.value for r in rows], pa.float64()),
            f"{name}~flag": pa.array([r.flag.value for r in rows], pa.string()),
            f"{name}~sources": pa.array([list(r.sources) for r in rows], pa.list_(pa.string())),
            f"{name}~marker": pa.array([r.marker for r in rows], pa.string()),
            f"{name}~issues": pa.array(issues, pa.string()),
            f"{name}~provenance": pa.array([provenance_json] * len(rows), pa.string()),
        }


def _issue_record(issue: RebaseIssue) -> dict[str, Any]:
    return {**asdict(issue), "kind": issue.kind.value}


def _issues_for(row: RebasedRow, issues: Sequence[RebaseIssue], attached: set[RebaseIssue]) -> str:
    """Issues naming the row's key, one of its source keys, or the row as their target, for its year or all years."""
    mine = [
        issue
        for issue in issues
        if (row.key in (issue.key, issue.target) or issue.key in row.sources) and issue.year in (None, row.year)
    ]
    attached.update(mine)
    return json.dumps([_issue_record(issue) for issue in mine], sort_keys=True)


def _option(options: Options, key: str, default: Any) -> Any:
    value = options.get(key)
    return default if value is None else value


def _year(options: Options, key: str) -> int:
    value = options.get(key)
    if value is None:
        raise ValueError(
            f"{KreisRebaseFeature.__name__} needs the group options rebase_from_year and rebase_to_year "
            f"(the BBSR key sheet to use); {key} is missing"
        )
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{key} must be an integer year, got {type(value).__name__}")
    return value


def _policy(options: Options, key: str) -> Policy:
    value = _option(options, key, "raise")
    if value == "raise":
        return "raise"
    if value == "flag":
        return "flag"
    if value == "drop":
        return "drop"
    raise ValueError(f"{key} must be 'raise', 'drop', or 'flag', got {value!r}")
