"""Level 1/2: CKAN discovery, metadata model, and license resolution."""

import json
from pathlib import Path

import httpx
import pytest
import respx

from mloda_plugin_govdata.feature_groups.govdata.core.client import build_client
from mloda_plugin_govdata.feature_groups.govdata.core.discovery import (
    Dataset,
    Resource,
    _select_resource,
    normalize_license,
    resolve_distribution,
    search_datasets,
)
from mloda_plugin_govdata.feature_groups.govdata.core.locator import GovDataLocator

PACKAGE_SHOW = "https://ckan.govdata.de/api/3/action/package_show"
PACKAGE_SEARCH = "https://ckan.govdata.de/api/3/action/package_search"
SLUG = "einwohner-nach-altersgruppen-und-stadtbezirken"


def test_normalize_license_known_and_free_text() -> None:
    assert normalize_license("http://dcat-ap.de/def/licenses/cc-by/4.0") == "CC-BY-4.0"
    # dataset-level spelling drift (underscore) normalizes to the resource-level label.
    assert normalize_license("http://dcat-ap.de/def/licenses/dl-by-de/2_0") == "DL-DE-BY-2.0"
    assert normalize_license("Es gelten keine Zugriffsbeschränkungen") == "Es gelten keine Zugriffsbeschränkungen"
    assert normalize_license(None) is None


def test_dataset_from_ckan_fixture(fixtures_dir: Path) -> None:
    payload = json.loads((fixtures_dir / "package_show.json").read_text(encoding="utf-8"))
    dataset = Dataset.from_ckan(payload["result"])
    assert dataset.name == SLUG
    assert dataset.resources[0].license == "http://dcat-ap.de/def/licenses/cc-by/4.0"
    assert dataset.resources[0].format == "CSV"
    assert "modified" in dataset.extras  # DCAT freshness extra is preserved


@respx.mock
def test_resolve_distribution_reads_license_from_distribution(fixtures_dir: Path) -> None:
    payload = (fixtures_dir / "package_show.json").read_text(encoding="utf-8")
    route = respx.get(PACKAGE_SHOW).mock(return_value=httpx.Response(200, text=payload))
    with build_client() as client:
        resolved = resolve_distribution(GovDataLocator(dataset_id=SLUG), client)
    assert route.called
    assert resolved.license == "CC-BY-4.0"
    assert resolved.url.endswith(".csv")


def test_resolve_direct_url_skips_discovery() -> None:
    with build_client() as client:
        resolved = resolve_distribution(GovDataLocator(distribution_url="https://example.org/data.csv"), client)
    assert resolved.url == "https://example.org/data.csv"
    assert resolved.license is None


def test_select_resource_prefers_csv_over_first_non_csv() -> None:
    resources = [
        Resource(url="https://example.org/page.html", format="HTML"),
        Resource(url="https://example.org/data.csv", format="CSV"),
    ]
    assert _select_resource(resources, 0).url.endswith(".csv")


def _search_page(count: int, names: list[str]) -> httpx.Response:
    results = [{"name": name, "title": name.replace("-", " "), "resources": []} for name in names]
    return httpx.Response(200, json={"success": True, "result": {"count": count, "results": results}})


@respx.mock
def test_search_datasets_paginates_until_count() -> None:
    route = respx.get(PACKAGE_SEARCH).mock(
        side_effect=[_search_page(3, ["ds-a", "ds-b"]), _search_page(3, ["ds-c"])],
    )
    with build_client() as client:
        names = [d.name for d in search_datasets(client, "einwohner", page_size=2)]
    assert names == ["ds-a", "ds-b", "ds-c"]
    assert route.call_count == 2
    first, second = route.calls
    assert dict(first.request.url.params) == {"q": "einwohner", "rows": "2", "start": "0"}
    assert dict(second.request.url.params) == {"q": "einwohner", "rows": "2", "start": "2"}


@respx.mock
def test_search_datasets_empty_result() -> None:
    route = respx.get(PACKAGE_SEARCH).mock(return_value=_search_page(0, []))
    with build_client() as client:
        assert list(search_datasets(client, "no-such-dataset")) == []
    assert route.call_count == 1


@respx.mock
def test_search_datasets_unsuccessful_payload_raises() -> None:
    respx.get(PACKAGE_SEARCH).mock(return_value=httpx.Response(200, json={"success": False}))
    with build_client() as client:
        with pytest.raises(ValueError, match="package_search"):
            list(search_datasets(client, "einwohner"))


@respx.mock
def test_search_datasets_caps_at_max_results_and_requests_no_extra_rows() -> None:
    route = respx.get(PACKAGE_SEARCH).mock(return_value=_search_page(5, ["ds-a", "ds-b"]))
    with build_client() as client:
        names = [d.name for d in search_datasets(client, "einwohner", page_size=100, max_results=2)]
    assert names == ["ds-a", "ds-b"]
    assert route.call_count == 1
    assert dict(route.calls[0].request.url.params) == {"q": "einwohner", "rows": "2", "start": "0"}


@respx.mock
def test_search_datasets_stops_on_stalled_server_page() -> None:
    # A server whose count promises more than it delivers must not loop forever.
    route = respx.get(PACKAGE_SEARCH).mock(
        side_effect=[_search_page(10, ["ds-a"]), _search_page(10, [])],
    )
    with build_client() as client:
        names = [d.name for d in search_datasets(client, "einwohner", page_size=1)]
    assert names == ["ds-a"]
    assert route.call_count == 2


@respx.mock
def test_search_datasets_shrinks_rows_near_max_results_and_honors_ckan_base() -> None:
    custom_search = "https://ckan.example.org/api/3/action/package_search"
    route = respx.get(custom_search).mock(
        side_effect=[_search_page(5, ["ds-a", "ds-b"]), _search_page(5, ["ds-c"])],
    )
    with build_client() as client:
        names = [
            d.name
            for d in search_datasets(
                client,
                "einwohner",
                ckan_base="https://ckan.example.org/api/3/action",
                page_size=2,
                max_results=3,
            )
        ]
    assert names == ["ds-a", "ds-b", "ds-c"]
    assert route.call_count == 2
    # The second request only asks for the one row still allowed by max_results.
    assert dict(route.calls[1].request.url.params) == {"q": "einwohner", "rows": "1", "start": "2"}


def test_search_datasets_rejects_bad_page_size() -> None:
    with build_client() as client:
        with pytest.raises(ValueError, match="page_size"):
            list(search_datasets(client, "einwohner", page_size=0))


@pytest.mark.live
def test_live_search_finds_population_dataset() -> None:
    with build_client() as client:
        names = [d.name for d in search_datasets(client, "einwohner altersgruppen stadtbezirken", max_results=100)]
    assert SLUG in names
