"""Shared GDAL CLI helpers for the pipeline stages.

One copy, imported by every stage that shells out to GDAL. This repository has
already paid once for hand-synced duplicate helpers drifting apart (see
tests/test_no_duplicate_stages.py's docstring), so path resolution and error
formatting live here and nowhere else.

Resolution order: $ULAP_GDAL_BIN (a directory containing the GDAL CLIs), then
PATH. Failures are loud and actionable — the operator gets the tool name and
the remedy, or the failing command and its stderr tail, never a raw traceback.
"""
from __future__ import annotations

import os
import shutil
import subprocess

# Enough stderr to diagnose; not enough to bury the message.
_STDERR_TAIL = 800


def gdal_tool(tool: str) -> str:
    """Resolve a GDAL CLI tool from $ULAP_GDAL_BIN or PATH (portable across OSes)."""
    override = os.environ.get("ULAP_GDAL_BIN")
    path = os.path.join(override, tool) if override else shutil.which(tool)
    if not path:
        raise SystemExit(
            f"{tool} not found. Install GDAL (on PATH) or set ULAP_GDAL_BIN to "
            "the directory containing the GDAL binaries."
        )
    return path


def run_gdal(cmd: list[str], stage: str = "gdal") -> subprocess.CompletedProcess:
    """Run a GDAL CLI with actionable context on failure instead of a raw traceback."""
    try:
        return subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "").strip()[-_STDERR_TAIL:]
        raise SystemExit(
            f"{stage}: {cmd[0]} failed (rc={e.returncode}) on "
            f"{' '.join(cmd[1:])}\nstderr: {stderr}"
        )
