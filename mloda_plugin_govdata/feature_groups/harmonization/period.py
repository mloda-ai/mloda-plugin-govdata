"""Annual-period FeatureGroup: ``<time>__year_period`` over a year, GENESIS label, or 31 Dec date column."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, ClassVar

import pyarrow as pa
from mloda.provider import DefaultOptionKeys, FeatureSet, property_spec
from mloda.user import Feature, FeatureName, Options

from ..destatis.core.period import Frequency, parse_genesis_time
from .base import HarmonizationFeature


class AnnualPeriodFeature(HarmonizationFeature):
    """``<time>__year_period``: the annual period start (``date32``) of a time column.

    Accepts an integer year, a GENESIS JAHR or STAG label, or a date on the 31 Dec reference date. A
    date inside the year is refused: the year a snapshot joins to is chosen where the join is defined,
    not a conversion this group makes.
    """

    PREFIX_PATTERN = rf".*__(?P<period_freq>{Frequency.YEAR.value})_period$"
    MIN_IN_FEATURES = 1
    MAX_IN_FEATURES = 1
    PROPERTY_MAPPING: ClassVar = {
        "period_freq": property_spec(
            "Period frequency",
            strict=True,
            allowed_values={Frequency.YEAR.value: "calendar year; quarter and month are not built"},
            context=False,
        ),
        DefaultOptionKeys.in_features: property_spec("The time column"),
    }

    def input_features(self, options: Options, feature_name: FeatureName) -> set[Feature] | None:
        return self.single_source_child(options, feature_name)

    @classmethod
    def calculate_feature(cls, data: Any, features: FeatureSet) -> Any:
        table: pa.Table = data
        # Sorted, not the raw set, so append order is stable regardless of hash seed. run_all
        # re-derives the final column order itself in every column_ordering mode, so this is
        # what a direct calculate_feature call (or by_base's collision winner) sees, not what
        # run_all returns.
        for feature in features.get_sorted_features():
            source = cls.source_column(feature)
            starts = [_period_start(source, row, value) for row, value in enumerate(table.column(source).to_pylist())]
            table = table.append_column(str(feature.name), pa.array(starts, pa.date32()))
        return table


def _period_start(source: str, row: int, value: Any) -> date:
    """Every input shape goes through the GENESIS label parser, which owns the 31 Dec rule."""
    if value is None:
        raise ValueError(f"{source}, row {row}: no time value")
    if isinstance(value, datetime):
        value = value.date()
    label = value.isoformat() if isinstance(value, date) else str(value)
    try:
        return parse_genesis_time(label).start
    except ValueError as exc:
        raise ValueError(f"{source}, row {row}: {exc}") from exc
