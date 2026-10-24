"""HarmonizationFeature.by_name: stable output order independent of set iteration and hash seed;
source_column: exactly one source; fetch_reference without tables."""

from pathlib import Path

import pytest
from mloda.provider import FeatureSet
from mloda.user import Feature, Options

from mloda_plugin_govdata.feature_groups.harmonization.base import HarmonizationFeature
from mloda_plugin_govdata.feature_groups.harmonization.period import AnnualPeriodFeature


def test_fetch_reference_on_a_group_without_reference_tables_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(AnnualPeriodFeature, "cache_dir", str(tmp_path))
    with pytest.raises(NotImplementedError, match="AnnualPeriodFeature reads no reference table"):
        AnnualPeriodFeature.fetch_reference()


def test_source_column_names_the_feature_on_a_wrong_source_count() -> None:
    # Not a chained name, so the sources come from in_features.
    feature = Feature("two_sources", Options(context={"in_features": ["a", "b"]}))
    with pytest.raises(ValueError, match="Feature 'two_sources' allows at most 1 in_feature"):
        AnnualPeriodFeature.source_column(feature)


def test_by_name_orders_by_feature_name_not_set_iteration() -> None:
    # Five names, so an unsorted set order rarely matches by chance.
    names = ["zeta__nuts2024", "alpha__nuts2024", "mu__nuts2024", "beta__nuts2024", "eta__nuts2024"]
    features = FeatureSet([Feature(name) for name in names])
    assert list(HarmonizationFeature.by_name(features)) == sorted(names)
