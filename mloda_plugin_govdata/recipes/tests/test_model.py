"""Recipe model: file shape, unknown keys, compliance fields, and credential rejection."""

import dataclasses
import json
from typing import Any

import pytest

from mloda_plugin_govdata.recipes import FeatureItem, Recipe, RecipeError, parse_recipe
from mloda_plugin_govdata.recipes.credential_scan import TOKEN_RUN_LENGTH, environment_secrets

LOCATOR = {"name": "12411-0010", "startyear": 2024, "endyear": 2024}
SOURCE: dict[str, Any] = {
    "license": "DL-DE-BY-2.0",
    "attribution": "(c) Statistisches Bundesamt (Destatis), 2026",
    "dataset_uri": "https://genesis.destatis.de/datenbank/online/statistic/12411/table/12411-0010",
    "retrieved_at": "2026-09-08T00:00:00Z",
    "sha256": "aba0f99e3b8eef1f4d975c0e2ed3d7323024dd8a798dbd875e35ae34447f3916",
    "modifications": [],
    "credential_env": ["GENESIS_TOKEN"],
}
SIDE = {"feature_group": "GovDataFeature", "index": ["Nr"]}
# Built, not pasted, so no token-shaped literal sits in the source tree.
TOKEN_LIKE = "t0ken" + "Ab1" * 8
GENESIS_ENV = ("GENESIS_TOKEN", "GENESIS_USER", "GENESIS_PASSWORD")


def _recipe(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "features": [{"name": "value", "options": {"DestatisReader": dict(LOCATOR)}}],
        "links": [],
        "compliance": {"sources": [dict(SOURCE)]},
    }
    document.update(overrides)
    return document


def _source(**overrides: Any) -> dict[str, Any]:
    source = dict(SOURCE)
    source.update(overrides)
    return source


def _link(discriminator: Any = None, join: str = "inner") -> dict[str, Any]:
    right = dict(SIDE, discriminator=discriminator) if discriminator is not None else dict(SIDE)
    return {"join": join, "left": dict(SIDE), "right": right}


def _rejects(document: dict[str, Any], match: str) -> RecipeError:
    with pytest.raises(RecipeError, match=match) as excinfo:
        parse_recipe(json.dumps(document))
    return excinfo.value


@pytest.fixture(autouse=True)
def _no_genesis_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in GENESIS_ENV:
        monkeypatch.delenv(name, raising=False)


def test_feature_item_fields_mirror_mloda_feature_config() -> None:
    from mloda.core.api.feature_config.models import FeatureConfig

    assert set(FeatureItem.model_fields) == {f.name for f in dataclasses.fields(FeatureConfig)}


def test_feature_item_mirrors_mloda_cross_field_rules() -> None:
    _rejects(
        _recipe(features=[{"name": "x", "options": {"a": 1}, "group_options": {"b": 2}}]),
        r"features\[0\]: options cannot be combined with group_options or context_options",
    )
    _rejects(
        _recipe(features=[{"name": "x", "propagate_context_keys": ["c"]}]),
        r"features\[0\]: propagate_context_keys needs context_options",
    )
    _rejects(
        _recipe(features=[{"name": "x", "cascade_context_keys": ["c"]}]),
        r"features\[0\]: cascade_context_keys needs context_options",
    )


def test_minimal_recipe_validates_and_links_default_to_empty() -> None:
    recipe = Recipe.model_validate({"features": ["value"], "compliance": {"sources": [SOURCE]}})
    assert recipe.links == []
    assert recipe.features == ["value"]


def test_a_top_level_unknown_key_is_rejected() -> None:
    _rejects(_recipe(notes="census break"), "notes: Extra inputs are not permitted")


def test_features_must_be_a_non_empty_array() -> None:
    _rejects(_recipe(features=[]), "features: List should have at least 1 item")
    _rejects(_recipe(features={"name": "value"}), "features")


