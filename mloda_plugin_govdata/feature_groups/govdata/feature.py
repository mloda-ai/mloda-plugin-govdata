"""Abstract root of the GovData source groups."""

from __future__ import annotations

from mloda.provider import SourceFeatureGroup


class GovDataFeature(SourceFeatureGroup):
    """Base of every reader; a ``feature_group="GovDataFeature"`` scope narrows to readers, a pointer picks one."""
