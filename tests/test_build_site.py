"""build_site.py: index, legal links, refusals, leak scan, real marimo exports; and the workflow that publishes."""

import ast
import base64
import importlib.metadata
import re
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

# Comes with marimo, which tox installs through the demo extra.
import yaml

from scripts import build_site
from scripts.build_site import TUTORIALS_DIR, main

TOKEN = "fake0token1for2the3tests"
WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "tutorials-live.yml"
EMBEDDED = base64.b64encode(f"n;t\n1;{TOKEN}\n".encode()).decode()
TOKEN_FROM_ENV = 'import os\n\n    token = os.environ["GENESIS_TOKEN"]'
LEGAL_PAGES = ("https://mloda.ai/impressum/", "https://mloda.ai/datenschutz/")
STUB_PREFIX = "https://cdn.jsdelivr.net/npm/@marimo-team/frontend@9.9.9/dist/"
STUB_NOTICES = {"LICENSE.txt": "license", "third_party.txt": "packages", "third_party_licenses.txt": "license texts"}
# Text that names the CDN without linking it, as a notebook may.
MENTION = "<p>Not from https://cdn.jsdelivr.net/ any more.</p>"
# Libraries whose output makes marimo's viewer fetch from other hosts: plotly loads MathJax from a CDN, maps load tiles.
OFF_SITE_LIBRARIES = {"plotly", "folium", "leafmap", "ipyleaflet", "pydeck", "lonboard"}
# The tag also as text inside the page, as notebook code can hold it.
PAGE = '<html><body><script>"</body>"</script>{}</body></html>'
NOTEBOOK = """import marimo

app = marimo.App()


@app.cell
def _():
    {cell}
    return
"""