def test_an_unknown_key_inside_a_feature_item_names_it_and_the_allowed_keys() -> None:
    error = _rejects(_recipe(features=[{"name": "value", "bogus": 1}]), r"features\[0\]: unknown key\(s\) \['bogus'\]")
    assert (
        "'column_index', 'context_options', 'feature_group', 'group_options', 'implementation', 'in_features', 'name'"
        in str(error)
    )


def test_feature_item_types_are_checked() -> None:
    _rejects(_recipe(features=[{"name": "value", "in_features": "a"}]), r"features\[0\]: in_features: Input should be")


def test_empty_feature_names_are_rejected() -> None:
    _rejects(_recipe(features=[""]), r"features\[0\]: a feature name must not be empty")
    _rejects(_recipe(features=[{"name": ""}]), r"features\[0\]: name: String should have at least 1 character")


def test_compliance_is_required_with_at_least_one_source() -> None:
    document = _recipe()
    del document["compliance"]
    _rejects(document, "compliance: Field required")
    _rejects(_recipe(compliance={"sources": []}), "compliance.sources: List should have at least 1 item")


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("sha256", "ABA0F99E", "64 lower-case hex digits"),
        ("sha256", "g" * 64, "64 lower-case hex digits"),
        ("retrieved_at", "2026-09-08T00:00:00", "timezone"),
        ("retrieved_at", "yesterday", "retrieved_at"),
        ("dataset_uri", "genesis.destatis.de/12411-0010", "URI with a scheme"),
        ("license", "", "at least 1 character"),
        ("credential_env", ["genesis_token"], r"env-var names only \(e.g. GENESIS_TOKEN\); entries \[0\] are not"),
        ("credential_env", ["GENESIS_TOKEN", "GENESIS TOKEN"], r"entries \[1\] are not"),
        ("credential_env", "GENESIS_TOKEN", "credential_env"),
    ],
)
def test_source_compliance_fields_are_validated(field: str, value: Any, match: str) -> None:
    _rejects(_recipe(compliance={"sources": [_source(**{field: value})]}), match)


def test_link_join_must_be_a_supported_type() -> None:
    _rejects(
        _recipe(links=[_link(join="asof")]),
        "links.0.join: Input should be 'inner', 'left', 'right', 'outer', 'append' or 'union'",
    )


def test_link_index_needs_a_column_name() -> None:
    side = {"feature_group": "GovDataFeature", "index": []}
    _rejects(_recipe(links=[{"join": "inner", "left": side, "right": side}]), "index: List should have at least 1 item")
    side = {"feature_group": "GovDataFeature", "index": [""]}
    _rejects(_recipe(links=[{"join": "inner", "left": side, "right": side}]), "non-empty strings")


def test_links_that_differ_only_by_discriminator_are_accepted() -> None:
    # mloda's Link equality and hash include discriminators, so both survive run_all's links set.
    same_shape = [
        _link({"BundeswahlleiterinReader": "https://a/kerg.csv"}),
        _link({"BundeswahlleiterinReader": "https://b/kerg.csv"}),
    ]
    assert len(Recipe.model_validate(_recipe(links=same_shape)).links) == 2


def test_an_exact_duplicate_link_is_rejected() -> None:
    _rejects(_recipe(links=[_link(), _link()]), r"links\[1\] repeats links\[0\]")
    Recipe.model_validate(_recipe(links=[_link(), _link(join="left")]))


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "username",
        "token",
        "GENESIS_TOKEN",
        "genesis_credentials",
        "api_key",
        "apikey",
        "client_secret",
        "user",
        "genesis_user",
        "auth",
        "Authorization",
        "login",
        "credential_env",
    ],
)
def test_a_credential_named_key_is_rejected_wherever_it_appears(key: str) -> None:
    _rejects(_recipe(features=[{"name": "value", "options": {key: "x"}}]), f"{key!r} names a credential")
    _rejects(
        _recipe(features=[{"name": "value", "options": {"DestatisReader": dict(LOCATOR, **{key: "x"})}}]),
        f"options.DestatisReader.{key}: {key!r} names a credential",
    )
    _rejects(_recipe(features=[{"name": "value", "context_options": {key: "x"}}]), f"{key!r} names a credential")
    _rejects(_recipe(links=[_link({key: "x"})]), f"links\\[0\\].right.discriminator.{key}: {key!r} names a credential")


