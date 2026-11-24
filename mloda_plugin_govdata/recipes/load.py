"""Recipe JSON to mloda objects (``load_recipe``): the feature array, the ``Link`` objects, and the compliance block."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from mloda.provider import FeatureGroup
from mloda.user import Feature, Index, JoinSpec, Link, load_features_from_config
from pydantic import ValidationError

# Registration side effect: a fresh process loading a recipe must resolve GovDataFeature and the readers.
from ..feature_groups import destatis, govdata, harmonization, land_population_per_voter  # noqa: F401
from .model import Compliance, LinkSpec, Recipe, RecipeError, error_summary


@dataclass(frozen=True)
class LoadedRecipe:
    """What ``load_recipe`` returns: pass ``features`` and ``set(links)`` to ``mloda.run_all``, with the credentials
    in its ``data_access_collection``."""

    features: list[Feature | str]
    links: list[Link]
    compliance: Compliance


def parse_recipe(text: str, label: str = "recipe") -> LoadedRecipe:
    """Validate recipe JSON and turn it into mloda objects; ``label`` names the source in errors."""
    try:
        recipe = Recipe.model_validate_json(text)
    except ValidationError as exc:
        raise RecipeError(f"{label}: {error_summary(exc)}") from None
    return realize_recipe(recipe, label)


def load_recipe(path: str | Path) -> LoadedRecipe:
    source = Path(path)
    return parse_recipe(source.read_text(encoding="utf-8"), label=str(source))


def realize_recipe(recipe: Recipe, label: str = "recipe") -> LoadedRecipe:
    """A validated ``Recipe`` to mloda objects. Only the feature array reaches mloda's config loader."""
    try:
        features = load_features_from_config(json.dumps(recipe.features), format="json")
    except (TypeError, ValueError) as exc:
        raise RecipeError(f"{label}: mloda rejected the feature array: {exc}") from None
    links = [_build_link(spec, f"{label}: links[{position}]") for position, spec in enumerate(recipe.links)]
    return LoadedRecipe(features=features, links=links, compliance=recipe.compliance)


def _build_link(spec: LinkSpec, where: str) -> Link:
    left = JoinSpec(_resolve_feature_group(spec.left.feature_group, f"{where}.left"), Index(tuple(spec.left.index)))
    right = JoinSpec(_resolve_feature_group(spec.right.feature_group, f"{where}.right"), Index(tuple(spec.right.index)))
    return Link(
        spec.join, left, right, left_discriminator=spec.left.discriminator, right_discriminator=spec.right.discriminator
    )


def _resolve_feature_group(name: str, where: str) -> type[FeatureGroup]:
    matches = {cls for cls in _subclasses(FeatureGroup) if cls.get_class_name() == name}
    if not matches:
        raise RecipeError(
            f"{where}: no FeatureGroup named {name!r} is loaded; import its module before loading the recipe"
        )
    if len(matches) > 1:
        modules = sorted(f"{cls.__module__}.{cls.__qualname__}" for cls in matches)
        raise RecipeError(f"{where}: FeatureGroup name {name!r} is ambiguous: {modules}")
    return matches.pop()


def _subclasses(cls: type[FeatureGroup]) -> Iterator[type[FeatureGroup]]:
    for sub in cls.__subclasses__():
        yield sub
        yield from _subclasses(sub)
