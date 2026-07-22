"""Config + portability tests (fast)."""
import os
from pathlib import Path
from ulap_scope.config import Config, load_config
from ulap_scope import geo


def test_config_paths_are_paths():
    c = load_config()
    for p in (c.data_dir, c.work_dir, c.build_dir, c.manifest_path, c.out_dir, c.stages_dir):
        assert isinstance(p, Path)

def test_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("ULAP_PROJECT_ROOT", str(tmp_path))
    c = load_config()
    assert c.project_root == tmp_path
    assert c.data_dir == tmp_path / "bbd-geo-portal"

def test_subprocess_env_is_portable():
    c = load_config()
    e = c.env()
    assert e["ULAP_PROJECT_ROOT"] == str(c.project_root)
    assert e["PYTHONNOUSERSITE"] == "1"           # keep envs isolated

def test_sweep_freqs_valid_for_ground_material():
    # every sweep frequency must be physical for BOTH scene materials
    c = load_config()
    for f in c.sweep_freqs_hz:
        assert geo.freq_valid_for("medium_dry_ground", f), f"{f} out of ground range"
        assert geo.freq_valid_for("concrete", f)

def test_mmwave_freqs_need_concrete_only():
    # mmWave is out of range for the ground material -> concrete-only scene required
    c = load_config()
    for f in c.mmwave_freqs_hz:
        assert not geo.freq_valid_for("medium_dry_ground", f)
        assert geo.freq_valid_for("concrete", f)

def test_stage_scripts_present():
    c = load_config()
    for s in ("clip_study_area.py", "preprocess_scene.py", "build_scene.py",
              "export_mitsuba.py", "sionna_coverage.py", "sionna_mmwave_sinr.py",
              "sionna_animate_rx.py"):
        assert (c.stages_dir / s).exists(), f"missing vendored stage {s}"
