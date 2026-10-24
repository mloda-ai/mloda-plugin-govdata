"""Repo-root pytest hooks: skip ``genesis_live`` tests visibly when no GENESIS credentials are configured."""

import os

import pytest

from mloda_plugin_govdata.feature_groups.destatis.core.auth import ENV_SUFFIXES
from mloda_plugin_govdata.feature_groups.destatis.core.hosts import KNOWN_HOSTS


def _hosts_with_credentials() -> list[str]:
    hosts: list[str] = []
    for name, host in KNOWN_HOSTS.items():
        token, user, password = (os.environ.get(host.env_var(suffix), "").strip() for suffix in ENV_SUFFIXES)
        if token or (user and password):
            hosts.append(name)
    return hosts


@pytest.fixture
def no_genesis_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """No GENESIS credentials in the environment, for any known host."""
    for host in KNOWN_HOSTS.values():
        for suffix in ENV_SUFFIXES:
            monkeypatch.delenv(host.env_var(suffix), raising=False)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if _hosts_with_credentials():
        return
    variables = ", ".join(
        f"{host.env_var('TOKEN')} (or {host.env_var('USER')} plus {host.env_var('PASSWORD')})"
        for host in KNOWN_HOSTS.values()
    )
    skip = pytest.mark.skip(reason=f"genesis_live: no GENESIS credentials in the environment; set one of {variables}")
    for item in items:
        if "genesis_live" in item.keywords:
            item.add_marker(skip)
