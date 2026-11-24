"""The recipe credential scan: credential-named keys, token-shaped values, URL userinfo, and live env secrets."""

from __future__ import annotations

import os
import re
from collections.abc import Iterator, Mapping
from typing import Any
from urllib.parse import urlsplit

from ..feature_groups.destatis.core.hosts import KNOWN_HOSTS
from ..feature_groups.destatis.core.redact import CREDENTIAL_KEYS, secret_variants

# A key names a credential when it contains one of these (lower-cased) or one of its `_`/`-`/`.`-separated
# words is in CREDENTIAL_KEY_TERMS. Substrings would make "auth" hit "author", hence the two tiers.
CREDENTIAL_KEY_WORDS: tuple[str, ...] = (
    "token",
    "password",
    "passwd",
    "secret",
    "apikey",
    "api_key",
    "credential",
    "bearer",
    "authorization",
)
CREDENTIAL_KEY_TERMS: frozenset[str] = frozenset({"user", "auth", "pwd", "login", "kennung"})
# A run of letters and digits with no separator, long enough to be an API token. The GENESIS token is one
# such run; table codes, slugs, URLs, region keys, and dates carry separators or are shorter, so they pass.
TOKEN_RUN_LENGTH = 24
_TOKEN_RUN = re.compile(rf"[A-Za-z0-9]{{{TOKEN_RUN_LENGTH},}}", re.ASCII)
_KEY_WORDS = re.compile(r"[^a-z0-9]+")
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
# The only places a hash or a credential-named field is legitimate, anchored to their exact paths.
_SHA256_FIELD = re.compile(r"^compliance\.sources\[\d+\]\.sha256$")
_CREDENTIAL_ENV_FIELD = re.compile(r"^compliance\.sources\[\d+\]\.credential_env$")
# Shorter env values are not scanned for (a short user name would match ordinary words).
_MIN_ENV_SECRET_LENGTH = 8


def reject_credentials(tree: Any) -> None:
    """Raise ``ValueError`` at the first credential in a recipe's JSON tree, naming its location, never its value."""
    secrets = environment_secrets()
    # Keys first, parents before children, so a message never has to print a key that is itself a secret.
    for parent, key in _keys(tree):
        where = f"{parent}.{key}" if parent else key
        if _credential_named(key) and not _CREDENTIAL_ENV_FIELD.fullmatch(where):
            raise ValueError(f"{where}: {key!r} names a credential; credentials go in the run's DataAccessCollection")
        if _token_shaped(key):
            raise ValueError(f"{parent or 'recipe'}: a key looks like an API token")
        if _matches_secret(key, secrets):
            raise ValueError(
                f"{parent or 'recipe'}: a key contains a value of a GENESIS credential set in this environment"
            )
    for path, leaf in _leaves(tree):
        if not isinstance(leaf, str):
            continue
        if _token_shaped(leaf) and not (_SHA256_FIELD.fullmatch(path) and SHA256_HEX.fullmatch(leaf)):
            raise ValueError(
                f"{path}: value looks like an API token ({TOKEN_RUN_LENGTH} or more letters and digits "
                "without a separator)"
            )
        if _url_carries_credentials(leaf):
            raise ValueError(f"{path}: URL carries credentials in front of the host")
        if _matches_secret(leaf, secrets):
            raise ValueError(f"{path}: contains a value of a GENESIS credential set in this environment")


def _credential_named(key: str) -> bool:
    lowered = key.lower()
    if lowered in CREDENTIAL_KEYS or any(word in lowered for word in CREDENTIAL_KEY_WORDS):
        return True
    return any(term in CREDENTIAL_KEY_TERMS for term in _KEY_WORDS.split(lowered))


def _token_shaped(value: str) -> bool:
    return any(any(ch.isalpha() for ch in run) and any(ch.isdigit() for ch in run) for run in _TOKEN_RUN.findall(value))


def _url_carries_credentials(value: str) -> bool:
    if "://" not in value:
        return False
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    return bool(parts.username or parts.password)


def _matches_secret(text: str, secrets: set[str]) -> bool:
    lowered = text.lower()
    return any(secret in lowered for secret in secrets)


def environment_secrets(environ: Mapping[str, str] | None = None) -> set[str]:
    """Lower-cased variants of the GENESIS credential values set in ``environ`` (default: the process env).

    Tokens and passwords are scanned as they are. A user name is scanned only when it is identifier-shaped
    (carries a digit or ``@``): a plain-word user name would match ordinary prose and URLs.
    """
    env = os.environ if environ is None else environ
    found: set[str] = set()
    for host in KNOWN_HOSTS.values():
        for suffix in ("TOKEN", "PASSWORD", "USER"):
            value = env.get(host.env_var(suffix), "").strip()
            if len(value) < _MIN_ENV_SECRET_LENGTH:
                continue
            if suffix == "USER" and "@" not in value and not any(ch.isdigit() for ch in value):
                continue
            found.update(variant.lower() for variant in secret_variants(value))
    return found


def _leaves(node: Any, path: str = "") -> Iterator[tuple[str, Any]]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _leaves(value, f"{path}.{key}" if path else str(key))
    elif isinstance(node, list):
        for position, value in enumerate(node):
            yield from _leaves(value, f"{path}[{position}]")
    else:
        yield path, node


def _keys(node: Any, path: str = "") -> Iterator[tuple[str, str]]:
    """Every dict key as (parent path, key), parents before children."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield path, str(key)
            yield from _keys(value, f"{path}.{key}" if path else str(key))
    elif isinstance(node, list):
        for position, value in enumerate(node):
            yield from _keys(value, f"{path}[{position}]")
