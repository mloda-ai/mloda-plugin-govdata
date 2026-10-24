"""Feature objects, links, and compliance to recipe JSON (``write_recipe``); ``load.py`` reads it back."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from mloda.user import Feature, Index, Link, Options
from pydantic import ValidationError

from ..feature_groups.destatis.locator import DestatisLocator
from ..feature_groups.govdata.core.locator import DEFAULT_CKAN_BASE, GovDataLocator
from .load import realize_recipe
from .model import Compliance, JoinSide, LinkSpec, Recipe, RecipeError, error_summary

# mloda's DefaultOptionKeys.in_features is a str enum equal to this; the loader stores it in Options.context.
IN_FEATURES = "in_features"
# Feature constructor parameters the mloda feature config can carry (the rest must be at their defaults).
# domain rides in the "domain" option key: mloda reads it from there and pops it on construction.
SUPPORTED_FEATURE_PARAMETERS: frozenset[str] = frozenset(
    {"name", "options", "link", "feature_group", "domain", "implementation"}
)
# Attribute name, its default, and the option key mloda also reads it from (then it round-trips with the options).
_UNSUPPORTED: tuple[tuple[str, Any, str | None], ...] = (
    ("data_type", None, None),
    ("index", None, None),
    ("compute_frameworks", None, "compute_framework"),
    ("initial_requested_data", False, None),
    ("forward_group", None, None),
    ("forward_group_exclude", frozenset(), None),
    ("inherit_context_keys", frozenset(), None),
    ("required_declarations", None, None),
    ("keep_index", False, None),
    ("_connection_holder", None, None),
)


def build_recipe(features: Iterable[Feature | str], compliance: Compliance, links: Iterable[Link] = ()) -> Recipe:
    """Feature objects (or names), links, and compliance to a validated ``Recipe``; feature-level links are hoisted.

    The result is also run through the loader, so the writer never emits a file its own loader rejects.
    """
    feature_list = list(features)
    all_links = list(links)
    for feature in feature_list:
        if isinstance(feature, Feature) and feature.link is not None and feature.link not in all_links:
            all_links.append(feature.link)
    items = [
        feature if isinstance(feature, str) else _feature_item(feature, position)
        for position, feature in enumerate(feature_list)
    ]
    try:
        specs = [_link_spec(link, position) for position, link in enumerate(all_links)]
        recipe = Recipe(features=items, links=specs, compliance=compliance)
    except ValidationError as exc:
        raise RecipeError(error_summary(exc)) from None
    realize_recipe(recipe)
    return recipe


def recipe_to_json(recipe: Recipe) -> str:
    """Stable, human-readable JSON; the feature array is written exactly as the model holds it."""
    document = {
        "features": recipe.features,
        "links": [spec.model_dump(mode="json", exclude_none=True) for spec in recipe.links],
        "compliance": recipe.compliance.model_dump(mode="json", exclude_none=True),
    }
    return json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def write_recipe(
    path: str | Path, features: Iterable[Feature | str], compliance: Compliance, links: Iterable[Link] = ()
) -> Path:
    target = Path(path)
    target.write_text(recipe_to_json(build_recipe(features, compliance, links)), encoding="utf-8")
    return target


def _feature_item(feature: Feature, position: int) -> dict[str, Any]:
    # Position only in the writer's own errors; mloda's loader names the item after the credential scan ran.
    where = f"features[{position}]"
    options = feature.options
    # What mloda derives from the options alone; a constructor argument that differs would be lost.
    from_options = Feature(str(feature.name), options=Options(group=dict(options.group), context=dict(options.context)))
    for attribute, default, option_key in _UNSUPPORTED:
        value = getattr(feature, attribute)
        if _same(value, default) or (option_key is not None and _same(value, getattr(from_options, attribute))):
            continue
        raise RecipeError(
            f"{where}: Feature.{attribute} has no recipe form; "
            "a recipe carries name, options, in_features, feature_group, implementation, propagate_context_keys, "
            "and cascade_context_keys"
        )
    if IN_FEATURES in options.group:
        raise RecipeError(
            f"{where}: {IN_FEATURES!r} belongs in Options.context; mloda reads a dict there as a nested Feature"
        )
    group_options = dict(options.group)
    if feature.domain is not None:
        group_options["domain"] = feature.domain.name  # the loader hands it back to mloda through the same key
    group = _json_value(group_options, f"{where}.options")
    context = dict(options.context)
    in_features = context.pop(IN_FEATURES, None)
    context_json = _json_value(context, f"{where}.context_options")
    if (options.propagate_context_keys or options.cascade_context_keys) and not context_json:
        raise RecipeError(f"{where}: {IN_FEATURES!r} cannot be pushed to inputs; a recipe carries it as its own field")
    item: dict[str, Any] = {"name": str(feature.name)}
    if in_features is not None:
        item[IN_FEATURES] = _in_feature_names(in_features, where)
    if context_json:
        if group:
            item["group_options"] = group
        item["context_options"] = context_json
        if options.propagate_context_keys:
            item["propagate_context_keys"] = sorted(options.propagate_context_keys)
        if options.cascade_context_keys:
            item["cascade_context_keys"] = sorted(options.cascade_context_keys)
    elif group:
        item["options"] = group
    scope = feature.feature_group_scope
    if scope is not None:
        item["feature_group"] = scope if isinstance(scope, str) else scope.get_class_name()
    pin = feature.implementation_pin
    if pin is not None:
        item["implementation"] = pin[0] if len(pin) == 1 else list(pin)
    return item


def _same(value: Any, other: Any) -> bool:
    # Index.__eq__ raises on a non-Index, so identity comes first and None never reaches __eq__.
    if value is other:
        return True
    if value is None or other is None:
        return False
    return bool(value == other)


def _in_feature_names(value: Any, where: str) -> list[str]:
    if isinstance(value, Feature):
        raise RecipeError(f"{where}: in_features must be feature names; a nested Feature has no config form")
    if not isinstance(value, (str, list, tuple, set, frozenset)):
        raise RecipeError(f"{where}: in_features must be a name, or a list, tuple or set of names")
    names = [name.strip() for name in value.split(",")] if isinstance(value, str) else list(value)
    if not all(isinstance(name, str) and name for name in names):
        raise RecipeError(f"{where}: in_features must be feature names; a nested Feature has no config form")
    # mloda keeps operand order, so only an unordered set is sorted (for a stable file).
    return sorted(names) if isinstance(value, (set, frozenset)) else names


def _json_value(value: Any, where: str) -> Any:
    """The JSON-safe subset of option values; a locator becomes its string or dict form."""
    if isinstance(value, float) and not math.isfinite(value):
        raise RecipeError(f"{where}: non-finite floats are not JSON")
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, DestatisLocator):
        return {key: item for key, item in value.to_dict().items() if item is not None}
    if isinstance(value, GovDataLocator):
        if value.ckan_base != DEFAULT_CKAN_BASE or value.resource_index != 0:
            raise RecipeError(
                f"{where}: a GovDataLocator with a non-default ckan_base or resource_index has no config form"
            )
        if value.dataset_id and value.distribution_url:
            raise RecipeError(f"{where}: a GovDataLocator with both dataset_id and distribution_url has no config form")
        return value.describe()
    if isinstance(value, (set, frozenset, tuple)):
        raise RecipeError(f"{where}: {type(value).__name__} values do not survive JSON; pass a list")
    if isinstance(value, list):
        return [_json_value(item, where) for item in value]
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise RecipeError(f"{where}: option key {key!r} is not a string")
            result[key] = _json_value(item, f"{where}.{key}")
        return result
    raise RecipeError(
        f"{where}: {type(value).__name__} values are not JSON-safe; pass strings, numbers, lists, dicts, or a locator"
    )


def _link_spec(link: Link, position: int) -> LinkSpec:
    where = f"links[{position}]"
    if link.asof_config is not None:
        raise RecipeError(f"{where}: asof joins have no recipe form")
    return LinkSpec.model_validate(
        {
            "join": link.jointype.value,
            "left": _join_side(link.left_feature_group, link.left_index, link.left_discriminator, f"{where}.left"),
            "right": _join_side(link.right_feature_group, link.right_index, link.right_discriminator, f"{where}.right"),
        }
    )


def _join_side(feature_group: type[Any], index: Index, discriminator: dict[str, Any] | None, where: str) -> JoinSide:
    return JoinSide(
        feature_group=feature_group.get_class_name(),
        index=list(index.index),
        discriminator=None if discriminator is None else _json_value(discriminator, f"{where}.discriminator"),
    )
