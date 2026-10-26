"""Packaging metadata: the wheel ships code only, the Python classifiers match CI, ruff matches the lock."""

import re
import tomllib
from fnmatch import fnmatchcase
from pathlib import Path
from typing import cast

REPO_ROOT = Path(__file__).resolve().parents[1]
DISTRIBUTION = REPO_ROOT / "mloda_plugin_govdata"


def _find_config() -> dict[str, list[str]]:
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        data = tomllib.load(handle)
    return cast(dict[str, list[str]], data["tool"]["setuptools"]["packages"]["find"])


def _dotted(path: Path) -> str:
    return ".".join(path.relative_to(REPO_ROOT).parts)


def test_tests_packages_are_excluded_from_the_wheel() -> None:
    # Same fnmatch semantics setuptools applies to include and exclude patterns.
    find = _find_config()
    tests_dirs = [path for path in DISTRIBUTION.rglob("tests") if path.is_dir()]
    assert tests_dirs, "no tests package under the distribution"
    candidates = list(tests_dirs) + [path for tests_dir in tests_dirs for path in tests_dir.rglob("*") if path.is_dir()]
    shipped = sorted(
        _dotted(path)
        for path in candidates
        if any(fnmatchcase(_dotted(path), pattern) for pattern in find["include"])
        and not any(fnmatchcase(_dotted(path), pattern) for pattern in find["exclude"])
    )
    assert shipped == []


def test_no_package_data_is_shipped() -> None:
    # A stale egg-info manifest would otherwise re-add excluded test modules as package data.
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        data = tomllib.load(handle)
    assert data["tool"]["setuptools"]["include-package-data"] is False


def test_python_classifiers_match_the_ci_matrix() -> None:
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        data = tomllib.load(handle)
    prefix = "Programming Language :: Python :: 3."
    classified = [
        c.removeprefix("Programming Language :: Python :: ")
        for c in data["project"]["classifiers"]
        if c.startswith(prefix)
    ]
    workflow = (REPO_ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    match = re.search(r"python-version:\s*\[([^\]]*)\]", workflow)
    assert match, "no python-version list in the CI matrix"
    matrix = re.findall(r"[\"']([^\"']+)[\"']", match.group(1))
    assert matrix
    assert classified == matrix


def test_ruff_pin_matches_the_lock() -> None:
    # tox resolves the dev extra without uv.lock; an exact pin equal to the lock keeps both on one ruff.
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        dev = tomllib.load(handle)["project"]["optional-dependencies"]["dev"]
    with (REPO_ROOT / "uv.lock").open("rb") as handle:
        locked = [p["version"] for p in tomllib.load(handle)["package"] if p["name"] == "ruff"]
    assert [d for d in dev if d.startswith("ruff")] == [f"ruff=={v}" for v in locked]