@pytest.mark.parametrize("key", ["author", "userland", "authored_by", "pwdless"])
def test_ordinary_keys_near_the_credential_words_pass(key: str) -> None:
    Recipe.model_validate(_recipe(features=[{"name": "value", "options": {key: "x"}}]))


def test_a_token_shaped_value_is_rejected_wherever_it_appears() -> None:
    message = f"looks like an API token \\({TOKEN_RUN_LENGTH} or more letters and digits"
    _rejects(_recipe(features=[{"name": "value", "options": {"DestatisReader": TOKEN_LIKE}}]), message)
    _rejects(_recipe(features=[TOKEN_LIKE]), message)
    _rejects(_recipe(features=[{"name": "value", "options": {"url": f"https://host/data?key={TOKEN_LIKE}"}}]), message)
    _rejects(_recipe(compliance={"sources": [_source(attribution=TOKEN_LIKE)]}), message)
    _rejects(_recipe(compliance={"sources": [_source(modifications=[TOKEN_LIKE])]}), message)
    _rejects(_recipe(compliance={"sources": [SOURCE], "notes": f"see {TOKEN_LIKE}"}), message)
    _rejects(_recipe(links=[_link({"BundeswahlleiterinReader": TOKEN_LIKE})]), message)
    _rejects(
        _recipe(features=[{"name": "value", "options": {TOKEN_LIKE: "x"}}]),
        r"features\[0\].options: a key looks like an API token",
    )


def test_a_key_named_like_an_exempt_compliance_field_is_not_exempt() -> None:
    _rejects(_recipe(features=[{"name": "value", "options": {"sha256": TOKEN_LIKE}}]), "looks like an API token")
    _rejects(
        _recipe(features=[{"name": "value", "options": {"DestatisReader": dict(LOCATOR, sha256=TOKEN_LIKE)}}]),
        "looks like an API token",
    )
    _rejects(_recipe(links=[_link({"sha256": TOKEN_LIKE})]), "looks like an API token")
    _rejects(_recipe(compliance={"sources": [_source(sha256=TOKEN_LIKE + "a" * (64 - len(TOKEN_LIKE)))]}), "hex digits")


@pytest.mark.parametrize(
    "value",
    [
        "1" * 40,  # digits only: an id, not a token
        "Donaudampfschifffahrtsgesellschaft",  # letters only
        "einwohner-nach-altersgruppen-und-stadtbezirken",  # slug
        "550e8400-e29b-41d4-a716-446655440000",  # a CKAN dataset id can be a UUID
        "https://www.bundeswahlleiterin.de/bundestagswahlen/2025/ergebnisse/opendata/btw25/csv/kerg.csv",
        "https://www.umweltbundesamt.de/api/air_data/v4/measures/json?date_from=2025-01-01&station=143&component=3",
        "2026-09-08T12:34:56+00:00",
        "Wahlberechtigte Erststimmen Endgültig",
        "Ab1" * 7,  # one short of the threshold
    ],
)
def test_ordinary_values_pass_the_token_shape(value: str) -> None:
    recipe = Recipe.model_validate(_recipe(features=[{"name": "value", "options": {"reader": value}}]))
    assert recipe.features[0] == {"name": "value", "options": {"reader": value}}


def test_the_sha256_field_is_exempt_but_a_hash_elsewhere_is_not() -> None:
    Recipe.model_validate(_recipe())
    _rejects(_recipe(compliance={"sources": [_source(attribution=SOURCE["sha256"])]}), "looks like an API token")


