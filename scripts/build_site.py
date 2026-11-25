"""Build the tutorial web pages: one static page per tutorial plus an index (repo tooling, not shipped).

Usage:
    uv run --env-file .env python scripts/build_site.py --out site

Every tutorial runs against the live sources, so this needs network access and ``GENESIS_TOKEN``.
The pages load marimo's viewer from a copy in the site, not from a CDN. Some outputs (plotly, maps) still make the
viewer fetch from other hosts at runtime; a test keeps the libraries behind them out of the tutorials.
A cell that fails or stops, a page still linking the viewer on the CDN, missing viewer files, or a credential in a
page, removes ``--out`` again.
"""

from __future__ import annotations

import argparse
import ast
import base64
import binascii
import html
import importlib.metadata
import re
import shutil

# marimo's own export command, a fixed argument list, no shell.
import subprocess  # nosec B404
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

from mloda_plugin_govdata.feature_groups.destatis import GENESIS_ONLINE, DestatisCredentials, MissingCredentialsError
from mloda_plugin_govdata.recipes.credential_scan import environment_secrets

TUTORIALS_DIR = Path(__file__).resolve().parents[1] / "tutorials"
REPO_URL = "https://github.com/mloda-ai/mloda-plugin-govdata"
# marimo's command line, with a stopped cell counted as a failed one.
_MARIMO = Path(__file__).with_name("export_page.py")
# Where marimo's export links its viewer; the build points those links at the copy in the site instead.
_MARIMO_CDN = "cdn.jsdelivr.net"
_VIEWER_LINK = re.compile(r"""(?:src|href)=["']https?://""" + re.escape(_MARIMO_CDN))
# Site folder for the copy, and the files a page links at the top of marimo's static folder (not its own start page).
_VIEWER = "marimo"
_VIEWER_TOP_LEVEL = (".ico", ".png", ".json", ".webmanifest")
# Shipped next to the viewer with marimo's license: its bundled packages and their license texts.
_THIRD_PARTY = ("third_party.txt", "third_party_licenses.txt")
_BASE64_PAYLOAD = re.compile(r";base64,([A-Za-z0-9+/]+=*)")
_LINK = '<a href="{href}" style="color:inherit;text-decoration:underline"{lang}>{label}</a>'
_BETWEEN = '<span aria-hidden="true"> | </span>'
_LEGAL = _BETWEEN.join(
    _LINK.format(href=f"https://mloda.ai/{page}/", lang=' lang="de"', label=label)
    for page, label in (("impressum", "Impressum"), ("datenschutz", "Datenschutz"))
)
# Fixed, because marimo's viewer owns the page layout; bottom left, because its own badge sits bottom right.
_BAR = (
    '<nav aria-label="Tutorials and legal links" style="position:fixed;bottom:0;left:0;z-index:30;max-width:100%;'
    "box-sizing:border-box;padding:.3rem .8rem;font:13px system-ui,sans-serif;background:Canvas;color:CanvasText;"
    'border:1px solid #8886;border-width:1px 1px 0 0;border-top-right-radius:.4rem">'
    f"{_LINK.format(href='index.html', lang='', label='All tutorials')}{_BETWEEN}{_LEGAL}</nav>"
)


def export(notebook: Path, page: Path) -> int:
    """Run the notebook and write it as one static page; non-zero when a cell failed or stopped."""
    command = [sys.executable, str(_MARIMO), "export", "html", str(notebook), "-o", str(page), "-f"]
    return subprocess.run(command, check=False).returncode  # nosec B603


class _Viewer(NamedTuple):
    prefix: str  # what marimo's export writes before every viewer file
    static: Path
    notices: dict[str, Path]  # name in the site -> file in the installed marimo


def _viewer_source() -> _Viewer | str:
    """The installed marimo's viewer, or why it cannot be shipped."""
    marimo = importlib.metadata.distribution("marimo")
    package = Path(str(marimo.locate_file("marimo")))
    # In the dist-info folder, whichever layout; the package also bundles other projects' LICENSE files.
    licenses = [file for file in marimo.files or () if file.name == "LICENSE" and file.parts[0].endswith(".dist-info")]
    notices = {name: package / name for name in _THIRD_PARTY}
    if licenses:
        notices["LICENSE.txt"] = Path(str(marimo.locate_file(licenses[0])))
    missing = [name for name in ("LICENSE.txt", *_THIRD_PARTY) if not notices.get(name, Path()).is_file()]
    if missing:
        return f"the installed marimo lacks {', '.join(missing)} to ship with its viewer"
    # As marimo's get_default_asset_url writes the version.
    version = marimo.version.replace(".dev", "-dev")
    return _Viewer(f"https://{_MARIMO_CDN}/npm/@marimo-team/frontend@{version}/dist/", package / "_static", notices)


def _leaks(text: str, secrets: set[str], nested: int = 2) -> bool:
    """A secret in the text, or in what its base64 payloads (embedded files) decode to."""
    lowered = text.lower()
    if any(secret in lowered for secret in secrets):
        return True
    if nested == 0:
        return False
    for payload in _BASE64_PAYLOAD.findall(text):
        try:
            raw = base64.b64decode(payload + "=" * (-len(payload) % 4))
        except (binascii.Error, ValueError):
            continue
        decoded = (raw.decode(encoding, errors="replace") for encoding in ("utf-8", "latin-1"))
        if any(_leaks(inner, secrets, nested - 1) for inner in decoded):
            return True
    return False


