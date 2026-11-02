"""Writer and loader: the supported Feature subset round-trips, links build, and only the feature array reaches mloda."""

import inspect
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from mloda.core.abstract_plugins.components.link import JoinType
from mloda.user import Feature, Index, JoinSpec, Link, Options, load_features_from_config

from mloda_plugin_govdata.feature_groups.destatis import DestatisLocator, DestatisReader
from mloda_plugin_govdata.feature_groups.govdata import BundeswahlleiterinReader, GovDataFeature, GovDataLocator
from mloda_plugin_govdata.feature_groups.land_population_per_voter import LAND_LINK, LAND_LOCATOR
from mloda_plugin_govdata.recipes import (
    Compliance,
    RecipeError,
    SourceCompliance,
    build_recipe,
    load_recipe,
    parse_recipe,
    recipe_to_json,
    write_recipe,
)
from mloda_plugin_govdata.recipes.write import _UNSUPPORTED, SUPPORTED_FEATURE_PARAMETERS
from scripts.write_recipes import KERG_URL, LAND_SHA256

BERLIN_URL = "https://www.wahlen-berlin.de/wahlen/BE2023/AFSPRAES/agh/Datenexport_AGH2023_Zweitstimme_W_BE.csv"
COMPLIANCE = Compliance(
    sources=[
        SourceCompliance(
            license="DL-DE-BY-2.0",
            attribution="(c) Statistisches Bundesamt (Destatis), 2026",
            dataset_uri="https://genesis.destatis.de/datenbank/online/statistic/12411/table/12411-0010",
            retrieved_at=datetime(2026, 9, 8, tzinfo=UTC),
            sha256=LAND_SHA256,
            credential_env=["GENESIS_TOKEN"],
        )
    ]
)


def _features(features: list[Feature | str]) -> list[Feature]:
    assert all(isinstance(feature, Feature) for feature in features)
    return cast(list[Feature], features)


@pytest.fixture(autouse=True)
def _no_genesis_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("GENESIS_TOKEN", "GENESIS_USER", "GENESIS_PASSWORD"):
        monkeypatch.delenv(name, raising=False)


def test_round_trip_keeps_names_options_context_scope_and_plain_strings(tmp_path: Path) -> None:
    features: list[Feature | str] = [
        "plain",
        Feature("value", options=cast(dict[str, Any], {DestatisReader: DestatisLocator("12411-0010", startyear=2024)})),
        Feature("Nr", options={BundeswahlleiterinReader.__name__: KERG_URL}),
        Feature(
            "derived",
            options=Options(
                group={"k": 1, "keys": ["03159", "03152"]},
                context={"in_features": frozenset({"b", "a"}), "flag": True, "trace": "t1"},
                propagate_context_keys=frozenset({"flag"}),
                cascade_context_keys=frozenset({"trace"}),
            ),
            feature_group="GovDataFeature",
        ),
        Feature("scoped", feature_group=GovDataFeature),
        Feature("context_only", options=Options(context={"note": "x"})),
    ]

    loaded = load_recipe(write_recipe(tmp_path / "r.json", features, COMPLIANCE))

    assert loaded.features[0] == "plain"
    value, nr, derived, scoped, context_only = _features(loaded.features[1:])
    assert str(value.name) == "value"
    assert value.options.group == {
        DestatisReader.__name__: {
            "name": "12411-0010",
            "startyear": 2024,
            "quality": False,
            "host": "genesis",
            "language": "de",
        }
    }
    assert DestatisLocator.coerce(value.options.group[DestatisReader.__name__]) == DestatisLocator(
        "12411-0010", startyear=2024
    )
    assert nr.options.group == {BundeswahlleiterinReader.__name__: KERG_URL}
    assert derived.options.group == {"k": 1, "keys": ["03159", "03152"]}
    assert derived.options.context == {"in_features": ("a", "b"), "flag": True, "trace": "t1"}
    assert derived.options.propagate_context_keys == frozenset({"flag"})
    assert derived.options.cascade_context_keys == frozenset({"trace"})
    assert derived.feature_group_scope == "GovDataFeature"
    assert scoped.feature_group_scope == "GovDataFeature" and scoped.options.group == {}
    assert context_only.options.group == {} and context_only.options.context == {"note": "x"}
    assert loaded.links == []
    assert loaded.compliance == COMPLIANCE