def test_a_url_with_credentials_in_front_of_the_host_is_rejected() -> None:
    message = "URL carries credentials in front of the host"
    _rejects(
        _recipe(features=[{"name": "v", "options": {"GovDataReader": "https://user:pw@ckan.govdata.de/x"}}]), message
    )
    _rejects(_recipe(compliance={"sources": [_source(dataset_uri="https://user@host/x")]}), message)
    Recipe.model_validate(_recipe(features=[{"name": "v", "options": {"GovDataReader": "https://host/x@y"}}]))


def test_values_of_the_environments_own_credentials_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENESIS_TOKEN", "sekret-value-1")
    monkeypatch.setenv("REGIONALSTATISTIK_PASSWORD", "p@ss w0rd!")
    uri = "https://genesis.destatis.de/x?token=SEKRET-value-1"
    _rejects(_recipe(compliance={"sources": [_source(dataset_uri=uri)]}), "value of a GENESIS credential")
    encoded = {"name": "value", "options": {"DestatisReader": "https://host/?p=p%40ss%20w0rd%21"}}
    _rejects(_recipe(features=[encoded]), "value of a GENESIS credential")
    _rejects(
        _recipe(features=[{"name": "value", "options": {"sekret-value-1": "x"}}]),
        r"features\[0\].options: a key contains a value of a GENESIS credential",
    )
    Recipe.model_validate(_recipe())


def test_a_plain_word_user_name_is_not_scanned_but_an_identifier_shaped_one_is(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENESIS_USER", "destatis")
    Recipe.model_validate(_recipe())
    monkeypatch.setenv("GENESIS_USER", "max.mustermann@example.org")
    _rejects(_recipe(compliance={"sources": [SOURCE], "notes": "ask Max.Mustermann@example.org"}), "GENESIS credential")


def test_environment_secrets_cover_known_hosts_and_skip_short_or_word_like_values() -> None:
    environ = {
        "GENESIS_TOKEN": "abc",
        "REGIONALSTATISTIK_USER": "max.mustermann@example.org",
        "GENESIS_USER": "Max Mustermann",
        "GENESIS_PASSWORD": "Statistisches",
        "OTHER_TOKEN": "long-enough-value",
    }
    secrets = environment_secrets(environ)
    assert "max.mustermann@example.org" in secrets
    assert "max.mustermann%40example.org" in secrets
    assert "statistisches" in secrets
    assert "max mustermann" not in secrets
    assert "abc" not in secrets
    assert not any("long-enough" in secret for secret in secrets)


def test_error_messages_never_echo_the_rejected_value(monkeypatch: pytest.MonkeyPatch) -> None:
    cases: list[tuple[dict[str, Any], str]] = [
        (_recipe(features=[{"name": "value", "options": {"DestatisReader": TOKEN_LIKE}}]), "API token"),
        (_recipe(features=[{"name": "value", "options": {TOKEN_LIKE: "x"}}]), "API token"),
        (_recipe(features=[{"name": TOKEN_LIKE, "bogus": 1}]), "unknown key"),
        (_recipe(features=[{"name": "value", "in_features": TOKEN_LIKE}]), "in_features"),
        (_recipe(compliance={"sources": [_source(dataset_uri=TOKEN_LIKE)]}), "URI with a scheme"),
        (_recipe(compliance={"sources": [_source(credential_env=[TOKEN_LIKE])]}), "env-var names only"),
        (_recipe(compliance={"sources": [_source(credential_env=["hunter2-passphrase"])]}), "env-var names only"),
    ]
    for document, match in cases:
        error = _rejects(document, match)
        assert TOKEN_LIKE not in str(error) and "hunter2" not in str(error)
    monkeypatch.setenv("GENESIS_TOKEN", "sekret-value-1")
    for document in (
        _recipe(compliance={"sources": [SOURCE], "notes": "sekret-value-1"}),
        _recipe(features=[{"name": "value", "options": {"sekret-value-1": "x"}}]),
        _recipe(features=[{"name": "value", "options": {"sekret-value-1": {"nested": "x"}}}]),
    ):
        error = _rejects(document, "GENESIS credential")
        assert "sekret" not in str(error).lower()
