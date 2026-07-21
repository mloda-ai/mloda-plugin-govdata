"""Root FeatureGroup exposing the GovData readers."""

from __future__ import annotations

from mloda.provider import BaseInputData
from mloda_plugins.feature_group.input_data.read_file_feature import ReadFileFeature

from .reader import BaseGovDataReader


class GovDataFeature(ReadFileFeature):
    """Root FeatureGroup for GovData columns; inherits the any-framework rule to avoid resolver collisions."""

    @classmethod
    def input_data(cls) -> BaseInputData | None:
        # The base reader, so every sibling reader subclass stays matchable via its class-name options key.
        return BaseGovDataReader()
