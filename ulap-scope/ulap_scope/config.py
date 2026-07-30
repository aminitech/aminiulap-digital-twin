"""
ulap_scope.config -- central, portable configuration for the Ulap Scope
Barbados / Sionna-RT digital-twin pipeline.

Everything machine- or layout-specific lives here and is overridable by
environment variable, so the package can be dropped into the Ulap One repo and
re-pointed without editing code.

Env overrides (all optional):
  ULAP_PROJECT_ROOT   repo root that contains bbd-geo-portal/ and blender/
  ULAP_DATA_DIR       geoportal shapefiles root (default <root>/bbd-geo-portal)
  ULAP_WORK_DIR       working/output dir      (default <root>/blender)
  ULAP_BLENDER_BIN    Blender executable      (default: `blender` on PATH)
  ULAP_PREP_PY        python w/ geopandas+scipy+pyproj+pillow (prep stages)
  ULAP_RT_PY          python w/ sionna-rt (RT stages)
  ULAP_GDAL_BIN       dir with the GDAL CLIs  (default: resolved from PATH)
"""
from __future__ import annotations
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

def _default_root() -> Path:
    # <root>/ulap-scope/ulap_scope/config.py  -> repo root is three parents up
    return Path(__file__).resolve().parents[2]

@dataclass(frozen=True)
class Config:
    project_root: Path = field(default_factory=_default_root)

    # --- study area (Newton Burial Site, Barbados) ---
    epsg: int = 21292                        # Barbados 1938 / Barbados National Grid
    origin: tuple[float, float] = (32735.32016057213, 64854.73663833553)  # scene 0,0 in EPSG:21292
    center_lonlat: tuple[float, float] = (-59.533908, 13.088121)
    half_width_m: int = 1000                 # 2 km study box
    antenna_radius_m: int = 3000             # towers to include as candidate TX

    # --- RT defaults ---
    freq_hz: float = 3.5e9
    sweep_freqs_hz: tuple[float, ...] = (1.8e9, 3.5e9, 6.0e9, 10.0e9)   # <=10 GHz (ground material)
    mmwave_freqs_hz: tuple[float, ...] = (28e9, 60e9)                    # concrete-only
    tx_power_dbm: float = 33.0
    bandwidth_hz: float = 100e6
    cell_size_m: float = 5.0
    max_depth: int = 5
    samples_per_tx: int = 10**6

    # --- interpreters (override per machine via env; cross-platform defaults so
    #     a fresh clone runs without editing code) ---
    blender_bin: str = (os.environ.get("ULAP_BLENDER_BIN")
                        or shutil.which("blender")
                        or "/Applications/Blender.app/Contents/MacOS/Blender")
    # The prep and RT stages need different dependency sets (geopandas vs
    # sionna-rt); point them at separate interpreters via env. Both default to
    # the current interpreter so a single all-deps env also works out of the box.
    prep_py: str = os.environ.get("ULAP_PREP_PY") or sys.executable
    rt_py: str = os.environ.get("ULAP_RT_PY") or sys.executable

    # --- derived paths ---
    @property
    def data_dir(self) -> Path:
        return Path(os.environ.get("ULAP_DATA_DIR", self.project_root / "bbd-geo-portal"))

    @property
    def work_dir(self) -> Path:
        return Path(os.environ.get("ULAP_WORK_DIR", self.project_root / "blender"))

    @property
    def study_area_dir(self) -> Path:
        return self.data_dir / "study_area"

    @property
    def build_dir(self) -> Path:
        return self.work_dir / "scene_build"

    @property
    def manifest_path(self) -> Path:
        return self.build_dir / "scene_manifest.json"

    @property
    def towers_path(self) -> Path:
        return self.build_dir / "towers_near.json"

    @property
    def out_dir(self) -> Path:
        return self.work_dir / "sionna_out"

    @property
    def stages_dir(self) -> Path:
        # vendored stage scripts shipped with the package
        return Path(__file__).resolve().parent / "stages"

    def env(self) -> dict:
        """Environment for subprocess stage runs (portable paths)."""
        e = dict(os.environ)
        e["ULAP_PROJECT_ROOT"] = str(self.project_root)
        e["PYTHONNOUSERSITE"] = "1"
        e["DRJIT_NO_RTLD_DEEPBIND"] = "1"
        return e

def load_config() -> Config:
    root = os.environ.get("ULAP_PROJECT_ROOT")
    return Config(project_root=Path(root)) if root else Config()
