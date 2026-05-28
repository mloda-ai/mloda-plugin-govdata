"""Tests for MyExtender."""

from mloda_plugin_govdata.extenders.my_plugin import MyExtender
from mloda.core.abstract_plugins.function_extender import Extender


def test_extends_base() -> None:
    """MyExtender should extend Extender."""
    assert issubclass(MyExtender, Extender)


def test_instantiation() -> None:
    """MyExtender should instantiate with no arguments."""
    instance = MyExtender()
    assert instance is not None
