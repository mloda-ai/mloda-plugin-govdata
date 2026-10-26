"""Parameter-keyed cache for POST replies (``data/tablefile``); a sibling of ``DownloadCache``.

A GET reply is keyed by URL and revalidated conditionally; a POST reply is keyed by host, endpoint,
and the form fields as sent, with no revalidation. Freshness rule: a hit wins with no request,
``refresh=True`` fetches again, no TTL, only a warning once a hit is older than ``STALE_AFTER``.
Credentials travel in headers, never in the key or the meta file. Both caches share one directory;
every file here carries the ``post-`` prefix.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ...govdata.core.cache import write_atomic
from .api import CLASSIFYING_KEYS, OPERATIONS
from .hosts import GenesisHost, resolve_host
from .redact import CREDENTIAL_KEYS

__all__ = ["SELECTION_FIELDS", "STALE_AFTER", "CachedPayload", "ParameterCache", "canonical_parameters"]

logger = logging.getLogger(__name__)

STALE_AFTER = timedelta(days=30)
KEY_PREFIX = "post-"
_HASH_CHUNK = 1 << 20
_SHA256 = re.compile(r"[0-9a-f]{64}")

# Comma-separated selections the server treats as sets: sorted for the key and on the wire.
SELECTION_FIELDS: frozenset[str] = frozenset({"regionalkey", *CLASSIFYING_KEYS})
# Numeric fields; anywhere else an int would drop a code's leading zeros.
_INT_FIELDS: frozenset[str] = frozenset({"startyear", "endyear", "timeslices"})


def _wire_scalar(name: str, value: object) -> str:
    """One value as it travels: strings stripped, ints as digits (``_INT_FIELDS`` only); bools refused."""
    if isinstance(value, bool):
        # The spec spells booleans per field ("true"/"false" for compress, "on"/"off" for quality).
        raise TypeError(f"parameter {name!r}: pass the wire string for booleans, not a bool")
    if isinstance(value, int):
        if name in _INT_FIELDS:
            return str(value)
        raise TypeError(f"parameter {name!r} must be a str: an int loses a code's leading zeros")
    if isinstance(value, str):
        return value.strip()
    # Named by field only: a value could be a secret pasted into the wrong place.
    raise TypeError(
        f"parameter {name!r} must be a str (an int for {', '.join(sorted(_INT_FIELDS))}) "
        f"or a flat sequence of those, got {type(value).__name__}"
    )


def canonical_parameters(endpoint: str, parameters: Mapping[str, object]) -> dict[str, str]:
    """The form fields as sent, which is also the request identity.

    Only fields the operation declares are accepted (undeclared names are refused before anything is
    keyed or written); ``username`` and ``password`` are dropped, ``None`` means not sent, selection
    fields are sorted, and ``language`` must be explicit where the operation declares it, because
    the client would otherwise fill it in silently and two languages would share one entry.
    """
    try:
        operation = OPERATIONS[endpoint]
    except KeyError:
        raise ValueError(f"Unknown GENESIS operation {endpoint!r}; known: {', '.join(sorted(OPERATIONS))}") from None
    canonical: dict[str, str] = {}
    for raw_name, value in parameters.items():
        name = str(raw_name)
        if name.lower() in CREDENTIAL_KEYS:
            continue
        if name not in operation.fields:
            raise ValueError(f"{endpoint} does not declare {name!r}; allowed: {sorted(operation.fields)}")
        if value is None:
            continue
        if isinstance(value, (list, tuple, set, frozenset)):
            text = ",".join(_wire_scalar(name, item) for item in value)
        else:
            text = _wire_scalar(name, value)
        if name in SELECTION_FIELDS:
            text = ",".join(sorted(part.strip() for part in text.split(",") if part.strip()))
        canonical[name] = text
    if "language" in operation.fields and "language" not in canonical:
        raise ValueError(f"{endpoint}: 'language' must be passed explicitly; it shapes the reply and the key")
    return canonical


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class CachedPayload:
    """A stored reply body; ``parameters`` is the canonical wire form that keyed it (credential-free)."""

    path: Path
    sha256: str
    retrieved_at: datetime
    key: str
    host: GenesisHost
    endpoint: str
    parameters: dict[str, str] = field(default_factory=dict, hash=False)


class ParameterCache:
    """Stores POST reply bodies keyed by host, endpoint, and canonical parameters.

    ``clock`` is injectable for the staleness warning; it must return an aware datetime.
    """

    def __init__(self, cache_dir: str | os.PathLike[str], *, clock: Callable[[], datetime] | None = None) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._clock = clock if clock is not None else lambda: datetime.now(UTC)

    def key(self, host: GenesisHost | str, endpoint: str, parameters: Mapping[str, object]) -> str:
        identity = {
            "base_url": resolve_host(host).base_url,
            "endpoint": endpoint,
            "parameters": canonical_parameters(endpoint, parameters),
        }
        return KEY_PREFIX + hashlib.sha256(_canonical_json(identity).encode("utf-8")).hexdigest()

    def lookup(self, host: GenesisHost | str, endpoint: str, parameters: Mapping[str, object]) -> CachedPayload | None:
        """The stored reply, or ``None``; never makes a request. Warns when the hit is older than ``STALE_AFTER``."""
        resolved = resolve_host(host)
        canonical = canonical_parameters(endpoint, parameters)
        key = self.key(resolved, endpoint, canonical)
        meta = self._read_meta(key)
        if meta is None:
            return None
        cached = self._payload_from_meta(key, resolved, endpoint, canonical, meta)
        if cached is not None:
            self._warn_if_stale(cached)
        return cached

    def store(
        self, host: GenesisHost | str, endpoint: str, parameters: Mapping[str, object], body: bytes
    ) -> CachedPayload:
        """Write ``body`` under the request key; the meta file never holds a credential."""
        if not body:
            raise ValueError(f"refusing to cache an empty {endpoint} reply")
        resolved = resolve_host(host)
        canonical = canonical_parameters(endpoint, parameters)
        key = self.key(resolved, endpoint, canonical)
        digest = hashlib.sha256(body).hexdigest()
        data_path = self.cache_dir / f"{KEY_PREFIX}{digest}.bin"
        write_atomic(data_path, body)
        retrieved_at = self._now()
        meta: dict[str, Any] = {
            "host": resolved.name,
            "base_url": resolved.base_url,
            "endpoint": endpoint,
            "parameters": canonical,
            "sha256": digest,
            "data_file": data_path.name,
            "retrieved_at": retrieved_at.isoformat(),
        }
        write_atomic(self._meta_path(key), _canonical_json(meta).encode("utf-8"))
        return CachedPayload(
            path=data_path,
            sha256=digest,
            retrieved_at=retrieved_at,
            key=key,
            host=resolved,
            endpoint=endpoint,
            parameters=canonical,
        )

    def get_or_fetch(
        self,
        host: GenesisHost | str,
        endpoint: str,
        parameters: Mapping[str, object],
        fetch: Callable[[Mapping[str, str]], bytes],
        *,
        refresh: bool = False,
    ) -> CachedPayload:
        """A hit wins without calling ``fetch``; ``refresh=True`` fetches and overwrites the entry.

        ``fetch`` receives the canonical form fields (the same mapping that keys the entry) and must
        raise for a reply that is not the payload; whatever it returns is stored.
        """
        canonical = canonical_parameters(endpoint, parameters)
        if not refresh:
            cached = self.lookup(host, endpoint, canonical)
            if cached is not None:
                return cached
        return self.store(host, endpoint, canonical, fetch(canonical))

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("ParameterCache clock returned a naive datetime; an aware UTC datetime is required")
        return now

    def _meta_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.meta.json"

    def _read_meta(self, key: str) -> dict[str, Any] | None:
        meta_path = self._meta_path(key)
        if not meta_path.exists():
            return None
        try:
            loaded = json.loads(meta_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):  # ValueError covers JSON and UTF-8 decoding
            return None  # unreadable meta: a miss, the entry is fetched again
        return loaded if isinstance(loaded, dict) else None

    def _payload_from_meta(
        self,
        key: str,
        host: GenesisHost,
        endpoint: str,
        canonical: dict[str, str],
        meta: dict[str, Any],
    ) -> CachedPayload | None:
        sha = meta.get("sha256")
        if not isinstance(sha, str) or not _SHA256.fullmatch(sha):
            return None  # never trust meta["data_file"] as a path
        data_path = self.cache_dir / f"{KEY_PREFIX}{sha}.bin"
        try:
            if _sha256_of_file(data_path) != sha:
                return None  # corrupted body: fetched again
        except OSError:
            return None  # missing or unreadable body: fetched again
        try:
            retrieved_at = datetime.fromisoformat(meta["retrieved_at"])
        except (KeyError, ValueError, TypeError):
            return None
        if retrieved_at.tzinfo is None:
            return None
        return CachedPayload(
            path=data_path,
            sha256=sha,
            retrieved_at=retrieved_at,
            key=key,
            host=host,
            endpoint=endpoint,
            parameters=canonical,
        )

    def _warn_if_stale(self, cached: CachedPayload) -> None:
        age = self._now() - cached.retrieved_at
        if age <= STALE_AFTER:
            return
        table = cached.parameters.get("name")
        subject = f"{cached.endpoint} reply for table {table}" if table else f"{cached.endpoint} reply"
        logger.warning(
            "Cached GENESIS %s is %d days old (retrieved %s); pass refresh=True to fetch it again.",
            subject,
            age.days,
            cached.retrieved_at.isoformat(),
        )
