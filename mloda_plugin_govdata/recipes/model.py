"""Recipe file model, fail-fast: the mloda feature array plus links and compliance blocks; never carries credentials."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .credential_scan import SHA256_HEX, reject_credentials

JoinName = Literal["inner", "left", "right", "outer", "append", "union"]

_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$", re.ASCII)


class RecipeError(ValueError):
    """A recipe failed validation or could not be turned into mloda objects."""


def error_summary(exc: ValidationError) -> str:
    """Locations and messages only: pydantic's default text echoes the input, which may be the rejected credential."""
    parts = []
    for error in exc.errors(include_url=False, include_context=False, include_input=False):
        location = ".".join(str(part) for part in error["loc"])
        message = error["msg"].removeprefix("Value error, ")
        parts.append(f"{location}: {message}" if location else message)
    return "; ".join(parts)


def _forbid_extra() -> ConfigDict:
    return ConfigDict(extra="forbid")


class FeatureItem(BaseModel):
    """One object item of the mloda feature array; fields and cross-field rules mirror mloda's ``FeatureConfig``."""

    model_config = _forbid_extra()

    name: str = Field(min_length=1)
    options: dict[str, Any] | None = None
    in_features: list[str] | None = None
    group_options: dict[str, Any] | None = None
    context_options: dict[str, Any] | None = None
    propagate_context_keys: list[str] | None = None
    cascade_context_keys: list[str] | None = None
    column_index: int | None = None
    feature_group: str | None = None
    implementation: str | list[str] | None = None

    @model_validator(mode="after")
    def _mloda_rules(self) -> FeatureItem:
        if self.options and (self.group_options or self.context_options):
            raise ValueError("options cannot be combined with group_options or context_options")
        for key_field in ("propagate_context_keys", "cascade_context_keys"):
            if getattr(self, key_field) and not self.context_options:
                raise ValueError(f"{key_field} needs context_options")
        return self


class JoinSide(BaseModel):
    """One side of a link: the FeatureGroup class name, its key columns, and the node discriminator."""

    model_config = _forbid_extra()

    feature_group: str = Field(min_length=1)
    index: list[str] = Field(min_length=1)
    discriminator: dict[str, Any] | None = None

    @field_validator("index")
    @classmethod
    def _non_empty_columns(cls, value: list[str]) -> list[str]:
        if any(not column for column in value):
            raise ValueError("index columns must be non-empty strings")
        return value


class LinkSpec(BaseModel):
    """A join the feature array cannot express; ``asof`` needs its own config and is not a recipe join."""

    model_config = _forbid_extra()

    join: JoinName
    left: JoinSide
    right: JoinSide


class SourceCompliance(BaseModel):
    """Provenance and license of one data source a recipe reads."""

    model_config = _forbid_extra()

    license: str = Field(min_length=1)
    attribution: str = Field(min_length=1)
    dataset_uri: str
    retrieved_at: AwareDatetime
    sha256: str
    modifications: list[str] = Field(default_factory=list)
    credential_env: list[str] = Field(default_factory=list)

    @field_validator("dataset_uri")
    @classmethod
    def _uri_has_a_scheme(cls, value: str) -> str:
        if "://" not in value:
            raise ValueError("dataset_uri must be a URI with a scheme")
        return value

    @field_validator("sha256")
    @classmethod
    def _sha256_shape(cls, value: str) -> str:
        if not SHA256_HEX.fullmatch(value):
            raise ValueError("sha256 must be 64 lower-case hex digits")
        return value

    @field_validator("credential_env")
    @classmethod
    def _env_names_only(cls, value: list[str]) -> list[str]:
        # Positions only: an entry here may be a pasted credential value, which must not reach the message.
        bad = [position for position, name in enumerate(value) if not _ENV_NAME.fullmatch(name)]
        if bad:
            raise ValueError(f"credential_env holds env-var names only (e.g. GENESIS_TOKEN); entries {bad} are not")
        return value


class Compliance(BaseModel):
    """The compliance block: one entry per source, plus free-text notes (census breaks, caveats)."""

    model_config = _forbid_extra()

    sources: list[SourceCompliance] = Field(min_length=1)
    notes: str | None = None


class Recipe(BaseModel):
    """The recipe file. ``features`` stays the raw mloda array so it reaches the loader verbatim."""

    model_config = _forbid_extra()

    features: list[str | dict[str, Any]] = Field(min_length=1)
    links: list[LinkSpec] = Field(default_factory=list)
    compliance: Compliance

    @field_validator("features")
    @classmethod
    def _feature_items(cls, value: list[str | dict[str, Any]]) -> list[str | dict[str, Any]]:
        allowed = set(FeatureItem.model_fields)
        for position, item in enumerate(value):
            if isinstance(item, str):
                if not item:
                    raise ValueError(f"features[{position}]: a feature name must not be empty")
                continue
            unknown = sorted(set(item) - allowed)
            if unknown:
                raise ValueError(
                    f"features[{position}]: unknown key(s) {unknown}; mloda feature items allow {sorted(allowed)}"
                )
            try:
                FeatureItem.model_validate(item)
            except ValidationError as exc:
                raise ValueError(f"features[{position}]: {error_summary(exc)}") from None
        return value

    @field_validator("links")
    @classmethod
    def _no_duplicate_links(cls, value: list[LinkSpec]) -> list[LinkSpec]:
        for position, spec in enumerate(value):
            for earlier in range(position):
                if value[earlier] == spec:
                    raise ValueError(f"links[{position}] repeats links[{earlier}]")
        return value

    @model_validator(mode="after")
    def _no_credentials(self) -> Recipe:
        reject_credentials(self.model_dump(mode="json"))
        return self
