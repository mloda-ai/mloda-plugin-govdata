"""marimo's command line with ``mo.stop`` turned into an error (repo tooling, used by build_site.py).

marimo exports a notebook whose cell stopped without failing, so a page with missing results would pass.
Run this as a file: the process marimo starts for the notebook imports the main module again, so the
change below reaches the cells.
"""

import runpy

import marimo


def _stop(predicate: bool, output: object = None) -> None:
    if predicate:
        raise RuntimeError("mo.stop fired")


marimo.stop = _stop

if __name__ == "__main__":
    runpy.run_module("marimo", run_name="__main__")
