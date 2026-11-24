"""GENESIS client: header credentials, form-encoded POST, pinned language, one request at a time.

Politeness: a per-host ``threading.Lock`` serializes calls inside one process, and a
``filelock.FileLock`` in the cache directory serializes across processes that share it. mloda's
``THREADING`` mode runs feature groups in threads of one process; ``MULTIPROCESSING`` spawns one
fresh interpreter per compute framework instance, so only the file lock reaches those.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from filelock import FileLock, Timeout

from ...govdata.core.cache import DEFAULT_CACHE_DIR
from ...govdata.core.client import OwnedHttpClient, RetryableStatusError, build_client, send_with_retry
from .auth import DestatisCredentials, resolve_credentials
from .envelope import (
    GenesisEnvelope,
    HelloWorldReply,
    InspectedReply,
    LoginCheckReply,
    inspect_response,
)
from .errors import GenesisBackendError, GenesisError, GenesisUnknownEnvelope
from .hosts import GENESIS_ONLINE, GenesisHost, resolve_host
from .redact import redact_text

__all__ = [
    "OPERATIONS",
    "GenesisClient",
    "Operation",
    "fetch_tablefile",
]

logger = logging.getLogger(__name__)

DEFAULT_LANGUAGE = "de"
LOCK_FILE_NAME = "genesis-{host}.lock"
# One attempt holds the lock for at most connect plus read timeout; anything longer is a stuck holder.
LOCK_TIMEOUT_SECONDS = 300.0


@dataclass(frozen=True)
class Operation:
    """One webservice operation as the client may call it; the contract test checks it against the spec."""

    path: str  # relative to the host base URL, e.g. "data/tablefile"
    method: str  # "GET" or "POST"
    credentials: bool  # username / password headers declared (and required)
    fields: frozenset[str]  # form fields (POST) or query parameters (GET) the client may send


CLASSIFYING_VARIABLES: tuple[str, ...] = tuple(f"classifyingvariable{i}" for i in range(1, 6))
CLASSIFYING_KEYS: tuple[str, ...] = tuple(f"classifyingkey{i}" for i in range(1, 6))

TABLEFILE_FIELDS: frozenset[str] = frozenset(
    {
        "name",
        "area",
        "compress",
        "transpose",
        "contents",
        "startyear",
        "endyear",
        "timeslices",
        "regionalvariable",
        "regionalkey",
        *CLASSIFYING_VARIABLES,
        *CLASSIFYING_KEYS,
        "format",
        "quality",
        "job",
        "stand",
        "language",
    }
)
# Sent on every data/tablefile request; not locator fields (see docs/destatis-options.md).
PINNED_TABLEFILE_FIELDS: Mapping[str, str] = {
    "format": "ffcsv",
    "job": "false",
    "compress": "false",
    "transpose": "false",
}

OPERATIONS: dict[str, Operation] = {
    "helloworld/whoami": Operation("helloworld/whoami", "GET", credentials=False, fields=frozenset()),
    "helloworld/logincheck": Operation(
        "helloworld/logincheck", "POST", credentials=True, fields=frozenset({"language"})
    ),
    "catalogue/qualitysigns": Operation(
        "catalogue/qualitysigns", "GET", credentials=False, fields=frozenset({"language"})
    ),
    "metadata/table": Operation(
        "metadata/table", "POST", credentials=True, fields=frozenset({"name", "area", "language"})
    ),
    "data/tablefile": Operation("data/tablefile", "POST", credentials=True, fields=TABLEFILE_FIELDS),
}

_process_locks: dict[tuple[str, str], threading.Lock] = {}
_process_locks_guard = threading.Lock()


def _process_lock(host: GenesisHost) -> threading.Lock:
    with _process_locks_guard:
        return _process_locks.setdefault((host.name, host.base_url), threading.Lock())


class GenesisClient(OwnedHttpClient):
    """Calls one GENESIS host with the credentials passed in; it never reads the environment."""

    def __init__(
        self,
        host: GenesisHost | str = GENESIS_ONLINE,
        credentials: DestatisCredentials | None = None,
        *,
        client: httpx.Client | None = None,
        language: str = DEFAULT_LANGUAGE,
        lock_dir: str | os.PathLike[str] | None = None,
        allow_guest: bool = False,
    ) -> None:
        self.host = resolve_host(host)
        self.language = language
        self._explicit = credentials
        self._credentials: DestatisCredentials | None = None
        # No credentials: send no headers instead of raising; for characterizing replies only (capture script).
        self.allow_guest = allow_guest
        self._owns_client = client is None
        # Redirects are also disabled per request, so an injected client cannot re-enable them.
        self._client = client if client is not None else build_client(follow_redirects=False)
        lock_root = Path(lock_dir) if lock_dir is not None else DEFAULT_CACHE_DIR
        self.lock_path = lock_root / LOCK_FILE_NAME.format(host=self.host.name)

    @property
    def credentials(self) -> DestatisCredentials:
        """Credentials for this host; raises MissingCredentialsError when none were passed."""
        if self._credentials is None:
            self._credentials = resolve_credentials(self.host, self._explicit)
        return self._credentials

    def _auth_headers(self) -> dict[str, str]:
        if self.allow_guest and self._explicit is None:
            return {}
        return self.credentials.headers()

    @contextmanager
    def _serialized(self) -> Iterator[None]:
        """One attempt at a time per host: this process's threads, then every process sharing the lock file."""
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with _process_lock(self.host):
            try:
                with FileLock(str(self.lock_path), timeout=LOCK_TIMEOUT_SECONDS):
                    yield
            except Timeout:
                raise GenesisBackendError(
                    f"Another process has held the GENESIS lock {self.lock_path} for more than {LOCK_TIMEOUT_SECONDS:g} s; "
                    "wait for it or remove a stale lock file."
                ) from None

    def request(self, endpoint: str, params: Mapping[str, str] | None = None) -> httpx.Response:
        """One request, each attempt under the lock; ``language`` is always sent, unknown fields are refused."""
        try:
            operation = OPERATIONS[endpoint]
        except KeyError:
            raise ValueError(
                f"Unknown GENESIS operation {endpoint!r}; known: {', '.join(sorted(OPERATIONS))}"
            ) from None
        sent: dict[str, str] = {}
        for key, value in (params or {}).items():
            if not isinstance(value, str):
                # The wire wants strings; str(True) would send "True" where the spec expects "true".
                raise TypeError(f"{endpoint}: value for {key!r} must be a str, got {type(value).__name__}")
            sent[str(key)] = value
        if "language" in operation.fields:
            sent.setdefault("language", self.language)
        unknown = sorted(set(sent) - operation.fields)
        if unknown:
            raise ValueError(f"{endpoint} does not declare {unknown}; allowed: {sorted(operation.fields)}")
        headers = self._auth_headers() if operation.credentials else {}
        url = self.host.url(operation.path)
        kwargs: dict[str, Any] = {"headers": headers, "follow_redirects": False}
        if operation.method == "GET":
            kwargs["params"] = sent
        else:
            kwargs["data"] = sent

        def attempt() -> httpx.Response:
            with self._serialized():
                return self._client.request(operation.method, url, **kwargs)

        try:
            return send_with_retry(attempt)
        except RetryableStatusError as exc:
            raise GenesisBackendError(
                f"GENESIS kept answering HTTP {exc.response.status_code} on {endpoint}; retry later.",
                endpoint=endpoint,
                http_status=exc.response.status_code,
            ) from None

    def call(self, endpoint: str, params: Mapping[str, str] | None = None) -> InspectedReply:
        """Request plus envelope inspection; JSON replies come back parsed, error statuses raise (redacted)."""
        response = self.request(endpoint, params)
        try:
            if response.is_redirect:
                raise GenesisUnknownEnvelope(
                    f"GENESIS redirected {endpoint} to {response.headers.get('location', '?')}; the base URL is stale. "
                    "Credentials are not sent across redirects.",
                    endpoint=endpoint,
                    http_status=response.status_code,
                )
            inspected = inspect_response(response, endpoint, host=self.host)
        except GenesisError as exc:
            self._redact(exc)
            raise
        if isinstance(inspected.reply, GenesisEnvelope) and inspected.reply.status.is_warning:
            logger.warning("GENESIS %s: %s", endpoint, redact_text(inspected.reply.status.content, self._secrets()))
        return inspected

    def _secrets(self) -> tuple[str, ...]:
        known = self._credentials if self._credentials is not None else self._explicit
        return known.secrets() if known is not None else ()

    def _redact(self, exc: GenesisError) -> None:
        """Server text quoted in an exception may echo a credential; scrub it with the known secrets."""
        secrets = self._secrets()
        if not secrets:
            return
        exc.args = tuple(redact_text(arg, secrets) if isinstance(arg, str) else arg for arg in exc.args)
        if exc.status_block is not None:
            exc.status_block = {
                k: redact_text(v, secrets) if isinstance(v, str) else v for k, v in exc.status_block.items()
            }

    def whoami(self) -> HelloWorldReply:
        reply = self.call("helloworld/whoami").reply
        if not isinstance(reply, HelloWorldReply):
            raise GenesisUnknownEnvelope("whoami did not answer with a User-Agent object", endpoint="helloworld/whoami")
        return reply

    def logincheck(self) -> LoginCheckReply:
        """Proves the credentials: raises GenesisAuthError on guest or rejected, GenesisBackendError on the outage text."""
        reply = self.call("helloworld/logincheck").reply
        if not isinstance(reply, LoginCheckReply):
            raise GenesisUnknownEnvelope(
                "logincheck did not answer with the flat Status/Username reply", endpoint="helloworld/logincheck"
            )
        return reply

    def qualitysigns(self) -> GenesisEnvelope:
        """The value-marker legend (``List`` of ``Code``/``Content``); no credentials needed."""
        return self._envelope("catalogue/qualitysigns", None)

    def metadata_table(self, name: str) -> GenesisEnvelope:
        """``metadata/table`` for one table code; ``area`` stays at the server default."""
        return self._envelope("metadata/table", {"name": name})

    def _envelope(self, endpoint: str, params: Mapping[str, str] | None) -> GenesisEnvelope:
        reply = self.call(endpoint, params).reply
        if not isinstance(reply, GenesisEnvelope):
            raise GenesisUnknownEnvelope(f"{endpoint} did not answer with the nested envelope", endpoint=endpoint)
        return reply


def fetch_tablefile(client: GenesisClient, parameters: Mapping[str, str]) -> bytes:
    """POSTs ``data/tablefile`` with already-canonical ``parameters`` and returns the zip body.

    Meant as the ``fetch`` callback for ``ParameterCache.get_or_fetch``. The envelope and HTTP
    status are inspected by ``GenesisClient.call`` before this looks at the reply kind; raises if
    GENESIS answers with anything other than a zip payload.
    """
    inspected = client.call("data/tablefile", parameters)
    if inspected.kind != "zip":
        raise GenesisUnknownEnvelope(
            "data/tablefile did not answer with a zip payload",
            endpoint="data/tablefile",
            http_status=inspected.http_status,
        )
    return inspected.body
