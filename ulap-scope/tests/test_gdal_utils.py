"""The shared GDAL helpers fail loudly and actionably — both branches proven.

These exist because the helpers were briefly copy-pasted into two stages, and
this repository's history shows exactly how hand-synced copies end (they drift).
The tests pin the shared module's contract: resolution precedence, the
not-found message, and the error-context wrapper.
"""
from __future__ import annotations

import subprocess
import sys

import pytest

from ulap_scope.gdal_utils import gdal_tool, run_gdal


def test_env_override_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("ULAP_GDAL_BIN", str(tmp_path))
    assert gdal_tool("gdalwarp") == str(tmp_path / "gdalwarp")


def test_path_resolution_when_no_override(monkeypatch):
    monkeypatch.delenv("ULAP_GDAL_BIN", raising=False)
    monkeypatch.setattr("shutil.which", lambda tool: f"/fake/bin/{tool}")
    assert gdal_tool("gdal_translate") == "/fake/bin/gdal_translate"


def test_not_found_is_actionable(monkeypatch):
    monkeypatch.delenv("ULAP_GDAL_BIN", raising=False)
    monkeypatch.setattr("shutil.which", lambda tool: None)
    with pytest.raises(SystemExit) as exc:
        gdal_tool("gdalinfo")
    msg = str(exc.value)
    assert "gdalinfo" in msg and "ULAP_GDAL_BIN" in msg


def test_run_gdal_success_returns_stdout():
    r = run_gdal([sys.executable, "-c", "print('ok')"], stage="test")
    assert r.stdout.strip() == "ok"


def test_run_gdal_failure_carries_command_and_stderr():
    with pytest.raises(SystemExit) as exc:
        run_gdal(
            [sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"],
            stage="test-stage",
        )
    msg = str(exc.value)
    assert "test-stage" in msg and "rc=3" in msg and "boom" in msg


def test_run_gdal_truncates_huge_stderr():
    with pytest.raises(SystemExit) as exc:
        run_gdal(
            [sys.executable, "-c",
             "import sys; sys.stderr.write('x'*10000); sys.exit(1)"],
            stage="test",
        )
    assert len(str(exc.value)) < 2000
