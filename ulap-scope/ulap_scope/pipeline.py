"""
ulap_scope.pipeline -- run the vendored stage scripts out-of-process, each with
the interpreter that has its dependencies. The pipeline spans three Python envs
(prep=geopandas, Blender=bpy+gdal+mitsuba, RT=sionna); a single interpreter
cannot host them, so each stage is a subprocess with a portable env.
"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
from .config import Config, load_config

def _run(cfg: Config, interp_and_args: list[str], stage: str) -> None:
    env = cfg.env()
    env["ULAP_WORK_DIR"] = str(cfg.work_dir)          # where scene_build/, mitsuba_scene/, sionna_out/ live
    print(f"\n=== [ulap-scope] {stage} ===\n  $ {' '.join(str(a) for a in interp_and_args)}")
    r = subprocess.run([str(a) for a in interp_and_args], env=env)
    if r.returncode != 0:
        raise SystemExit(f"stage '{stage}' failed (exit {r.returncode})")

def _stage(cfg: Config, name: str) -> Path:
    return cfg.stages_dir / name

# ---- prep (geopandas / gdal CLI / pillow) ----
def clip(cfg=None):
    cfg = cfg or load_config(); _run(cfg, [cfg.prep_py, _stage(cfg, "clip_study_area.py")], "clip")

def preprocess(cfg=None):
    cfg = cfg or load_config(); _run(cfg, [cfg.prep_py, _stage(cfg, "preprocess_scene.py")], "preprocess")

def basemap(cfg=None):
    cfg = cfg or load_config(); _run(cfg, [cfg.prep_py, _stage(cfg, "fetch_basemap.py")], "basemap")

# ---- Blender (bpy) ----
def build(cfg=None, mode="flat"):
    cfg = cfg or load_config()
    out = cfg.work_dir / (f"ulap-bbd-memorial-twin_{'terrain' if mode=='terrain' else 'built'}.blend")
    base = cfg.work_dir / "ulap-bbd-memorial-twin.blend"
    _run(cfg, [cfg.blender_bin, "-b", base, "--python", _stage(cfg, "build_scene.py"),
               "--", cfg.manifest_path, out, mode], f"build:{mode}")

def export(cfg=None, mode="flat"):
    cfg = cfg or load_config()
    blend = cfg.work_dir / (f"ulap-bbd-memorial-twin_{'terrain' if mode=='terrain' else 'built'}.blend")
    xml = cfg.work_dir / (f"mitsuba_scene{'_terrain' if mode=='terrain' else ''}" ) / "scene.xml"
    _run(cfg, [cfg.blender_bin, "-b", blend, "--python", _stage(cfg, "export_mitsuba.py"),
               "--", xml], f"export:{mode}")

# ---- Sionna RT ----
def coverage(cfg=None, mode="flat"):
    cfg = cfg or load_config(); _run(cfg, [cfg.rt_py, _stage(cfg, "sionna_coverage.py"), mode], f"coverage:{mode}")

def analysis(cfg=None):
    cfg = cfg or load_config(); _run(cfg, [cfg.rt_py, _stage(cfg, "sionna_analysis.py")], "analysis")

def mmwave_sinr(cfg=None):
    cfg = cfg or load_config(); _run(cfg, [cfg.rt_py, _stage(cfg, "sionna_mmwave_sinr.py")], "mmwave_sinr")

def terrain_ground(cfg=None):
    cfg = cfg or load_config(); _run(cfg, [cfg.rt_py, _stage(cfg, "sionna_terrain_ground.py")], "terrain_ground")

def animate(cfg=None):
    cfg = cfg or load_config(); _run(cfg, [cfg.rt_py, _stage(cfg, "sionna_animate_rx.py")], "animate")

def run_all(cfg=None):
    """Full reproduce: prep -> build -> export -> RT, flat + terrain."""
    cfg = cfg or load_config()
    # preprocess builds the manifest (buildings/terrain/small basemap); basemap
    # then fetches full imagery and updates the manifest basemap in place.
    clip(cfg); preprocess(cfg); basemap(cfg)
    for m in ("flat", "terrain"):
        build(cfg, m); export(cfg, m); coverage(cfg, m)
    analysis(cfg); mmwave_sinr(cfg); terrain_ground(cfg); animate(cfg)