@pytest.fixture
def token(no_genesis_env: None, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("GENESIS_TOKEN", TOKEN)
    return TOKEN


@pytest.fixture
def exported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replaces the marimo export with a stub page; lists the notebooks it was asked for."""
    names: list[str] = []
    _fake_export(monkeypatch, tmp_path, names)
    return names


def _fake_export(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    names: list[str],
    body: str = f'<script src="{STUB_PREFIX}assets/x.js"></script>{MENTION}',
    code: int = 0,
    frame: str = PAGE,
    extra: dict[str, str] | None = None,
) -> None:
    def export(notebook: Path, page: Path) -> int:
        names.append(notebook.name)
        page.write_text(frame.format(body), encoding="utf-8")
        for name, text in (extra or {}).items():  # files an export might write next to its page
            (page.parent / name).parent.mkdir(parents=True, exist_ok=True)
            (page.parent / name).write_text(text, encoding="utf-8")
        return code

    monkeypatch.setattr(build_site, "export", export)
    # A small stand-in for marimo's viewer files, so the stub runs do not copy the real ones.
    static = tmp_path / "viewer"
    (static / "assets").mkdir(parents=True)
    # The token in a viewer file: the copied package is not scanned, so the builds that should pass still do.
    for name, text in (("assets/x.js", TOKEN), ("favicon.ico", "icon"), ("index.html", "app"), ("notes.md", "notes")):
        (static / name).write_text(text, encoding="utf-8")
    for name, text in STUB_NOTICES.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    viewer = build_site._Viewer(STUB_PREFIX, static, {name: tmp_path / name for name in STUB_NOTICES})
    monkeypatch.setattr(build_site, "_viewer_source", lambda: viewer)


def _notebook(folder: Path, name: str, docstring: str | None, cell: str = "1 + 1") -> None:
    folder.mkdir(exist_ok=True)
    head = f'"""{docstring}"""\n\n' if docstring else ""
    (folder / name).write_text(head + NOTEBOOK.format(cell=cell), encoding="utf-8")


def _run(tmp_path: Path) -> int:
    return main(["--out", str(tmp_path / "site"), "--tutorials", str(tmp_path / "tutorials")])


def test_index_links_every_tutorial_with_its_docstring_line(tmp_path: Path, token: str, exported: list[str]) -> None:
    _notebook(tmp_path / "tutorials", "01_first.py", "Tutorial 1: read <one> & two.\n\nMore.")
    _notebook(tmp_path / "tutorials", "02_second.py", "Tutorial 2: the next one.")
    _notebook(tmp_path / "tutorials", "_draft.py", "Not a tutorial yet.")
    (tmp_path / "site").mkdir()  # an empty folder is taken
    assert _run(tmp_path) == 0
    assert exported == ["01_first.py", "02_second.py"]
    site = tmp_path / "site"
    assert sorted(path.name for path in site.iterdir()) == ["01_first.html", "02_second.html", "index.html", "marimo"]
    # marimo's own start page and notes are not part of the viewer the pages load.
    assert sorted(str(path.relative_to(site / "marimo")) for path in (site / "marimo").rglob("*")) == [
        "LICENSE.txt",
        "assets",
        "assets/x.js",
        "favicon.ico",
        "third_party.txt",
        "third_party_licenses.txt",
    ]
    index = (site / "index.html").read_text(encoding="utf-8")
    for name, text in STUB_NOTICES.items():
        assert (site / "marimo" / name).read_text(encoding="utf-8") == text
        assert f'href="marimo/{name}"' in index
    assert '<a href="01_first.html">Tutorial 1: read &lt;one&gt; &amp; two.</a>' in index
    assert '<a href="02_second.html">Tutorial 2: the next one.</a>' in index
    for expected in ('charset="utf-8"', "snapshot", "docs/schnellstart.md", "Funding code: 16IS26S11"):
        assert expected in index
    assert "jsDelivr" not in index
    assert "<img" not in index  # the ministry logo needs approval first
    for legal_page in LEGAL_PAGES:
        assert f'href="{legal_page}"' in index
    for name in ("01_first.html", "02_second.html"):
        page = (site / name).read_text(encoding="utf-8")
        assert page.count(build_site._BAR) == 1
        assert page.endswith(build_site._BAR + "</body></html>")  # before the last body end, not the text one
        assert '<script src="marimo/assets/x.js">' in page
        assert MENTION in page  # text is neither rewritten nor refused
        assert all(f'href="{target}"' in page for target in ("index.html", *LEGAL_PAGES))


def test_the_default_folder_is_the_repos_tutorials(tmp_path: Path, token: str, exported: list[str]) -> None:
    assert main(["--out", str(tmp_path / "site")]) == 0
    assert exported
    assert all((TUTORIALS_DIR / name).is_file() for name in exported)


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"GENESIS_USER": "someone"},
        {"GENESIS_USER": "someone", "GENESIS_PASSWORD": "a-long-enough-password"},
        {"GENESIS_TOKEN": "short"},
        {"GENESIS_TOKEN": "broken\ntoken-value"},
    ],
    ids=["none", "user-without-password", "no-token", "token-too-short-to-scan", "token-with-a-newline"],
)
def test_without_a_usable_token_nothing_is_exported(
    tmp_path: Path,
    no_genesis_env: None,
    monkeypatch: pytest.MonkeyPatch,
    exported: list[str],
    env: dict[str, str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    _notebook(tmp_path / "tutorials", "01_first.py", "Tutorial 1: one.")
    assert _run(tmp_path) == 2
    assert exported == []
    assert not (tmp_path / "site").exists()
    assert "GENESIS_TOKEN" in capsys.readouterr().err


@pytest.mark.parametrize("kind", ["a-file", "a-folder-with-content", "a-link-to-a-folder"])
def test_an_out_that_is_taken_is_refused_and_left_alone(
    tmp_path: Path, token: str, exported: list[str], kind: str
) -> None:
    _notebook(tmp_path / "tutorials", "01_first.py", "Tutorial 1: one.")
    kept = tmp_path / "site"
    if kind == "a-link-to-a-folder":
        kept = tmp_path / "elsewhere" / "keep.txt"
        kept.parent.mkdir()
        (tmp_path / "site").symlink_to(kept.parent, target_is_directory=True)
    elif kind == "a-folder-with-content":
        kept.mkdir()
        kept = kept / "keep.txt"
    kept.write_text("mine", encoding="utf-8")
    assert _run(tmp_path) == 2
    assert exported == []
    assert kept.read_text(encoding="utf-8") == "mine"


@pytest.mark.parametrize(
    ("prepare", "reason"),
    [
        (lambda folder: folder.mkdir(), "no tutorials"),
        (lambda folder: _notebook(folder, "01_first.py", None), "has no docstring"),
    ],
    ids=["no-tutorials", "no-docstring"],
)
def test_nothing_to_list_fails_and_removes_the_folder(
    tmp_path: Path,
    token: str,
    exported: list[str],
    prepare: Callable[[Path], None],
    reason: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    prepare(tmp_path / "tutorials")
    assert _run(tmp_path) == 1
    assert exported == []
    assert not (tmp_path / "site").exists()
    assert reason in capsys.readouterr().err


@pytest.mark.parametrize(
    ("code", "frame", "reason"),
    [
        (1, PAGE, "did not run to the end"),
        (0, "{}", "has no </body>"),
        # Another marimo version's viewer: the rewrite only knows the installed one.
        (
            0,
            PAGE.replace(
                "{}", '<script src="https://cdn.jsdelivr.net/npm/@marimo-team/frontend@0.0.1/dist/a.js"></script>{}'
            ),
            "still links cdn.jsdelivr.net",
        ),
    ],
    ids=["failed-export", "page-without-a-body-end", "viewer-left-on-the-cdn"],
)
def test_a_page_that_cannot_be_kept_removes_the_folder(
    tmp_path: Path,
    token: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    code: int,
    frame: str,
    reason: str,
) -> None:
    _fake_export(monkeypatch, tmp_path, [], code=code, frame=frame)
    _notebook(tmp_path / "tutorials", "01_first.py", "Tutorial 1: one.")
    assert _run(tmp_path) == 1
    assert not (tmp_path / "site").exists()
    assert reason in capsys.readouterr().err


def test_an_unexpected_error_still_removes_the_folder(tmp_path: Path, token: str, exported: list[str]) -> None:
    (tmp_path / "tutorials").mkdir()
    (tmp_path / "tutorials" / "01_first.py").write_text("def broken(:\n", encoding="utf-8")
    with pytest.raises(SyntaxError):
        _run(tmp_path)
    assert not (tmp_path / "site").exists()


@pytest.mark.parametrize(
    ("docstring", "body", "extra", "file"),
    [
        ("Tutorial 1: one.", f"<p>{TOKEN.upper()}</p>", None, "01_first.html"),
        (f"Tutorial 1: {TOKEN}.", "<p>page</p>", None, "index.html"),
        ("Tutorial 1: one.", f'<a href="data:text/csv;base64,{EMBEDDED}">data</a>', None, "01_first.html"),
        ("Tutorial 1: one.", "<p>page</p>", {"files/data.csv": f"t;{TOKEN}"}, "files/data.csv"),
    ],
    ids=["in-a-page", "in-the-index", "in-an-embedded-file", "in-a-subfolder"],
)
def test_a_credential_in_any_file_removes_the_folder_and_names_only_the_file(
    tmp_path: Path,
    token: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    docstring: str,
    body: str,
    extra: dict[str, str] | None,
    file: str,
) -> None:
    _fake_export(monkeypatch, tmp_path, [], body=body, extra=extra)
    _notebook(tmp_path / "tutorials", "01_first.py", docstring)
    assert _run(tmp_path) == 1
    assert not (tmp_path / "site").exists()
    err = capsys.readouterr().err
    assert f"{file} contains a GENESIS credential" in err
    assert token.lower() not in err.lower()


@pytest.mark.parametrize(
    ("cell", "reason"),
    [
        ('raise RuntimeError("boom")', "did not run to the end"),
        ('import marimo as mo\n\n    mo.stop(True, "nothing to show")', "did not run to the end"),
        (f"{TOKEN_FROM_ENV}\n\n    token", "contains a GENESIS credential"),
        (
            f'{TOKEN_FROM_ENV}\n    import pandas as pd\n\n    pd.DataFrame({{"t": [token]}})',
            "contains a GENESIS credential",
        ),
    ],
    ids=["failing-cell", "stopped-cell", "token-in-an-output", "token-in-a-table"],
)
def test_the_real_marimo_export_is_caught(
    tmp_path: Path, token: str, cell: str, reason: str, capsys: pytest.CaptureFixture[str]
) -> None:
    # No fake here: marimo's exit code and page format are what the build relies on.
    _notebook(tmp_path / "tutorials", "01_first.py", "Tutorial 1: one.", cell=cell)
    assert _run(tmp_path) == 1
    assert not (tmp_path / "site").exists()
    assert reason in capsys.readouterr().err


def test_the_real_marimo_page_takes_the_links_and_the_viewer(tmp_path: Path, token: str) -> None:
    _notebook(tmp_path / "tutorials", "01_first.py", "Tutorial 1: one.")
    assert _run(tmp_path) == 0
    site = tmp_path / "site"
    page = (site / "01_first.html").read_text(encoding="utf-8")
    assert "__MARIMO_EXPORT_CONTEXT__" in page
    assert page.count(build_site._BAR) == 1
    assert page.rfind("</body>") == page.index(build_site._BAR) + len(build_site._BAR)
    assert "cdn.jsdelivr.net" not in page
    viewer_files = set(re.findall(r'(?:src|href)="(marimo/[^"]+)"', page))
    assert viewer_files
    assert all((site / name).is_file() for name in viewer_files)
    assert "Apache License" in (site / "marimo" / "LICENSE.txt").read_text(encoding="utf-8")
    assert all((site / "marimo" / name).stat().st_size > 0 for name in ("third_party.txt", "third_party_licenses.txt"))


@pytest.mark.parametrize(
    ("files", "missing"),
    [
        (["marimo-1.0.dist-info/licenses/LICENSE", "marimo/third_party.txt", "marimo/third_party_licenses.txt"], None),
        (["marimo-1.0.dist-info/LICENSE", "marimo/third_party.txt", "marimo/third_party_licenses.txt"], None),
        (["marimo/third_party.txt", "marimo/third_party_licenses.txt"], "LICENSE.txt"),
        # A license of a project marimo bundles is not marimo's own.
        (["marimo/_lsp/zod/LICENSE", "marimo/third_party.txt", "marimo/third_party_licenses.txt"], "LICENSE.txt"),
        (["marimo-1.0.dist-info/LICENSE", "marimo/third_party_licenses.txt"], "third_party.txt"),
    ],
    ids=["license-in-licenses", "license-in-dist-info", "no-license", "bundled-license-only", "no-package-list"],
)
def test_the_viewer_ships_only_with_marimos_license_and_notices(
    tmp_path: Path,
    token: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    files: list[str],
    missing: str | None,
) -> None:
    installed = tmp_path / "site-packages"
    for name in files:
        (installed / name).parent.mkdir(parents=True, exist_ok=True)
        (installed / name).write_text(name, encoding="utf-8")
    marimo = SimpleNamespace(
        files=[importlib.metadata.PackagePath(name) for name in files],
        version="1.0",
        locate_file=lambda path: installed / str(path),
    )
    monkeypatch.setattr(importlib.metadata, "distribution", lambda _name: marimo)
    viewer = build_site._viewer_source()
    if missing is None:
        assert isinstance(viewer, build_site._Viewer)
        assert viewer.notices["LICENSE.txt"].read_text(encoding="utf-8").endswith("LICENSE")
        return
    assert viewer == f"the installed marimo lacks {missing} to ship with its viewer"
    _notebook(tmp_path / "tutorials", "01_first.py", "Tutorial 1: one.")
    assert _run(tmp_path) == 1
    assert not (tmp_path / "site").exists()
    assert viewer in capsys.readouterr().err


def test_no_tutorial_imports_a_library_whose_output_fetches_from_other_hosts() -> None:
    for notebook in sorted(TUTORIALS_DIR.glob("*.py")):
        tree = ast.parse(notebook.read_text(encoding="utf-8"))
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imported |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
        assert not {name.split(".")[0] for name in imported} & OFF_SITE_LIBRARIES, notebook.name


def test_the_workflow_publishes_by_hand_only_and_after_the_live_test() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert set(workflow[True]) == {"workflow_dispatch"}  # YAML 1.1 reads the key `on` as true
    tick_box = workflow[True]["workflow_dispatch"]["inputs"]["publish"]
    assert (tick_box["type"], tick_box["default"]) == ("boolean", False)
    steps = workflow["jobs"]["tutorials"]["steps"]
    runs = [step.get("run", "") for step in steps]
    live = next(position for position, run in enumerate(runs) if "pytest -m live" in run)
    build = next(position for position, run in enumerate(runs) if "scripts/build_site.py" in run)
    assert live < build
    assert all(step["if"] == "inputs.publish" for step in steps[build:])
    assert steps[build]["env"] == steps[live]["env"]  # the same token, or tutorials 3 to 5 stop
    publish = workflow["jobs"]["publish"]
    assert publish["needs"] == "tutorials"
    assert publish["if"] == "inputs.publish && github.ref_name == github.event.repository.default_branch"
