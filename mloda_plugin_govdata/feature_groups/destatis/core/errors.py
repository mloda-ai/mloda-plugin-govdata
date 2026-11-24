"""Typed exceptions for GENESIS replies. Messages never carry credentials or the echoed username."""

from __future__ import annotations

from typing import Any


class GenesisError(Exception):
    """Base for every GENESIS-side failure; ``status_block`` is the raw status dict when one was parsed."""

    def __init__(
        self,
        message: str,
        *,
        endpoint: str | None = None,
        http_status: int | None = None,
        status_block: dict[str, Any] | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.http_status = http_status
        self.status_block = status_block
        super().__init__(message)


class GenesisAuthError(GenesisError):
    """Credentials missing, rejected, or not sent (the reply ran as guest)."""


class MissingCredentialsError(GenesisAuthError):
    """No credentials for the host; the message names the collection handle and the registration URL."""


class WrongHostCredentialsError(GenesisAuthError):
    """Credentials scoped to one host were offered to another; registrations are separate."""


class GenesisBackendError(GenesisError):
    """The generic system error text: backend outage, or (as observed) guest and wrong credentials."""


class GenesisUnknownTable(GenesisError):
    """The table code is not known to the host."""


class GenesisEmptySelection(GenesisError):
    """The selection matched no objects (documented status code 104)."""


class GenesisResultTooLarge(GenesisError):
    """The table is too large for a direct download; the job path needs user plus password."""


class GenesisJobAccepted(GenesisError):
    """The host queued a background job instead of returning the table."""


class GenesisMaintenance(GenesisError):
    """An HTML page came back instead of JSON or a zip (maintenance or error page)."""


class GenesisUnknownEnvelope(GenesisError):
    """A reply shape or status code this client does not know; the raw status block is quoted."""
