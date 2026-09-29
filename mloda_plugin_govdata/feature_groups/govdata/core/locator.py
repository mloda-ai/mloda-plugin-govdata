"""GovData locator: identifies a dataset distribution to read."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypeVar, runtime_checkable

DEFAULT_CKAN_BASE = "https://ckan.govdata.de/api/3/action"

_L = TypeVar("_L", bound="Locator")


@runtime_checkable
class Locator(Protocol):
    """What a reader needs from its locator type: coercion from an option value and a label.

    The label names the dataset in messages and in lineage and audit records, so it never carries a credential.
    """

    # PYI019 wants `Self`, which is 3.11+; the package floor is 3.10.
    @classmethod
    def coerce(cls: type[_L], value: object) -> _L | None: ...  # noqa: PYI019

    def describe(self) -> str: ...


@dataclass(frozen=True)
class GovDataLocator:
    """Points at one GovData distribution.

    Either a CKAN ``dataset_id`` (resolved to a distribution via ``package_show``)
    or a direct ``distribution_url``. ``resource_index`` selects the distribution
    when a dataset exposes several.
    """

    dataset_id: str | None = None
    distribution_url: str | None = None
    ckan_base: str = DEFAULT_CKAN_BASE
    resource_index: int = 0

    def __post_init__(self) -> None:
        if not self.dataset_id and not self.distribution_url:
            raise ValueError("GovDataLocator needs a dataset_id or a distribution_url.")

    @classmethod
    def from_string(cls, value: str) -> GovDataLocator:
        """A URL becomes a direct distribution; anything else is a dataset id."""
        if value.startswith(("http://", "https://")):
            return cls(distribution_url=value)
        return cls(dataset_id=value)

    @classmethod
    def coerce(cls, value: object) -> GovDataLocator | None:
        """Normalize a reader option value into a locator, or None if unusable."""
        if isinstance(value, GovDataLocator):
            return value
        if isinstance(value, str) and value:
            return cls.from_string(value)
        return None

    def describe(self) -> str:
        """Label for messages: the dataset id, else the distribution URL."""
        return self.dataset_id or self.distribution_url or ""
