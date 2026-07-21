"""Level 1: retry policy for transient transport / status failures."""

import httpx
import pytest
import respx

from mloda_plugin_govdata.feature_groups.govdata.core.client import (
    RetryableStatusError,
    build_client,
    request_with_retry,
)

URL = "https://example.org/x"


@pytest.fixture(autouse=True)
def _instant_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    # Collapse tenacity's backoff to zero so retry tests run instantly.
    monkeypatch.setattr(
        "mloda_plugin_govdata.feature_groups.govdata.core.client._BASE_WAIT",
        lambda _state: 0.0,
    )


@respx.mock
def test_retries_on_503_then_succeeds() -> None:
    responses = [httpx.Response(503), httpx.Response(503), httpx.Response(200, content=b"ok")]
    route = respx.get(URL).mock(side_effect=responses)
    with build_client() as client:
        response = request_with_retry(client, "GET", URL)
    assert response.status_code == 200
    assert route.call_count == 3


@respx.mock
def test_no_retry_on_404() -> None:
    route = respx.get(URL).mock(return_value=httpx.Response(404))
    with build_client() as client:
        response = request_with_retry(client, "GET", URL)
    assert response.status_code == 404
    assert route.call_count == 1


@respx.mock
def test_gives_up_after_max_attempts() -> None:
    route = respx.get(URL).mock(return_value=httpx.Response(503))
    with build_client() as client, pytest.raises(RetryableStatusError):
        request_with_retry(client, "GET", URL)
    assert route.call_count == 5
