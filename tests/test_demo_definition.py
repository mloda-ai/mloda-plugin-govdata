"""The marimo demos must define their apps without running any cell (no network); demo and doc imports must exist."""

import ast
import importlib.util
import re
from pathlib import Path
from typing import TypeGuard

# A hard import on purpose: tox installs the demo extra, so a broken marimo
# dependency set must fail this test instead of skipping it.
import marimo
import pytest

DEMO_PATH = Path(__file__).resolve().parents[1] / "demos" / "govdata_demo.py"
RECIPES_DIR = DEMO_PATH.parents[1] / "recipes"
DEMO_PATHS = sorted(path for path in DEMO_PATH.parent.glob("*.py") if not path.name.startswith("_"))
REPO_ROOT = DEMO_PATH.parents[1]
# Only unindented ```python fences, the one style the docs use.
PYTHON_FENCE = re.compile(r"^```python\n(.*?)^```", re.MULTILINE | re.DOTALL)
DOC_PATHS = [
    path
    for path in [REPO_ROOT / "README.md", *sorted((REPO_ROOT / "docs").glob("*.md"))]
    if PYTHON_FENCE.search(path.read_text(encoding="utf-8"))
]


def test_globs_find_all_demos_and_docs() -> None:
    # A silently empty glob must fail, not skip the parametrized tests.
    assert {DEMO_PATH, DEMO_PATH.with_name("berlin_wahl_2026_demo.py")} <= set(DEMO_PATHS)
    assert {REPO_ROOT / "README.md", REPO_ROOT / "docs" / "schnellstart.md"} <= set(DOC_PATHS)


@pytest.mark.parametrize("demo_path", DEMO_PATHS, ids=lambda path: path.stem)
def test_demo_defines_marimo_app(demo_path: Path) -> None:
    spec = importlib.util.spec_from_file_location(demo_path.stem, demo_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert isinstance(module.app, marimo.App)


@pytest.mark.parametrize("path", DEMO_PATHS + DOC_PATHS, ids=lambda path: str(path.relative_to(REPO_ROOT)))
def test_every_mloda_name_it_imports_exists(path: Path) -> None:
    # Cell bodies and doc snippets never run here, so a moved module or a renamed export only shows up this way.
    imports = [
        node
        for tree in _python_trees(path)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in {"mloda", "mloda_plugin_govdata"}
    ]
    assert imports, f"{path.name} imports nothing from mloda or mloda_plugin_govdata"
    missing = [
        f"{node.module}.{alias.name}"
        for node in imports
        for alias in node.names
        if not hasattr(importlib.import_module(str(node.module)), alias.name)
    ]
    assert missing == []


def _demo_tree(path: Path = DEMO_PATH) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _python_trees(path: Path) -> list[ast.Module]:
    if path.suffix == ".py":
        return [_demo_tree(path)]
    # Every python fence must parse on its own; a REPL-style block fails here on purpose.
    blocks = PYTHON_FENCE.findall(path.read_text(encoding="utf-8"))
    return [ast.parse(block, filename=f"{path.name}, python block {n}") for n, block in enumerate(blocks, 1)]


def _recipe_files_the_demo_loads() -> set[str]:
    calls = [
        node
        for node in ast.walk(_demo_tree())
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "load_recipe"
    ]
    return {
        leaf.value
        for call in calls
        for leaf in ast.walk(call)
        if isinstance(leaf, ast.Constant) and isinstance(leaf.value, str)
    }


def test_every_recipe_file_the_demo_loads_is_shipped() -> None:
    names = _recipe_files_the_demo_loads()
    assert names, "the recipe chapters load recipe files"
    assert [name for name in sorted(names) if not (RECIPES_DIR / name).is_file()] == []


def _returned_names(cell: ast.FunctionDef) -> set[str]:
    last = cell.body[-1]
    if not isinstance(last, ast.Return) or last.value is None:
        return set()
    values = last.value.elts if isinstance(last.value, ast.Tuple) else [last.value]
    return {value.id for value in values if isinstance(value, ast.Name)}


def _is_cell(node: ast.stmt) -> TypeGuard[ast.FunctionDef]:
    # ``@app.cell`` or, once code is hidden in the editor, ``@app.cell(hide_code=True)``.
    return isinstance(node, ast.FunctionDef) and any(
        ast.unparse(d.func if isinstance(d, ast.Call) else d) == "app.cell" for d in node.decorator_list
    )


def _is_markdown(cell: ast.FunctionDef) -> bool:
    body = [stmt for stmt in cell.body if not isinstance(stmt, ast.Return)]
    return (
        len(body) == 1
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Call)
        and ast.unparse(body[0].value.func) == "mo.md"
    )


def test_every_cell_after_the_credentials_guard_depends_on_it() -> None:
    # mo.stop skips only the cells that take a name from the stopped cell, directly or through another cell.
    cells = [node for node in _demo_tree().body if _is_cell(node)]
    guard = next(index for index, cell in enumerate(cells) if "mo.stop(" in ast.unparse(cell))
    reached = _returned_names(cells[guard])
    guarded: list[int] = []
    unguarded: list[int] = []
    for cell in cells[guard + 1 :]:
        if _is_markdown(cell):
            continue  # shown even without credentials
        if {arg.arg for arg in cell.args.args} & reached:
            guarded.append(cell.lineno)
            reached |= _returned_names(cell)
        else:
            unguarded.append(cell.lineno)
    assert guarded, "the Destatis cells follow the guard"
    assert unguarded == []