def test_writing_a_loaded_recipe_again_gives_the_same_text() -> None:
    features: list[Feature | str] = [
        Feature("value", options={DestatisReader.__name__: LAND_LOCATOR}, link=LAND_LINK),
        Feature("Nr", options={BundeswahlleiterinReader.__name__: KERG_URL}, keep_index=True, index=Index(("Nr",))),
    ]
    first = recipe_to_json(build_recipe(features, COMPLIANCE))
    loaded = parse_recipe(first)
    second = recipe_to_json(build_recipe(loaded.features, loaded.compliance, loaded.links))
    assert first == second
    # The written index still binds the link side it names.
    assert _features(loaded.features)[1].index == loaded.links[0].right_index


def _kerg_self_link(right_url: str) -> Link:
    """A same-class link, told apart from its twins by the right discriminator."""
    return Link.inner(
        JoinSpec(BundeswahlleiterinReader, "Nr"),
        JoinSpec(BundeswahlleiterinReader, "Nr"),
        left_discriminator={BundeswahlleiterinReader.__name__: KERG_URL},
        right_discriminator={BundeswahlleiterinReader.__name__: right_url},
    )


def test_links_block_builds_the_link() -> None:
    loaded = parse_recipe(recipe_to_json(build_recipe(["value", "Nr"], COMPLIANCE, [LAND_LINK])))

    (link,) = loaded.links
    assert link.jointype is JoinType.INNER
    assert link.left_feature_group is DestatisReader and link.right_feature_group is BundeswahlleiterinReader
    assert link.left_index == Index(("1_variable_attribute_code",)) and link.right_index == Index(("Nr",))
    assert link == LAND_LINK


def test_links_block_builds_discriminators() -> None:
    # A dict locator (the DestatisLocator form) as well as a string one.
    destatis_self = Link.inner(
        JoinSpec(DestatisReader, "time"),
        JoinSpec(DestatisReader, "time"),
        left_discriminator={DestatisReader.__name__: LAND_LOCATOR},
        right_discriminator={DestatisReader.__name__: "12411-0015"},
    )
    links = [_kerg_self_link(BERLIN_URL), destatis_self]
    loaded = parse_recipe(recipe_to_json(build_recipe(["Nr"], COMPLIANCE, links)))

    kerg, destatis = loaded.links
    assert kerg.left_discriminator == {BundeswahlleiterinReader.__name__: KERG_URL}
    assert kerg.right_discriminator == {BundeswahlleiterinReader.__name__: BERLIN_URL}
    assert destatis.left_discriminator == {DestatisReader.__name__: LAND_LOCATOR}
    assert loaded.links == links


def test_a_same_name_key_link_and_a_multi_column_index_round_trip() -> None:
    same_key = Link.left(
        JoinSpec(BundeswahlleiterinReader, ("Nr", "Gebiet")),
        JoinSpec(BundeswahlleiterinReader, ("Nr", "Gebiet")),
        left_discriminator={BundeswahlleiterinReader.__name__: KERG_URL},
        right_discriminator={BundeswahlleiterinReader.__name__: BERLIN_URL},
    )
    loaded = parse_recipe(recipe_to_json(build_recipe(["Nr"], COMPLIANCE, [same_key])))
    (link,) = loaded.links
    assert link.jointype is JoinType.LEFT
    assert link.left_index == link.right_index == Index(("Nr", "Gebiet"))
    assert link.left_discriminator != link.right_discriminator


def test_a_feature_level_link_is_hoisted_once() -> None:
    features: list[Feature | str] = [
        Feature("value", options={DestatisReader.__name__: LAND_LOCATOR}, link=LAND_LINK),
        Feature("Nr", options={BundeswahlleiterinReader.__name__: KERG_URL}, link=LAND_LINK),
    ]
    recipe = build_recipe(features, COMPLIANCE, [LAND_LINK])
    assert len(recipe.links) == 1
    loaded = parse_recipe(recipe_to_json(recipe))
    assert all(isinstance(feature, Feature) and feature.link is None for feature in loaded.features)


