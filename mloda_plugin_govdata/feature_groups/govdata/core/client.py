"""HTTP client and retry policy for GovData / publisher requests."""

from __future__ import annotations

import importlib.metadata
from typing import Any

import httpx
from tenacity import RetryCallState, retry, retry_if_exception, stop_after_attempt, wait_exponential_jitter

# Four-part timeout: distinct connect / read / write / pool budgets.
DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=10.0)
RETRYABLE_STATUS: frozenset[int] = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 5
MAX_RETRY_AFTER = 60.0  # cap a server's Retry-After so it cannot stall the client for hours

_BASE_WAIT = wait_exponential_jitter(initial=0.5, max=10.0)


def _user_agent() -> str:
    try:
        version = importlib.metadata.version("mloda-plugin-govdata")
    except importlib.metadata.PackageNotFoundError:
        version = "0.0.0"
    return f"mloda-plugin-govdata/{version} (+https://github.com/mloda-ai/mloda-plugin-govdata)"


def build_client(*, timeout: httpx.Timeout = DEFAULT_TIMEOUT) -> httpx.Client:
    """A pooled httpx client with the polite User-Agent and timeout budget."""
    return httpx.Client(timeout=timeout, headers={"User-Agent": _user_agent()}, follow_redirects=True)


class RetryableStatusError(Exception):
    """Raised internally so a retryable status code triggers a tenacity retry."""

    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.retry_after = _parse_retry_after(response)
        super().__init__(f"retryable status {response.status_code} for {response.request.url}")


def _parse_retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return float(raw)  # seconds form; HTTP-date form is not honored
    except ValueError:
        return None


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, (httpx.TransportError, RetryableStatusError))


def _wait(state: RetryCallState) -> float:
    base = _BASE_WAIT(state)
    outcome = state.outcome
    if outcome is not None:
        exc = outcome.exception()
        if isinstance(exc, RetryableStatusError) and exc.retry_after is not None:
            return max(base, min(exc.retry_after, MAX_RETRY_AFTER))
    return base


@retry(retry=retry_if_exception(_is_retryable), wait=_wait, stop=stop_after_attempt(MAX_ATTEMPTS), reraise=True)
def request_with_retry(client: httpx.Client, method: str, url: str, **kwargs: Any) -> httpx.Response:
    """Issue a request, retrying transport errors and retryable status codes."""
    response = client.request(method, url, **kwargs)
    if response.status_code in RETRYABLE_STATUS:
        raise RetryableStatusError(response)
    return response
