"""Destatis GENESIS connector: ``DestatisReader`` reads the table selection a ``DestatisLocator`` names.

GENESIS is the database software and its REST API. ``genesis`` (GENESIS-Online, Destatis) and ``regionalstatistik``
(Regionaldatenbank, run by IT.NRW) are two installations of it, each with its own registration. By convention
``Destatis*`` classes face mloda and ``Genesis*`` classes speak the protocol; ``OPTION_GENESIS_CREDENTIALS`` is an
mloda option despite its name.
"""

from .core.api import GenesisClient
from .core.auth import OPTION_GENESIS_CREDENTIALS, DestatisCredentials
from .core.cache import ParameterCache
from .core.errors import (
    GenesisAuthError,
    GenesisBackendError,
    GenesisEmptySelection,
    GenesisError,
    GenesisJobAccepted,
    GenesisMaintenance,
    GenesisResultTooLarge,
    GenesisUnknownEnvelope,
    GenesisUnknownTable,
    MissingCredentialsError,
    WrongHostCredentialsError,
)
from .core.hosts import GENESIS_ONLINE, REGIONALSTATISTIK, GenesisHost
from .core.parse import parse_ffcsv_zip
from .locator import DestatisLocator
from .reader import DestatisReader

__all__ = [
    "GENESIS_ONLINE",
    "OPTION_GENESIS_CREDENTIALS",
    "REGIONALSTATISTIK",
    "DestatisCredentials",
    "DestatisLocator",
    "DestatisReader",
    "GenesisAuthError",
    "GenesisBackendError",
    "GenesisClient",
    "GenesisEmptySelection",
    "GenesisError",
    "GenesisHost",
    "GenesisJobAccepted",
    "GenesisMaintenance",
    "GenesisResultTooLarge",
    "GenesisUnknownEnvelope",
    "GenesisUnknownTable",
    "MissingCredentialsError",
    "ParameterCache",
    "WrongHostCredentialsError",
    "parse_ffcsv_zip",
]
