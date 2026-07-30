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
  ULAP_BLENDER_BIN    Blender executable
  ULAP_PREP_PY        python w/ geopandas+scipy+pyproj+pillow (prep stages)
  ULAP_RT_PY          python w/ sionna-rt (RT stages)

Nothing here hard-codes one developer's machine. With no environment set, the
three tool defaults resolve against the machine actually running the code:
Blender from PATH (or the standard macOS/Windows install location if that is
where it is), and both stage interpreters from the interpreter running the CLI.
`ulap-scope info` reports whether each one is really there -- see `tool_status`.
"""
from __future__ import annotations
import os, shutil, sys
from dataclasses import dataclass, field
from pathlib import Path

def _default_root() -> Path:
    # <root>/ulap-scope/ulap_scope/config.py  -> repo root is three parents up
    return Path(__file__).resolve().parents[2]

# Standard per-OS install locations, checked only if `blender` is not on PATH.
# Nothing is assumed to exist: each is tested before it is used.
_BLENDER_FALLBACKS = (
    "/Applications/Blender.app/Contents/MacOS/Blender",          # macOS
    "/usr/bin/blender", "/usr/local/bin/blender",                # Linux distro / manual
    "/var/lib/flatpak/exports/bin/org.blender.Blender",          # Linux flatpak
    r"C:\Program Files\Blender Foundation\Blender 4.4\blender.exe",   # Windows
)

def _default_blender_bin() -> str:
    """Blender executable: $ULAP_BLENDER_BIN, else PATH, else a standard install."""
    env = os.environ.get("ULAP_BLENDER_BIN")
    if env:
        return env
    found = shutil.which("blender")
    if found:
        return found
    for candidate in _BLENDER_FALLBACKS:
        if Path(candidate).exists():
            return candidate
    # Not installed. Return the bare command rather than a dead absolute path, so
    # the failure reads as "blender: not found" instead of a stranger's home dir.
    return "blender"

def _default_prep_py() -> str:
    """Prep interpreter: $ULAP_PREP_PY, else the interpreter running this code."""
    return os.environ.get("ULAP_PREP_PY") or sys.executable or "python3"

def _default_rt_py() -> str:
    """RT interpreter: $ULAP_RT_PY, else the interpreter running this code."""
    return os.environ.get("ULAP_RT_PY") or sys.executable or "python3"

def _tool_exists(path: str) -> bool:
    """True if `path` names a runnable program (absolute/relative path or on PATH)."""
    if not path:
        return False
    if os.sep in path or (os.altsep and os.altsep in path):
        return os.path.isfile(path) and os.access(path, os.X_OK)
    return shutil.which(path) is not None

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

    # --- interpreters (override per machine) ---
    # default_factory, not a plain default: the env var is read when a Config is
    # built, not when this module is first imported. Setting ULAP_* after import
    # therefore still takes effect, which is what the docstring above promises.
    blender_bin: str = field(default_factory=_default_blender_bin)
    prep_py: str = field(default_factory=_default_prep_py)
    rt_py: str = field(default_factory=_default_rt_py)

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

    # --- honesty about the toolchain -------------------------------------
    def tool_status(self, probe: bool = True) -> list[dict]:
        """Report each external tool: where it resolved to, and whether it is there.

        Returns one dict per tool with keys:
          name    short label ("blender_bin")
          env     the environment variable that overrides it
          path    the resolved command or path
          source  "env" if an override is set, else "auto"
          ok      True if the command exists and is executable
          status  "ok" | "missing" | "incomplete" | "unknown"
          note    a plain-English explanation when something is missing or unproven

        `ok` and `status` say different things on purpose: an interpreter that
        exists but has none of its stage dependencies is `ok=True, incomplete` --
        the file is there, the capability is not.

        `probe=False` skips the (subprocess) check that an interpreter really
        carries its stage dependencies, and reports existence only.
        """
        specs = (
            ("blender_bin", "ULAP_BLENDER_BIN", self.blender_bin, None,
             "needed only to BUILD a new scene (build, export); the exported "
             "Mitsuba scenes are committed, so the RT stages do not need it"),
            ("prep_py", "ULAP_PREP_PY", self.prep_py, "geopandas",
             "needed for clip, preprocess, basemap"),
            ("rt_py", "ULAP_RT_PY", self.rt_py, "sionna.rt",
             "needed for coverage, analysis, mmwave-sinr, terrain-ground, animate"),
        )
        out = []
        for name, var, path, module, purpose in specs:
            overridden = bool(os.environ.get(var))
            ok = _tool_exists(path)
            if not ok:
                note = f"NOT FOUND -- {purpose}. Set {var} to point at it."
            elif module is None:
                note = purpose
            else:
                has = self._has_module(path, module) if probe else None
                if has is True:
                    note = purpose
                elif has is False:
                    note = (f"found, but it does not provide `{module}` -- {purpose}. "
                            f"Set {var} to an interpreter that has it.")
                else:
                    note = f"{purpose} (dependency check skipped)"
            out.append({"name": name, "env": var, "path": path,
                        "source": "env" if overridden else "auto",
                        "ok": ok, "note": note})
        return out

    @staticmethod
    def _has_module(interpreter: str, module: str) -> bool | None:
        """True/False if `interpreter` provides `module`; None if unknowable.

        Uses `find_spec` rather than a real import: importing `sionna.rt` pulls in
        Mitsuba and Dr.Jit and can take tens of seconds, which is too slow for a
        command whose whole job is to answer quickly.
        """
        import subprocess
        code = ("import importlib.util as u, sys; "
                f"sys.exit(0 if u.find_spec({module!r}) else 1)")
        try:
            r = subprocess.run([interpreter, "-c", code],
                               capture_output=True, timeout=60)
            return r.returncode == 0
        except Exception:
            return None

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
