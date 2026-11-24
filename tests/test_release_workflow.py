"""Releases use PyPI Trusted Publishing with a TestPyPI stage, no stored token."""

import re
from itertools import pairwise
from pathlib import Path
from typing import Any

import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"

ACTION = "pypa/gh-action-pypi-publish"
PINNED = re.compile(r"^pypa/gh-action-pypi-publish@[0-9a-f]{40}$")
EXPECTED_PUBLISHERS = {("release.yaml", "publish_testpypi"), ("publish-pypi.yaml", "publish_pypi")}
EXPECTED_PERMISSIONS = {
    "publish_testpypi": {"id-token": "write"},
    "publish_pypi": {"contents": "read", "id-token": "write"},
}
# Must match the environment each Trusted Publisher is limited to on (Test)PyPI.
EXPECTED_ENVIRONMENTS = {"publish_testpypi": "testpypi", "publish_pypi": "pypi"}


def _workflow_paths() -> list[Path]:
    return sorted(WORKFLOWS.glob("*.y*ml"))


def _workflow(name: str) -> dict[Any, Any]:
    config: dict[Any, Any] = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    return config


def _all_jobs() -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (path.name, job_name): job
        for path in _workflow_paths()
        for job_name, job in _workflow(path.name)["jobs"].items()
    }


def _needs(job: dict[str, Any]) -> set[str]:
    needs = job.get("needs", [])
    return {needs} if isinstance(needs, str) else set(needs)


def _uses(step: dict[str, Any]) -> str:
    return str(step.get("uses", ""))


def test_no_stored_pypi_token_or_twine_upload() -> None:
    for path in _workflow_paths():
        text = path.read_text(encoding="utf-8")
        assert "PYPI_API_TOKEN" not in text, f"{path.name} still references PYPI_API_TOKEN"
        assert "twine upload" not in text, f"{path.name} still runs twine upload"


def test_only_expected_jobs_publish_with_oidc_only() -> None:
    jobs = _all_jobs()
    publishers = {key for key, job in jobs.items() if any(_uses(s).startswith(ACTION) for s in job.get("steps", []))}
    assert publishers == EXPECTED_PUBLISHERS
    for key in publishers:
        job = jobs[key]
        assert job.get("permissions") == EXPECTED_PERMISSIONS[key[1]], f"{key} permissions"
        assert job.get("environment", {}).get("name") == EXPECTED_ENVIRONMENTS[key[1]], f"{key} environment"
        steps = job["steps"]
        assert not any(_uses(s).startswith("actions/checkout") for s in steps), f"{key} must not check out code"
        (publish,) = [s for s in steps if _uses(s).startswith(ACTION)]
        assert PINNED.match(publish["uses"]), f"{key} must pin the action by 40-hex SHA"
        if key[1] == "publish_testpypi":
            assert publish["with"]["repository-url"] == "https://test.pypi.org/legacy/"
        else:
            assert "repository-url" not in publish.get("with", {}), f"{key} must publish to real PyPI"
    for key, job in jobs.items():
        if key not in publishers:
            assert "id-token" not in (job.get("permissions") or {}), f"{key} must not grant id-token"
    for path in _workflow_paths():
        assert "id-token" not in (_workflow(path.name).get("permissions") or {}), f"{path.name} top-level"


def test_wheel_is_built_once_and_flows_through_the_stages() -> None:
    jobs = _all_jobs()
    builders = {key for key, job in jobs.items() if any("uv build" in str(s.get("run", "")) for s in job["steps"])}
    assert builders == {("release.yaml", "build")}
    chain = ["build", "publish_testpypi", "attach_to_release"]
    for previous, current in pairwise(chain):
        assert previous in _needs(jobs[("release.yaml", current)]), f"{current} must need {previous}"


def test_publish_pypi_is_manual_with_required_version() -> None:
    config = _workflow("publish-pypi.yaml")
    # PyYAML reads the bare `on` key as the boolean True.
    triggers: dict[str, Any] = config["on"] if "on" in config else config[True]
    assert set(triggers) == {"workflow_dispatch"}
    assert triggers["workflow_dispatch"]["inputs"]["version"]["required"] is True