def test_links_that_differ_only_by_discriminator_stay_distinct() -> None:
    # mloda's Link equality includes discriminators, so both survive a recipe's links block and run_all(links=...).
    first, other = _kerg_self_link(BERLIN_URL), _kerg_self_link(KERG_URL)
    assert len({first, other}) == 2
    recipe = build_recipe(["Nr"], COMPLIANCE, [first, other])
    loaded = parse_recipe(recipe_to_json(recipe))
    assert set(loaded.links) == {first, other}


def test_two_feature_level_links_differing_only_by_discriminator_both_hoist() -> None:
    first, other = _kerg_self_link(BERLIN_URL), _kerg_self_link(KERG_URL)
    features: list[Feature | str] = [Feature("Gebiet", link=first), Feature("Nr", link=other)]
    recipe = build_recipe(features, COMPLIANCE)
    assert len(recipe.links) == 2
    loaded = parse_recipe(recipe_to_json(recipe))
    assert set(loaded.links) == {first, other}


def test_an_unknown_feature_group_in_the_links_block_is_named() -> None:
    text = recipe_to_json(build_recipe(["Nr"], COMPLIANCE, [LAND_LINK])).replace("DestatisReader", "NoSuchFeature", 1)
    with pytest.raises(RecipeError, match=r"links\[0\].left: no FeatureGroup named 'NoSuchFeature' is loaded"):
        parse_recipe(text)


def test_an_asof_link_has_no_recipe_form() -> None:
    asof = Link.asof(
        JoinSpec(BundeswahlleiterinReader, "Nr"),
        JoinSpec(BundeswahlleiterinReader, "Nr"),
        left_time_column="t",
        right_time_column="t",
    )
    with pytest.raises(RecipeError, match=r"links\[0\]: asof joins have no recipe form"):
        build_recipe(["Nr"], COMPLIANCE, [asof])


def test_every_feature_constructor_parameter_is_either_carried_or_refused() -> None:
    parameters = set(inspect.signature(Feature.__init__).parameters) - {"self"}
    # Constructor name where the attribute differs.
    renamed = {"compute_frameworks": "compute_framework", "_connection_holder": "connection"}
    refused = {renamed.get(attribute, attribute) for attribute, _, _ in _UNSUPPORTED}
    assert parameters == SUPPORTED_FEATURE_PARAMETERS | refused
    # The writer carries every Options field; a new one must be written or refused, never dropped.
    assert set(inspect.signature(Options.__init__).parameters) - {"self"} == {
        "group",
        "context",
        "propagate_context_keys",
        "cascade_context_keys",
    }


@pytest.mark.parametrize(
    ("feature", "attribute"),
    [
        (Feature("x", data_type="INT64"), "data_type"),
        (Feature("x", compute_framework="PyArrowTable"), "compute_frameworks"),
        (Feature("x", initial_requested_data=True), "initial_requested_data"),
        (Feature("x", forward_group=False), "forward_group"),
        (Feature("x", forward_group=["k"]), "forward_group"),
        (Feature("x", forward_group_exclude=["k"]), "forward_group_exclude"),
        (Feature("x", inherit_context_keys=["k"]), "inherit_context_keys"),
        (Feature("x", required_declarations={"k": "v"}), "required_declarations"),
        (Feature("x", connection=sqlite3.connect(":memory:")), "_connection_holder"),
    ],
)
def test_feature_attributes_without_a_config_field_raise_instead_of_being_dropped(
    feature: Feature, attribute: str
) -> None:
    with pytest.raises(RecipeError, match=rf"features\[0\]: Feature.{attribute} has no recipe form"):
        build_recipe([feature], COMPLIANCE)


@pytest.mark.parametrize("keys", ["propagate_context_keys", "cascade_context_keys"])
def test_pushing_only_in_features_raises_instead_of_being_dropped(keys: str) -> None:
    pushed = frozenset({"in_features"})
    options = Options(
        context={"in_features": ("a",)},
        propagate_context_keys=pushed if keys == "propagate_context_keys" else None,
        cascade_context_keys=pushed if keys == "cascade_context_keys" else None,
    )
    with pytest.raises(RecipeError, match=r"features\[0\]: 'in_features' cannot be pushed"):
        build_recipe([Feature("x", options=options)], COMPLIANCE)


def test_domain_and_compute_framework_given_as_options_round_trip() -> None:
    feature = Feature("x", options={"domain": "d", "compute_framework": "PyArrowTable"})
    (loaded,) = _features(parse_recipe(recipe_to_json(build_recipe([feature], COMPLIANCE))).features)
    assert loaded.options.group.get("compute_framework") == "PyArrowTable"
    assert loaded.domain == feature.domain and loaded.compute_frameworks == feature.compute_frameworks


