"""Content-addressed download cache with conditional-GET revalidation."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from .client import OwnedHttpClient, build_client, request_with_retry

# Persistent cache location shared by the readers and the Destatis client's lock file.
DEFAULT_CACHE_DIR = Path(tempfile.gettempdir()) / "mloda-govdata-cache"


def write_atomic(path: Path, data: bytes) -> None:
    """Writes ``data`` to ``path`` atomically; never leaves a partial file behind on failure.
    ``path.parent`` must already exist."""
    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f"{path.name}.", suffix=".tmp", delete=False) as tmp:
            tmp_name = tmp.name
            tmp.write(data)
        os.replace(tmp_name, path)
    except BaseException:
        if tmp_name is not None:
            with contextlib.suppress(OSError):
                Path(tmp_name).unlink(missing_ok=True)
        raise


class CacheMissError(RuntimeError):
    """Raised when revalidate=False and the URL is not cached; no request is made."""


class PinMismatchError(RuntimeError):
    """Raised when a downloaded body's sha256 is not the pinned one; the cache is left as it was."""


@dataclass(frozen=True)
class CachedFile:
    path: Path
    url: str
    sha256: str
    etag: str | None
    retrieved_at: datetime  # when the bytes were downloaded; a 304 revalidation keeps it


class DownloadCache(OwnedHttpClient):
    """Stores downloaded bodies addressed by content hash.

    Revalidates with ``If-None-Match`` / ``If-Modified-Since``; a ``304`` reuses
    the stored body (sha256-verified). Safe to share across runs: entries are
    keyed by URL and content hash. ``revalidate=False`` reads the cache offline,
    making no request.
    """

    def __init__(self, cache_dir: str | os.PathLike[str], client: httpx.Client | None = None) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._owns_client = client is None
        self._client = client if client is not None else build_client()

    def _meta_path(self, url: str) -> Path:
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{key}.meta.json"

    def _read_meta(self, url: str) -> dict[str, Any] | None:
        meta_path = self._meta_path(url)
        if not meta_path.exists():
            return None
        try:
            loaded = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None  # unreadable metadata: treat as a cache miss and re-download
        return loaded if isinstance(loaded, dict) else None

    def get_or_download(self, url: str, *, revalidate: bool = True, sha256: str | None = None) -> CachedFile:
        """``sha256`` pins the body: a cached body with another hash is a miss, and a download with another
        hash raises ``PinMismatchError`` before the cache is touched."""
        meta = self._read_meta(url)
        cached = self._cached_from_meta(url, meta) if meta is not None else None
        if cached is not None and sha256 is not None and cached.sha256 != sha256:
            cached = None

        if not revalidate:
            if cached is not None:
                return cached
            raise CacheMissError(
                f"{url} has no usable cache entry in {self.cache_dir} (missing, corrupted, without a retrieval "
                "time, or not the pinned body); no request made because revalidate=False"
            )

        # Only revalidate conditionally when there is a valid body to fall back on;
        # otherwise request unconditionally so the server sends a full 200.
        headers: dict[str, str] = {}
        if cached is not None and meta is not None:
            if meta.get("etag"):
                headers["If-None-Match"] = meta["etag"]
            if meta.get("last_modified"):
                headers["If-Modified-Since"] = meta["last_modified"]

        response = request_with_retry(self._client, "GET", url, headers=headers)
        if response.status_code == 304:
            if cached is not None:
                return cached
            raise RuntimeError(f"server returned 304 for {url} but no cached body is available")
        response.raise_for_status()
        return self._store(url, response, sha256)

    def _cached_from_meta(self, url: str, meta: dict[str, Any]) -> CachedFile | None:
        sha = meta.get("sha256")
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
            return None  # untrusted or malformed hash; never trust meta["data_file"] as a path
        data_path = self.cache_dir / f"{sha}.bin"
        if not data_path.exists():
            return None
        digest = hashlib.sha256(data_path.read_bytes()).hexdigest()
        if digest != sha:
            return None  # corrupted cache; force re-download
        try:
            retrieved_at = datetime.fromisoformat(meta["retrieved_at"])
        except (KeyError, ValueError, TypeError):
            return None  # missing or unparseable timestamp; treat as a miss
        if retrieved_at.tzinfo is None:
            return None  # naive timestamp; treat as a miss
        return CachedFile(path=data_path, url=url, sha256=digest, etag=meta.get("etag"), retrieved_at=retrieved_at)

    def _store(self, url: str, response: httpx.Response, pinned: str | None) -> CachedFile:
        body = response.content
        digest = hashlib.sha256(body).hexdigest()
        if pinned is not None and digest != pinned:
            raise PinMismatchError(f"{url}: downloaded sha256 {digest} does not match the pinned {pinned}")
        data_path = self.cache_dir / f"{digest}.bin"
        write_atomic(data_path, body)
        retrieved_at = datetime.now(UTC)
        meta: dict[str, Any] = {
            "url": url,
            "etag": response.headers.get("ETag"),
            "last_modified": response.headers.get("Last-Modified"),
            "sha256": digest,
            "data_file": data_path.name,
            "retrieved_at": retrieved_at.isoformat(),
        }
        # Meta last: an orphan blob reads back as a miss, never a truncated hit.
        write_atomic(self._meta_path(url), json.dumps(meta).encode("utf-8"))
        return CachedFile(path=data_path, url=url, sha256=digest, etag=meta["etag"], retrieved_at=retrieved_at)