def _first_docstring_line(notebook: Path) -> str | None:
    docstring = ast.get_docstring(ast.parse(notebook.read_text(encoding="utf-8")))
    return docstring.splitlines()[0].strip() if docstring else None


def _index(entries: Sequence[tuple[str, str]]) -> str:
    items = "\n".join(f'<li><a href="{html.escape(page)}">{html.escape(line)}</a></li>' for page, line in entries)
    built = datetime.now(UTC).strftime("%Y-%m-%d")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>mloda-plugin-govdata tutorials</title>
<style>body {{ font-family: system-ui, sans-serif; max-width: 44rem; margin: 2rem auto; padding: 0 1rem; }}</style>
</head>
<body>
<h1>mloda-plugin-govdata tutorials</h1>
<p>German open government data as typed tables. Each tutorial is shown with the results it gave.</p>
<ul>
{items}
</ul>
<p>These pages are a snapshot from {built}. The inputs on them do not react: to change a value, run the
notebooks yourself, see the <a href="{REPO_URL}#tutorials-and-demos">README</a>
(<span lang="de">auf Deutsch: <a href="{REPO_URL}/blob/main/docs/schnellstart.md">Schnellstart</a></span>).</p>
<p>Each tutorial ends with the source and the license of its data. The tutorial pages use marimo's viewer, served
from this site (<a href="{_VIEWER}/LICENSE.txt">license</a>; <a href="{_VIEWER}/third_party.txt">bundled packages</a>
and <a href="{_VIEWER}/third_party_licenses.txt">their licenses</a>).</p>
<p>Funded by the German Federal Ministry of Research, Technology and Space (BMFTR) through the
<a href="https://prototypefund.de">Prototype Fund</a>, supported by the
<a href="https://okfn.de">Open Knowledge Foundation Deutschland</a>. Funding code: 16IS26S11.</p>
<p>{_LEGAL}</p>
</body>
</html>
"""


def build(tutorials: Path, out: Path, secrets: set[str]) -> str | None:
    """Write every page and the index into ``out``; the reason when the result must not be kept."""
    notebooks = sorted(path for path in tutorials.glob("*.py") if not path.name.startswith("_"))
    if not notebooks:
        return f"no tutorials in {tutorials}"
    viewer = _viewer_source()
    if isinstance(viewer, str):
        return viewer
    # Only links: a notebook may mention the CDN in its text.
    rewrite = re.compile(r"""((?:src|href)=["'])""" + re.escape(viewer.prefix))
    entries: list[tuple[str, str]] = []
    for notebook in notebooks:
        line = _first_docstring_line(notebook)
        if line is None:
            return f"{notebook.name} has no docstring for its index line"
        page = f"{notebook.stem}.html"
        if export(notebook, out / page) != 0:
            return f"{notebook.name} did not run to the end"
        text = rewrite.sub(lambda link: f"{link.group(1)}{_VIEWER}/", (out / page).read_text(encoding="utf-8"))
        if _VIEWER_LINK.search(text):
            return f"{page} still links {_MARIMO_CDN}"
        # The last </body>: notebook code or an output may hold the tag as text.
        head, body_end, tail = text.rpartition("</body>")
        if not body_end:
            return f"{page} has no </body> to put the legal links before"
        (out / page).write_text(head + _BAR + body_end + tail, encoding="utf-8")
        entries.append((page, line))
    shutil.copytree(viewer.static / "assets", out / _VIEWER / "assets")
    for file in viewer.static.iterdir():
        if file.is_file() and file.suffix in _VIEWER_TOP_LEVEL:
            shutil.copyfile(file, out / _VIEWER / file.name)
    for name, notice in viewer.notices.items():
        shutil.copyfile(notice, out / _VIEWER / name)
    (out / "index.html").write_text(_index(entries), encoding="utf-8")
    # The viewer folder is a copy of the installed package, not output of a notebook run.
    written = (path for path in out.rglob("*") if path.is_file() and path.relative_to(out).parts[0] != _VIEWER)
    for file in sorted(written):
        if _leaks(file.read_text(encoding="utf-8", errors="replace"), secrets):
            return f"{file.relative_to(out)} contains a GENESIS credential"  # the file, never the value
    return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True, help="a new or empty folder for the pages")
    parser.add_argument("--tutorials", type=Path, default=TUTORIALS_DIR, help="the folder with the notebooks")
    args = parser.parse_args(argv)

    # The same cases stop the tutorials that need a token, and a stopped cell does not fail its export.
    try:
        credentials = DestatisCredentials.from_env(GENESIS_ONLINE)
    except (MissingCredentialsError, ValueError):
        credentials = None
    secrets = environment_secrets()
    token = credentials.token if credentials is not None else None
    if token is None or token.lower() not in secrets:
        # A token too short to look for in the pages is refused too.
        print("Set GENESIS_TOKEN: the pages are built with the token and checked for it.", file=sys.stderr)
        return 2
    out: Path = args.out
    if out.is_symlink() or (out.exists() and (not out.is_dir() or any(out.iterdir()))):
        print(f"{out} is a link or not empty; pass a new or empty folder.", file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)

    problem: str | None = "the build broke off"
    try:
        problem = build(args.tutorials, out, secrets)
    finally:
        if problem is not None:  # also on an error nobody expected
            shutil.rmtree(out)
            print(f"{problem}; {out} removed.", file=sys.stderr)
    if problem is not None:
        return 1
    print(f"{out}: pages and index written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