@pytest.mark.parametrize("pin", ["PandasAggregation", ["PandasAggregation", "PyArrowAggregation"]])
def test_an_implementation_pin_round_trips(pin: str | list[str]) -> None:
    recipe = build_recipe([Feature("x", implementation=pin)], COMPLIANCE)
    assert recipe.features[0] == {"name": "x", "implementation": pin}
    (loaded,) = parse_recipe(recipe_to_json(recipe)).features
    assert (
        isinstance(loaded, Feature) and loaded.implementation_pin == Feature("x", implementation=pin).implementation_pin
    )


@pytest.mark.parametrize(
    ("feature", "written"),
    [
        (Feature("x", keep_index=True, index=Index(("a",))), {"name": "x", "keep_index": True, "index": ["a"]}),
        (Feature("x", keep_index=True), {"name": "x", "keep_index": True}),
        (Feature("x", index=Index(("a", "b"))), {"name": "x", "index": ["a", "b"]}),
        (
            Feature("x", options=Options(group={"k": 1}, context={"c": 2}), keep_index=True, index=Index(("a",))),
            {"name": "x", "group_options": {"k": 1}, "context_options": {"c": 2}, "keep_index": True, "index": ["a"]},
        ),
    ],
)
def test_keep_index_and_index_round_trip(feature: Feature, written: dict[str, Any]) -> None:
    recipe = build_recipe([feature], COMPLIANCE)
    assert recipe.features[0] == written
    text = recipe_to_json(recipe)
    loaded = parse_recipe(text)
    # Feature equality ignores both attributes, so they are compared one by one.
    (back,) = _features(loaded.features)
    assert back.keep_index == feature.keep_index and back.index == feature.index
    assert recipe_to_json(build_recipe(loaded.features, loaded.compliance)) == text


@pytest.mark.parametrize("index", [("a",), ["a"]])
def test_an_index_that_is_not_an_index_raises(index: Any) -> None:
    with pytest.raises(RecipeError, match=r"features\[0\]: Feature.index must be an Index"):
        build_recipe([Feature("x", index=index)], COMPLIANCE)


def test_a_constructor_domain_is_written_to_the_domain_option() -> None:
    recipe = build_recipe([Feature("x", domain="d")], COMPLIANCE)
    assert recipe.features[0] == {"name": "x", "options": {"domain": "d"}}
    (loaded,) = _features(parse_recipe(recipe_to_json(recipe)).features)
    assert loaded.domain is not None and loaded.domain.name == "d"


def test_govdata_locator_instances_become_their_string_form() -> None:
    features: list[Feature | str] = [
        Feature("a", options={"GovDataReader": GovDataLocator.from_string("einwohner-stuttgart")}),
        Feature("b", options={"BundeswahlleiterinReader": GovDataLocator.from_string(KERG_URL)}),
    ]
    a, b = _features(parse_recipe(recipe_to_json(build_recipe(features, COMPLIANCE))).features)
    assert a.options.group == {"GovDataReader": "einwohner-stuttgart"}
    assert b.options.group == {"BundeswahlleiterinReader": KERG_URL}


@pytest.mark.parametrize(
    ("locator", "match"),
    [
        (GovDataLocator(dataset_id="slug", resource_index=1), "a non-default ckan_base or resource_index"),
        (GovDataLocator(dataset_id="slug", ckan_base="https://other/api"), "a non-default ckan_base or resource_index"),
        (GovDataLocator(dataset_id="slug", distribution_url=KERG_URL), "both dataset_id and distribution_url"),
    ],
)
def test_a_govdata_locator_without_a_string_form_raises(locator: GovDataLocator, match: str) -> None:
    with pytest.raises(
        RecipeError, match=rf"features\[0\].options.GovDataReader: a GovDataLocator with {match} has no config form"
    ):
        build_recipe([Feature("a", options={"GovDataReader": locator})], COMPLIANCE)


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (frozenset({Feature("a", options={"k": 1})}), "in_features must be feature names"),
        (Feature("a"), "in_features must be feature names"),
        ({"a": 1}, "in_features must be a name, or a list"),
        (3, "in_features must be a name, or a list"),
    ],
)
def test_in_features_that_are_not_names_raise(value: Any, message: str) -> None:
    feature = Feature("d", options=Options(context={"in_features": value}))
    with pytest.raises(RecipeError, match=message):
        build_recipe([feature], COMPLIANCE)


