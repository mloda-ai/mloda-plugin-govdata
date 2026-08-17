"""Tests to verify mloda dependencies can be imported."""


def test_mloda_provider_imports() -> None:
    """Verify mloda.provider module imports work."""
    from mloda.provider import ComputeFramework, FeatureGroup

    assert FeatureGroup is not None
    assert ComputeFramework is not None


def test_mloda_core_imports() -> None:
    """Verify mloda.core module imports work."""
    from mloda.core.abstract_plugins.function_extender import Extender

    assert Extender is not None


def test_mloda_testing_imports() -> None:
    """Verify mloda.testing module imports work."""
    from mloda.testing.base import FeatureGroupTestBase

    assert FeatureGroupTestBase is not None


def test_mloda_user_imports() -> None:
    """Verify mloda.user and its pyarrow backend module import work."""
    from mloda.user import Feature, Options, mloda
    from mloda.user.pyarrow import PyArrowTable

    assert Feature is not None
    assert Options is not None
    assert mloda is not None
    assert PyArrowTable is not None
