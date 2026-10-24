"""Host-scoped GENESIS credentials: explicit option, then the run's DataAccessCollection, then env; redacted."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from mloda.user import DataAccessCollection, Options

from .errors import MissingCredentialsError, WrongHostCredentialsError
from .hosts import GenesisHost

# Suffixes joined with the host prefix: GENESIS_TOKEN, REGIONALSTATISTIK_USER, ... (a tuple, so
# no *_PASSWORD named constant exists for bandit B105 to flag).
ENV_SUFFIXES: tuple[str, str, str] = ("TOKEN", "USER", "PASSWORD")

# Options.context key for explicit credentials; never a group key (group is hashed and printed).
OPTION_GENESIS_CREDENTIALS = "genesis_credentials"

_REDACTED = "<redacted>"


def _clean(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _header_safe(value: str) -> bool:
    """Printable latin-1 only: no control characters (a copied token with a newline would break the header)."""
    try:
        value.encode("latin-1")
    except UnicodeEncodeError:
        return False
    return not any(ord(ch) < 32 or ord(ch) == 127 for ch in value)


@dataclass(frozen=True, repr=False)
class DestatisCredentials:
    """A token, or user plus password, scoped to one host by name.

    The token is the default path; ``job=true`` and ``profile/*`` calls need user plus password.
    """

    host: str = "genesis"
    token: str | None = None
    user: str | None = None
    password: str | None = None

    def __post_init__(self) -> None:
        for name in ("host", "token", "user", "password"):
            value = _clean(getattr(self, name))
            if value is not None and not _header_safe(value):
                # Named by field only: an httpx header error would otherwise print the value in a traceback.
                raise ValueError(
                    f"DestatisCredentials.{name} contains characters that cannot travel in an HTTP header."
                )
            object.__setattr__(self, name, value)
        if not self.host:
            raise ValueError("DestatisCredentials needs a host name.")
        if (self.user is None) != (self.password is None):
            raise ValueError("DestatisCredentials needs user and password together.")
        if self.token is None and self.user is None:
            raise ValueError("DestatisCredentials needs a token or user plus password.")

    @property
    def has_password_path(self) -> bool:
        return self.user is not None

    def headers(self) -> dict[str, str]:
        """The two credential headers; the token travels in ``username`` with an empty ``password``."""
        if self.token is not None:
            # The token path sends an empty password header by protocol; B105 sees a hardcoded secret.
            return {"username": self.token, "password": ""}  # nosec B105
        return {"username": self.user or "", "password": self.password or ""}

    def secrets(self) -> tuple[str, ...]:
        """Every value that must never appear in output (for redaction)."""
        return tuple(value for value in (self.token, self.user, self.password) if value)

    def __repr__(self) -> str:
        shown = ", ".join(
            f"{name}={_REDACTED if getattr(self, name) is not None else None}" for name in ("token", "user", "password")
        )
        return f"DestatisCredentials(host={self.host!r}, {shown})"

    __str__ = __repr__

    @classmethod
    def from_env(cls, host: GenesisHost, environ: Mapping[str, str] | None = None) -> DestatisCredentials | None:
        """Read the host's env vars; ``None`` when none is set, an error when the set is incomplete."""
        env = os.environ if environ is None else environ
        token, user, password = (_clean(env.get(host.env_var(suffix))) for suffix in ENV_SUFFIXES)
        if token is None and user is None and password is None:
            return None
        if (user is None) != (password is None):
            missing = host.env_var("PASSWORD" if password is None else "USER")
            raise MissingCredentialsError(f"{missing} is not set; the password path needs both user and password.")
        return cls(host=host.name, token=token, user=user, password=password)


def missing_credentials_message(host: GenesisHost) -> str:
    token_var, user_var, password_var = (host.env_var(suffix) for suffix in ENV_SUFFIXES)
    return (
        f"No credentials for {host.label}. Set {token_var} (personal API token), or {user_var} and "
        f"{password_var}, or pass the token in the run's DataAccessCollection under the handle {host.name!r}. "
        f"Registration is free and same-day: {host.registration_url}. Registrations are per host, so a token "
        "from another GENESIS installation is not valid here."
    )


def resolve_credentials(
    host: GenesisHost,
    explicit: DestatisCredentials | None = None,
    environ: Mapping[str, str] | None = None,
) -> DestatisCredentials:
    """Explicit credentials (host must match), else the host's env vars, else a MissingCredentialsError."""
    if explicit is not None:
        if explicit.host != host.name:
            raise WrongHostCredentialsError(
                f"Credentials are scoped to host {explicit.host!r} but the request targets {host.name!r} "
                f"({host.label}); registrations and tokens are separate per host."
            )
        return explicit
    from_env = DestatisCredentials.from_env(host, environ)
    if from_env is None:
        raise MissingCredentialsError(missing_credentials_message(host))
    return from_env


_CREDENTIAL_KEYS = frozenset({"host", "token", "user", "password"})


def credentials_from_collection(
    collection: DataAccessCollection | None, host: GenesisHost
) -> DestatisCredentials | None:
    """The collection's GENESIS credentials for ``host``, or ``None``; errors name handles and keys, never values.

    An entry counts only when tagged for GENESIS: its handle is a host name (``genesis``, ``regionalstatistik``)
    or it carries a known ``host`` key, so another plugin's token is never sent here.
    """
    entries = {} if collection is None else collection.credentials
    matching = sorted(name for name, entry in entries.items() if _tag(entry.get("host", name)) == host.name)
    if len(matching) > 1:
        raise ValueError(f"Several credentials for host {host.name!r}: {', '.join(matching)}; keep one.")
    return _destatis_credentials(matching[0], entries[matching[0]], host.name) if matching else None


def _tag(value: object) -> str | None:
    return value.strip().lower() if isinstance(value, str) else None


def _destatis_credentials(handle: str, entry: Mapping[str, object], host: str) -> DestatisCredentials:
    unknown = sorted(set(entry) - _CREDENTIAL_KEYS)
    if unknown:
        raise ValueError(
            f"Credentials {handle!r} have unknown key(s) {unknown}; GENESIS takes {sorted(_CREDENTIAL_KEYS)}."
        )
    fields = {key: value for key, value in entry.items() if key != "host"}
    try:
        return DestatisCredentials(host=host, **fields)  # type: ignore[arg-type]
    except ValueError as exc:  # __post_init__ names fields only, never values
        raise ValueError(f"Credentials {handle!r}: {exc}") from None


def explicit_credentials_from_options(options: Options | None) -> DestatisCredentials | None:
    """The explicit ``DestatisCredentials`` from ``Options.context``, or ``None``; never touches env or a host.

    That lets a reader build a ``GenesisClient`` before knowing whether a request will actually happen
    (a cache hit needs no credentials at all).
    Only a ``DestatisCredentials`` instance is accepted: a plain mapping would sit unredacted in the
    context, which ``str(options)`` prints verbatim.
    """
    if options is None:
        return None
    if OPTION_GENESIS_CREDENTIALS in options.group:
        raise ValueError(
            f"{OPTION_GENESIS_CREDENTIALS!r} must be passed in Options.context, not group: "
            "group options are hashed and printed with the feature."
        )
    raw = options.context.get(OPTION_GENESIS_CREDENTIALS)
    if raw is None:
        return None
    if not isinstance(raw, DestatisCredentials):
        raise TypeError(
            f"{OPTION_GENESIS_CREDENTIALS!r} must be a DestatisCredentials instance (its repr is redacted), "
            f"got {type(raw).__name__}"
        )
    return raw