def test_in_features_in_the_group_options_raises() -> None:
    # mloda's loader turns a dict under this key into a nested Feature, so the value would change type on reload.
    feature = Feature("d", options=Options(group={"in_features": {"name": "a"}}))
    with pytest.raises(RecipeError, match=r"features\[0\]: 'in_features' belongs in Options.context"):
        build_recipe([feature], COMPLIANCE)


@pytest.mark.parametrize(
    ("value", "names"),
    [
        ("b, a", ["b", "a"]),
        (("b", "a"), ["b", "a"]),
        (["b", "a"], ["b", "a"]),
        (frozenset({"b", "a"}), ["a", "b"]),
    ],
)
def test_in_features_keep_their_order_and_a_set_is_sorted(value: Any, names: list[str]) -> None:
    feature = Feature("d", options=Options(context={"in_features": value}))
    recipe = build_recipe([feature], COMPLIANCE)
    assert recipe.features == [{"name": "d", "in_features": names}]
    (loaded,) = _features(parse_recipe(recipe_to_json(recipe)).features)
    assert loaded.options.context["in_features"] == tuple(names)


@pytest.mark.parametrize(
    ("value", "match"),
    [
        (object(), "object values are not JSON-safe"),
        (Path("x"), "values are not JSON-safe"),
        ({1: "non-string key"}, "option key 1 is not a string"),
        (("a", "b"), "tuple values do not survive JSON; pass a list"),
        (frozenset({"a"}), "frozenset values do not survive JSON; pass a list"),
        (float("nan"), "non-finite floats are not JSON"),
        ([1.0, float("inf")], "non-finite floats are not JSON"),
    ],
)
def test_values_outside_the_json_safe_subset_raise(value: Any, match: str) -> None:
    with pytest.raises(RecipeError, match=rf"features\[0\].options.*{match}"):
        build_recipe([Feature("x", options={"k": value})], COMPLIANCE)


@pytest.mark.parametrize(
    ("feature", "match"),
    [
        (
            Feature("x", options={"feature_group": "GovDataFeature", "k": 1}),
            "'feature_group' must not be a top-level key",
        ),
        (Feature("x", index=Index(("k", "k"))), "'index' must not repeat a column"),
        (Feature("x", index=Index(())), "'index' must be a non-empty array"),
    ],
)
def test_the_writer_refuses_what_its_own_loader_would_refuse(feature: Feature, match: str) -> None:
    # Passes the item model, fails inside mloda's config loader; build_recipe runs the loader so no file is written.
    with pytest.raises(RecipeError, match=f"mloda rejected the feature array: .*{match}"):
        build_recipe([feature], COMPLIANCE)


def test_only_the_feature_array_reaches_mloda(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    original = load_features_from_config

    def capture(config_str: str, format: str = "json") -> Any:
        seen.append(config_str)
        return original(config_str, format=format)

    features: list[Feature | str] = [Feature("value", options={DestatisReader.__name__: LAND_LOCATOR}), "Nr"]
    text = recipe_to_json(build_recipe(features, COMPLIANCE, [LAND_LINK]))
    monkeypatch.setattr("mloda_plugin_govdata.recipes.load.load_features_from_config", capture)

    parse_recipe(text)

    (passed,) = seen
    assert json.loads(passed) == json.loads(text)["features"]
    assert "compliance" not in passed and "links" not in passed and "sha256" not in passed


def test_load_recipe_labels_errors_with_the_path(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    with pytest.raises(RecipeError, match=rf"^{broken}: Invalid JSON"):
        load_recipe(broken)


def test_mloda_rejections_of_the_feature_array_are_wrapped() -> None:
    # A nested in_features dict without a name passes the item model but fails inside mloda's loader.
    text = recipe_to_json(build_recipe(["Nr"], COMPLIANCE)).replace(
        '"Nr"', '{"name": "d", "options": {"in_features": {}}}'
    )
    with pytest.raises(RecipeError, match="mloda rejected the feature array"):
        parse_recipe(text)
