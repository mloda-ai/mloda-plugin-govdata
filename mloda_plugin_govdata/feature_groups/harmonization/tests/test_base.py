"""HarmonizationFeature.by_base: stable output order and collision resolution, independent of
set iteration/hash seed; source_column: exactly one source; fetch_reference without tables."""

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


def test_by_base_orders_by_feature_name_not_set_iteration() -> None:
    # Five distinct bases, not two or three: an unfixed set-iteration order has only a 1-in-120
    # chance of coincidentally matching this expected order on a given run.
    names = ["zeta__nuts2024", "alpha__nuts2024~nuts1", "mu__nuts2024", "beta__nuts2024", "eta__nuts2024"]
    features = FeatureSet([Feature(name) for name in names])
    result = HarmonizationFeature.by_base(features)
    assert list(result) == [HarmonizationFeature.base_name(name) for name in sorted(names)]


def test_by_base_collision_keeps_the_part_over_the_plain_base() -> None:
    # A base and its own ~part variant collide on base name; the ~part's full name sorts after
    # the bare base name, so it wins deterministically and the plain request's Options are dropped.
    plain = Feature("key__nuts2024", Options({"nuts_on_unmatched": "raise"}))
    part = Feature("key__nuts2024~unmatched", Options({"nuts_on_unmatched": "flag"}))
    result = HarmonizationFeature.by_base(FeatureSet([plain, part]))
    assert result["key__nuts2024"] is part
