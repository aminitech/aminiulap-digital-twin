"""
ulap_scope.cli -- command-line entry point.

    ulap-scope init [--defaults] [-o study.toml]   # interactive study wizard
    ulap-scope <stage> [--mode flat|terrain]
    ulap-scope all
    ulap-scope info

Stages: clip preprocess basemap build export coverage analysis mmwave sinr
        terrain-ground animate all info init
"""
from __future__ import annotations
import argparse, sys
from . import pipeline
from .config import load_config

STAGES = {
    "clip":            lambda c, a: pipeline.clip(c),
    "preprocess":      lambda c, a: pipeline.preprocess(c),
    "basemap":         lambda c, a: pipeline.basemap(c),
    "build":           lambda c, a: pipeline.build(c, a.mode),
    "export":          lambda c, a: pipeline.export(c, a.mode),
    "coverage":        lambda c, a: pipeline.coverage(c, a.mode),
    "analysis":        lambda c, a: pipeline.analysis(c),
    "mmwave-sinr":     lambda c, a: pipeline.mmwave_sinr(c),
    "terrain-ground":  lambda c, a: pipeline.terrain_ground(c),
    "animate":         lambda c, a: pipeline.animate(c),
    "all":             lambda c, a: pipeline.run_all(c),
}

def _info(cfg):
    print("Ulap Scope configuration")
    print("  project_root :", cfg.project_root)
    print("  data_dir     :", cfg.data_dir)
    print("  work_dir     :", cfg.work_dir)
    print("  manifest     :", cfg.manifest_path, "(exists:", cfg.manifest_path.exists(), ")")
    print("  out_dir      :", cfg.out_dir)
    print("  stages_dir   :", cfg.stages_dir)
    print("  blender_bin  :", cfg.blender_bin)
    print("  prep_py      :", cfg.prep_py)
    print("  rt_py        :", cfg.rt_py)
    print("  study centre :", cfg.center_lonlat, "EPSG:", cfg.epsg)

def main(argv=None):
    p = argparse.ArgumentParser(prog="ulap-scope", description="Ulap Scope digital-twin RF pipeline")
    p.add_argument("stage", choices=list(STAGES) + ["info", "init"])
    p.add_argument("--mode", choices=["flat", "terrain"], default="flat",
                   help="scene variant for build/export/coverage")
    p.add_argument("--defaults", action="store_true",
                   help="init: skip prompts, write the Barbados pilot defaults")
    p.add_argument("-o", "--output", default="study.toml",
                   help="init: where to write the study file")
    args = p.parse_args(argv)
    if args.stage == "init":                     # no config needed to start a study
        from .wizard import run_wizard
        run_wizard(defaults=args.defaults, output_path=args.output)
        return 0
    cfg = load_config()
    if args.stage == "info":
        _info(cfg); return 0
    STAGES[args.stage](cfg, args)
    return 0

if __name__ == "__main__":
    sys.exit(main())
