"""
Execute every example notebook end to end.

A notebook that is read but never run is a claim, not evidence: it can rot the
day a dependency, a data file, or a helper changes shape, and nothing will say
so. This test runs each of the four numbered notebooks top to bottom with a
fresh kernel and fails on the first errored cell — so "the notebooks work"
stays a checked property rather than a remembered one.

The notebooks are committed with outputs stripped (that is deliberate: stored
outputs are exactly the kind of stale artefact the rest of this repository
exists to prevent), so execution is the only way to know they still run.

Requires nbclient + ipykernel; skips with a visible reason when they are
absent so a minimal environment still passes the rest of the suite.

    cd examples && python -m pytest tests/test_notebooks_execute.py -q
"""
from __future__ import annotations

import pathlib

import pytest

nbformat = pytest.importorskip("nbformat", reason="nbformat not installed")
nbclient = pytest.importorskip("nbclient", reason="nbclient not installed")
pytest.importorskip("ipykernel", reason="ipykernel not installed")

NOTEBOOK_DIR = pathlib.Path(__file__).resolve().parent.parent / "notebooks"
NOTEBOOKS = sorted(NOTEBOOK_DIR.glob("0*.ipynb"))


def test_all_four_notebooks_are_present() -> None:
    names = [p.name for p in NOTEBOOKS]
    assert len(names) == 4, f"expected the four numbered notebooks, found {names}"


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: p.name)
def test_notebook_executes_clean(path: pathlib.Path) -> None:
    nb = nbformat.read(path, as_version=4)
    client = nbclient.NotebookClient(
        nb, timeout=1200, resources={"metadata": {"path": str(NOTEBOOK_DIR)}}
    )
    client.execute()
    errors = [
        out
        for cell in nb.cells
        for out in cell.get("outputs", [])
        if out.get("output_type") == "error"
    ]
    assert not errors, f"{path.name}: {errors[0].get('ename')}: {errors[0].get('evalue')}"
