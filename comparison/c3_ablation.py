#!/usr/bin/env python3
"""
C3 -- what does terrain and ground-following actually change, numerically?

Pre-registered in ``benchmarks/METHOD.md``. Metrics fixed before the first number was
produced: **median and p10/p90 path gain per variant, and the fraction of cells whose
best server changes**. The honest failure mode this study must expose is stated there
too: *"if the ground-following map differs little from the horizontal plane, the
nine-plane machinery is not earning its complexity."*

The three variants (exactly what the shipped stages do)
-------------------------------------------------------
======= ================================================================================
``flat``            ``mitsuba_scene`` (buildings on a z=0 plane, no terrain). TX z = h.
                    Measurement plane at z = 1.5 m.                  [sionna_coverage.py]
``terrain_plane``   ``mitsuba_scene_terrain`` (terrain draped, 54.7-115.5 m).
                    TX z = ground_z + h. ONE horizontal plane at zmax + 5 m -- the stage's
                    own compromise, which is 5 m above ground on the hilltops and ~60 m
                    above ground in the valleys.            [sionna_coverage.py terrain]
``terrain_ground``  Same terrain scene and TX heights, but a stack of K=9 horizontal
                    planes spanning the relief; each cell reads the plane nearest to
                    (local terrain + 1.5 m).               [sionna_terrain_ground.py]
======= ================================================================================

All three are solved on **one common grid** (identical centre, size and 8 m cells, taken
from the scene bounding box, which is identical in x/y for both Mitsuba scenes) so that
cells can be compared one-to-one. As of 2026-07-30 the shipped stages agree with this
grid: ``sionna_coverage.py`` moved 5 m -> 8 m and both stages now read one cell size from
``ULAP_RM_CELL_M``, so this study no longer has to harmonise anything. ``SAMPLES_PER_TX``
tracks the stages' raised 1e8 default for the same reason -- see
``docs/audits/2026-07-30-sampling-and-resolution.md``.

The control arm
---------------
"Fraction of cells whose best server changes" is meaningless without knowing how much of
it a *re-run of the same configuration* produces. RadioMapSolver is a Monte-Carlo
estimator, so two identical solves with different seeds already disagree on some cells.
Every variant is therefore run ``REPEATS`` times with different seeds, and the
same-variant / different-seed change fraction is reported as the **noise floor** that any
between-variant number must clear to mean anything.

Run:
    ULAP_WORK_DIR=/path/to/rtwork MPLBACKEND=Agg \\
        /path/to/venv-rt/bin/python comparison/c3_ablation.py
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import time
import traceback
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

import numpy as np

os.environ.setdefault("DRJIT_NO_RTLD_DEEPBIND", "1")
os.environ.setdefault("MPLBACKEND", "Agg")

REPO = Path(__file__).resolve().parent.parent
OUT_JSON = REPO / "comparison" / "results" / "c3.json"
OUT_FIG = REPO / "comparison" / "figures" / "c3_ablation.png"
WORK = Path(os.environ.get("ULAP_WORK_DIR", ""))

# --- pre-registered configuration -------------------------------------------
FREQ_HZ = 3.5e9
# Mirrors the shipped stages, which as of 2026-07-30 both read these two from the
# environment with these defaults. Keep in step.
CELL_M = float(os.environ.get("ULAP_RM_CELL_M", 8.0))
SAMPLES_PER_TX = int(float(os.environ.get("ULAP_RM_SAMPLES_PER_TX", 10 ** 8)))
MAX_DEPTH = 5
RX_AGL_M = 1.5
# Mirrors ulap-scope/ulap_scope/stages/sionna_terrain_ground.py, which is canonical.
# K is derived from a stated height tolerance rather than hardcoded, and the selection
# rule is CEILING (never below the target height) rather than nearest -- the nearest
# rule put the receiver underground in 29% of cells. Keep these two in step.
MAX_HEIGHT_ERR_M = float(os.environ.get("ULAP_GF_MAX_HEIGHT_ERR_M", 1.0))
REPEATS = 3                  # METHOD rule 1
SEEDS = [42, 43, 44]
VARIANTS = ("flat", "terrain_plane", "terrain_ground")


def md5(path: Path) -> str:
    h = hashlib.md5(usedforsecurity=False)  # content fingerprint, not a signature
    h.update(Path(path).read_bytes())
    return h.hexdigest()


def terrain_sampler(T):
    """Bilinear terrain height, identical to the stage's own ``terr()``."""
    nx, ny = T["nx"], T["ny"]
    z = np.array(T["z"], dtype=float).reshape(ny, nx)

    def terr(x, y):
        fx = (x - T["minx"]) / (T["maxx"] - T["minx"]) * (nx - 1)
        fy = (y - T["miny"]) / (T["maxy"] - T["miny"]) * (ny - 1)
        fx = np.clip(fx, 0, nx - 1)
        fy = np.clip(fy, 0, ny - 1)
        ix = fx.astype(int); iy = fy.astype(int)
        ix1 = np.minimum(ix + 1, nx - 1); iy1 = np.minimum(iy + 1, ny - 1)
        tx = fx - ix; ty = fy - iy
        return (z[iy, ix] * (1 - tx) * (1 - ty) + z[iy, ix1] * tx * (1 - ty)
                + z[iy1, ix] * (1 - tx) * ty + z[iy1, ix1] * tx * ty)
    return terr


def stats(db: np.ndarray) -> dict:
    finite = db[np.isfinite(db)]
    if finite.size == 0:
        return {"median_db": None, "p10_db": None, "p90_db": None,
                "mean_db": None, "finite_cells": 0, "no_coverage_fraction": 1.0}
    return {
        "median_db": round(float(np.median(finite)), 3),
        "p10_db": round(float(np.percentile(finite, 10)), 3),
        "p90_db": round(float(np.percentile(finite, 90)), 3),
        "mean_db": round(float(np.mean(finite)), 3),
        "p90_minus_p10_db": round(float(np.percentile(finite, 90)
                                        - np.percentile(finite, 10)), 3),
        "finite_cells": int(finite.size),
        "total_cells": int(db.size),
        "no_coverage_fraction": round(float(1.0 - finite.size / db.size), 5),
    }


def best_server_change(a: np.ndarray, b: np.ndarray, valid: np.ndarray) -> dict:
    n = int(valid.sum())
    if n == 0:
        return {"fraction": None, "n_compared": 0}
    diff = (a != b) & valid
    return {"fraction": round(float(diff.sum() / n), 5),
            "n_changed": int(diff.sum()), "n_compared": n}


def main() -> int:
    failures: list[dict] = []
    result: dict = {
        "study": "C3",
        "question": "What does terrain and ground-following actually change, numerically?",
        "pre_registered_metrics": ["median_path_gain_db", "p10_db", "p90_db",
                                   "best_server_change_fraction"],
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "host": {"node": platform.node(), "machine": platform.machine(),
                 "python": platform.python_version(), "executable": sys.executable},
        "config": {"freq_hz": FREQ_HZ, "cell_m": CELL_M, "samples_per_tx": SAMPLES_PER_TX,
                   "max_depth": MAX_DEPTH, "rx_agl_m": RX_AGL_M,
                   "repeats": REPEATS, "seeds": SEEDS, "ulap_work_dir": str(WORK),
                   "note": ("all three variants solved on ONE common grid (same centre, "
                            "size and cell size) so cells compare one-to-one. Since "
                            "2026-07-30 the shipped stages agree: sionna_coverage.py moved "
                            "5 m -> 8 m and both read ULAP_RM_CELL_M / "
                            "ULAP_RM_SAMPLES_PER_TX, so nothing is harmonised away here. "
                            "samples_per_tx was 1e7 in the superseded run of this study."),
                   "timing_caveat": ("Dr.Jit persists compiled kernels in an on-disk cache, so "
                                     "'cold' here means first solve in a fresh interpreter, NOT "
                                     "first solve ever. On a machine with an empty Dr.Jit cache "
                                     "the same cells took 0.16 s (flat), 0.16 s (terrain_plane) "
                                     "and 1.41 s (terrain_ground, 9 solves). Timing here is "
                                     "indicative; benchmarks/ owns the authoritative harness.")},
        "failures": failures,
    }

    import drjit as dr
    import mitsuba as mi
    from sionna.rt import load_scene, PlanarArray, Transmitter, RadioMapSolver

    scene_flat = WORK / "mitsuba_scene" / "scene.xml"
    scene_terr = WORK / "mitsuba_scene_terrain" / "scene.xml"
    mani_path = WORK / "scene_build" / "scene_manifest.json"
    towers_path = WORK / "scene_build" / "towers_near.json"
    for p in (scene_flat, scene_terr, mani_path, towers_path):
        if not p.exists():
            failures.append({"cell": "inputs", "error": f"missing input: {p}"})
            OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
            OUT_JSON.write_text(json.dumps(result, indent=2))
            print(f"ABORT: missing {p}; wrote failure record to {OUT_JSON}")
            return 1

    mani = json.loads(mani_path.read_text())
    T = mani["terrain"]
    _relief = float(T["zmax"] - T["zmin"])
    K_PLANES = max(2, int(np.ceil(_relief / MAX_HEIGHT_ERR_M)) + 1)   # matches the stage
    # K depends on the scene relief, so it is only knowable after the manifest loads.
    result["config"]["k_planes"] = K_PLANES
    result["config"]["k_planes_source"] = (
        f"ceil(relief {_relief:.2f} m / tolerance {MAX_HEIGHT_ERR_M:g} m) + 1")
    result["config"]["plane_selection_rule"] = "ceiling (never below target height)"

    towers = [t for t in json.loads(towers_path.read_text()) if t["in_scene"]]
    buildings_xy = [np.array(b["ring"]) for b in mani["buildings"]]
    result["inputs"] = {
        "scene_flat": str(scene_flat), "scene_terrain": str(scene_terr),
        "manifest": str(mani_path), "manifest_md5": md5(mani_path),
        "towers": [t["name"] for t in towers],
        "terrain_relief_m": round(float(T["zmax"] - T["zmin"]), 2),
        "terrain_zmin_m": T["zmin"], "terrain_zmax_m": T["zmax"],
        "n_buildings": len(mani["buildings"]),
        "scene": ("Newton, Barbados — the government scene the ray tracer was run on "
                  "(576 footprints). NOT the bundled open-data examples/ scene."),
    }

    # ---- common grid --------------------------------------------------------
    sc0 = load_scene(str(scene_terr))
    bb = sc0.mi_scene.bbox()
    cx = float((bb.min[0] + bb.max[0]) / 2); cy = float((bb.min[1] + bb.max[1]) / 2)
    sx = float(bb.max[0] - bb.min[0]); sy = float(bb.max[1] - bb.min[1])
    sc1 = load_scene(str(scene_flat))
    bb1 = sc1.mi_scene.bbox()
    grid = {"center_xy": [round(cx, 2), round(cy, 2)], "size_xy": [round(sx, 2), round(sy, 2)],
            "cell_m": CELL_M,
            "flat_scene_bbox": [[round(float(v), 1) for v in bb1.min],
                                [round(float(v), 1) for v in bb1.max]],
            "terrain_scene_bbox": [[round(float(v), 1) for v in bb.min],
                                   [round(float(v), 1) for v in bb.max]]}
    xy_identical = (abs(float(bb.min[0]) - float(bb1.min[0])) < 1e-3
                    and abs(float(bb.max[1]) - float(bb1.max[1])) < 1e-3)
    grid["flat_and_terrain_xy_extent_identical"] = bool(xy_identical)
    if not xy_identical:
        failures.append({"cell": "grid", "error": "flat and terrain scenes differ in x/y "
                                                  "extent; per-cell comparison is approximate"})
    result["grid"] = grid

    def build(scene_xml: Path, terrain: bool):
        sc = load_scene(str(scene_xml))
        sc.frequency = FREQ_HZ
        sc.tx_array = PlanarArray(num_rows=1, num_cols=1, pattern="tr38901", polarization="V")
        sc.rx_array = PlanarArray(num_rows=1, num_cols=1, pattern="dipole", polarization="V")
        for t in towers:
            z = float(t["ground_z"] + t["h"]) if terrain else float(t["h"])
            sc.add(Transmitter(t["name"].lower().replace(" ", "_"),
                               [float(t["x"]), float(t["y"]), z]))
        return sc

    solver = RadioMapSolver()

    def solve(sc, z, seed):
        t0 = time.monotonic()
        rm = solver(scene=sc, max_depth=MAX_DEPTH, cell_size=(CELL_M, CELL_M),
                    samples_per_tx=SAMPLES_PER_TX, center=[cx, cy, float(z)],
                    size=[sx, sy], orientation=[0., 0., 0.], seed=seed)
        pg = np.array(rm.path_gain)              # [num_tx, H, W], linear
        cc = np.array(rm.cell_centers)
        dr.sync_thread()
        return pg, cc, time.monotonic() - t0

    # ---- run the three variants --------------------------------------------
    runs: dict[str, list[dict]] = {v: [] for v in VARIANTS}
    per_tx: dict[str, list[np.ndarray]] = {v: [] for v in VARIANTS}
    cell_centers = None
    gf_underground_mask = None
    plane_z = np.linspace(T["zmin"] + RX_AGL_M, T["zmax"] + RX_AGL_M, K_PLANES)

    for rep, seed in enumerate(SEEDS[:REPEATS]):
        for variant in VARIANTS:
            try:
                if variant == "flat":
                    sc = build(scene_flat, terrain=False)
                    pg, cc, wall = solve(sc, RX_AGL_M, seed)
                    n_solves = 1
                elif variant == "terrain_plane":
                    sc = build(scene_terr, terrain=True)
                    pg, cc, wall = solve(sc, T["zmax"] + 5.0, seed)
                    n_solves = 1
                else:
                    sc = build(scene_terr, terrain=True)
                    stack, wall, cc = [], 0.0, None
                    for z in plane_z:
                        p, c, w = solve(sc, z, seed)
                        stack.append(p); wall += w
                        if cc is None:
                            cc = c
                    stack = np.stack(stack, axis=0)            # [K, num_tx, H, W]
                    terr = terrain_sampler(T)
                    target = terr(cc[..., 0], cc[..., 1]) + RX_AGL_M     # [H,W]
                    # ceiling, not nearest: the selected plane is always at or above
                    # the target height, so the receiver can never be underground.
                    kbest = np.clip(np.searchsorted(plane_z, target, side="left"),
                                    0, K_PLANES - 1)
                    pg = np.take_along_axis(stack, kbest[None, None], axis=0)[0]  # [num_tx,H,W]
                    n_solves = K_PLANES
                    if rep == 0:
                        # HISTORICAL: the nearest-plane rule landed the measurement point BELOW local
                        # ground: with K planes over R metres of relief the worst-case error
                        # is R/(2(K-1)). Those cells read zero path gain and look like shadow
                        # when they are really underground. Now fixed; this block should report 0 and
                        # exists to keep proving it.
                        terr_z = target - RX_AGL_M
                        gf_underground = plane_z[kbest] < terr_z
                        gf_underground_mask = gf_underground
                        result["ground_following_artifact"] = {
                            "underground_cell_fraction": round(float(np.mean(gf_underground)), 5),
                            "plane_spacing_m": round(float(plane_z[1] - plane_z[0]), 3),
                            "worst_case_height_error_m": round(
                                float((plane_z[1] - plane_z[0]) / 2), 3),
                            "selected_plane_minus_ground_m": {
                                "median": round(float(np.median(plane_z[kbest] - terr_z)), 2),
                                "p10": round(float(np.percentile(plane_z[kbest] - terr_z, 10)), 2),
                                "p90": round(float(np.percentile(plane_z[kbest] - terr_z, 90)), 2),
                            },
                            "note": ("Cells where the selected plane sits below local ground. "
                                     "They are indistinguishable from genuine shadow in the "
                                     "shipped map. The banding visible in the ground-following "
                                     "figure runs along terrain contours -- these bands, not "
                                     "radio physics."),
                        }
                        result["ground_following"] = {
                            "plane_z_m": [round(float(z), 2) for z in plane_z],
                            "planes_used_histogram": {int(k): int(np.sum(kbest == k))
                                                      for k in range(K_PLANES)},
                            "target_agl_m": RX_AGL_M,
                            "terrain_plane_height_above_local_ground_m": {
                                "median": round(float(np.median(
                                    (T["zmax"] + 5.0) - (target - RX_AGL_M))), 2),
                                "min": round(float(np.min(
                                    (T["zmax"] + 5.0) - (target - RX_AGL_M))), 2),
                                "max": round(float(np.max(
                                    (T["zmax"] + 5.0) - (target - RX_AGL_M))), 2),
                                "note": ("how far the single terrain_plane cut sits above local "
                                         "ground -- the quantity ground-following exists to fix"),
                            },
                        }

                if cell_centers is None:
                    cell_centers = cc
                per_tx[variant].append(pg)
                runs[variant].append({"repeat": rep, "seed": seed, "cold": rep == 0,
                                      "wall_s": round(wall, 3), "n_solves": n_solves,
                                      "mitsuba_variant": mi.variant()})
                print(f"  [{variant:>14} rep{rep} seed{seed}] {wall:6.2f} s  shape {pg.shape}")
            except Exception as exc:                            # METHOD rule 5
                failures.append({"cell": f"{variant}/rep{rep}", "error": repr(exc),
                                 "traceback": traceback.format_exc(limit=5)})
                print(f"  FAIL {variant} rep{rep}: {exc!r}")

    # ---- per-variant statistics (median of repeats) -------------------------
    best_db: dict[str, np.ndarray] = {}
    best_idx: dict[str, np.ndarray] = {}
    variants_out: dict = {}
    for variant in VARIANTS:
        if not per_tx[variant]:
            variants_out[variant] = {"status": "failed", "repeats": []}
            continue
        rep_stats, rep_best_db, rep_best_idx = [], [], []
        for pg in per_tx[variant]:
            b = pg.max(axis=0)
            with np.errstate(divide="ignore"):
                db = 10 * np.log10(b)
            db[~np.isfinite(db)] = np.nan
            rep_best_db.append(db)
            rep_best_idx.append(np.argmax(pg, axis=0))
            rep_stats.append(stats(db))
        med = float(np.median([s["median_db"] for s in rep_stats]))
        best_db[variant] = rep_best_db[0]
        best_idx[variant] = rep_best_idx[0]
        variants_out[variant] = {
            "status": "ok",
            "stats_repeat0": rep_stats[0],
            "median_db_across_repeats": [s["median_db"] for s in rep_stats],
            "median_db_spread_db": round(float(np.ptp([s["median_db"] for s in rep_stats])), 4),
            "median_db_of_repeat_medians": round(med, 3),
            "p10_db_across_repeats": [s["p10_db"] for s in rep_stats],
            "p90_db_across_repeats": [s["p90_db"] for s in rep_stats],
            "timing": runs[variant],
            "wall_s_median": round(float(np.median([r["wall_s"] for r in runs[variant]])), 3),
        }
        # per-repeat noise floor: same configuration, different seed
        if len(rep_best_idx) > 1:
            valid = np.isfinite(rep_best_db[0]) & np.isfinite(rep_best_db[1])
            variants_out[variant]["seed_noise_floor"] = {
                "best_server_change_fraction_same_variant_different_seed":
                    best_server_change(rep_best_idx[0], rep_best_idx[1], valid)["fraction"],
                "path_gain_rms_delta_db_same_variant_different_seed": round(float(np.sqrt(
                    np.nanmean((rep_best_db[0] - rep_best_db[1]) ** 2))), 4),
                "note": ("Monte-Carlo noise floor. Any between-variant change fraction that "
                         "does not clearly exceed this number is not a terrain effect."),
            }
    # the same numbers with the plane-stack artifact removed
    if gf_underground_mask is not None and "terrain_ground" in best_db:
        keep = ~gf_underground_mask
        variants_out["terrain_ground"]["stats_repeat0_excluding_underground_cells"] = {
            **stats(best_db["terrain_ground"][keep]),
            "cells_removed": int(gf_underground_mask.sum()),
            "note": ("terrain_ground with cells whose selected plane sits below local ground "
                     "removed from BOTH numerator and denominator; compare against "
                     "stats_repeat0 to see how much of the no-coverage area is the "
                     "discretisation, not the radio"),
        }
    result["variants"] = variants_out

    # ---- between-variant comparison ----------------------------------------
    pairs = {}
    for a, b in combinations([v for v in VARIANTS if v in best_db], 2):
        da, db_ = best_db[a], best_db[b]
        valid = np.isfinite(da) & np.isfinite(db_)
        delta = db_ - da
        pairs[f"{a}__vs__{b}"] = {
            "best_server_change_fraction": best_server_change(best_idx[a], best_idx[b],
                                                              valid)["fraction"],
            "best_server_n_changed": best_server_change(best_idx[a], best_idx[b],
                                                        valid)["n_changed"],
            "median_path_gain_delta_db": round(float(np.nanmedian(delta)), 3),
            "p10_delta_db": round(float(np.nanpercentile(delta, 10)), 3),
            "p90_delta_db": round(float(np.nanpercentile(delta, 90)), 3),
            "rms_delta_db": round(float(np.sqrt(np.nanmean(delta ** 2))), 3),
            "fraction_cells_within_3db": round(
                float(np.mean(np.abs(delta[valid]) <= 3.0)), 4),
            "fraction_cells_over_10db": round(
                float(np.mean(np.abs(delta[valid]) > 10.0)), 4),
            "n_cells_compared": int(valid.sum()),
            "no_coverage_fraction": {a: variants_out[a]["stats_repeat0"]["no_coverage_fraction"],
                                     b: variants_out[b]["stats_repeat0"]["no_coverage_fraction"]},
        }
    # the headline pair again, with the plane-stack artifact removed
    if (gf_underground_mask is not None and "terrain_ground" in best_db
            and "terrain_plane" in best_db):
        da, db_ = best_db["terrain_plane"], best_db["terrain_ground"]
        valid = np.isfinite(da) & np.isfinite(db_) & (~gf_underground_mask)
        delta = (db_ - da)[valid]
        pairs["terrain_plane__vs__terrain_ground__excluding_underground_cells"] = {
            "best_server_change_fraction": best_server_change(
                best_idx["terrain_plane"], best_idx["terrain_ground"], valid)["fraction"],
            "median_path_gain_delta_db": round(float(np.median(delta)), 3),
            "p10_delta_db": round(float(np.percentile(delta, 10)), 3),
            "p90_delta_db": round(float(np.percentile(delta, 90)), 3),
            "rms_delta_db": round(float(np.sqrt(np.mean(delta ** 2))), 3),
            "fraction_cells_within_3db": round(float(np.mean(np.abs(delta) <= 3.0)), 4),
            "fraction_cells_over_10db": round(float(np.mean(np.abs(delta) > 10.0)), 4),
            "n_cells_compared": int(valid.sum()),
            "note": ("the pre-registered comparison with the discretisation artifact removed; "
                     "the difference between this row and the unqualified one is the size of "
                     "the artifact"),
        }
    result["pairwise"] = pairs

    # ---- the verdict METHOD asks C3 to reach --------------------------------
    key = "terrain_plane__vs__terrain_ground"
    if key in pairs and "terrain_ground" in variants_out:
        p = pairs[key]
        nf = variants_out["terrain_ground"].get("seed_noise_floor", {}) or {}
        floor = nf.get("best_server_change_fraction_same_variant_different_seed")
        gf_wall = variants_out["terrain_ground"]["wall_s_median"]
        tp_wall = variants_out["terrain_plane"]["wall_s_median"]
        result["verdict"] = {
            "question": ("Does the nine-plane ground-following machinery earn its "
                         "complexity over the single horizontal terrain plane?"),
            "median_path_gain_delta_db": p["median_path_gain_delta_db"],
            "rms_delta_db": p["rms_delta_db"],
            "best_server_change_fraction": p["best_server_change_fraction"],
            "monte_carlo_noise_floor_change_fraction": floor,
            "change_fraction_over_noise_floor": (
                None if floor in (None, 0) else round(p["best_server_change_fraction"] / floor, 2)),
            "cost_multiplier_vs_single_plane": round(gf_wall / max(tp_wall, 1e-9), 2),
            "p10_delta_db": p["p10_delta_db"],
            "p90_delta_db": p["p90_delta_db"],
            "fraction_cells_over_10db": p["fraction_cells_over_10db"],
            "no_coverage_fraction_terrain_plane":
                variants_out["terrain_plane"]["stats_repeat0"]["no_coverage_fraction"],
            "no_coverage_fraction_terrain_ground":
                variants_out["terrain_ground"]["stats_repeat0"]["no_coverage_fraction"],
            "note": ("Stated whichever way the numbers fall. A small delta here is a finding "
                     "against the nine-plane design, and is reported as such. Read the median "
                     "and the tails together: the pre-registered median is the metric most "
                     "likely to hide a terrain effect, because raising or lowering the "
                     "measurement plane moves cells in both directions."),
        }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, indent=2))
    print(f"wrote {OUT_JSON}")

    # ---- figure -------------------------------------------------------------
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        present = [v for v in VARIANTS if v in best_db]
        fig = plt.figure(figsize=(16, 10))
        gs = fig.add_gridspec(2, len(present), height_ratios=[2.0, 1.2], hspace=0.28)
        ext = [cell_centers[..., 0].min(), cell_centers[..., 0].max(),
               cell_centers[..., 1].min(), cell_centers[..., 1].max()]
        allv = np.concatenate([best_db[v][np.isfinite(best_db[v])] for v in present])
        vmax = float(np.percentile(allv, 99)); vmin = vmax - 80

        for i, v in enumerate(present):
            ax = fig.add_subplot(gs[0, i])
            im = ax.imshow(best_db[v], origin="lower", extent=ext, cmap="viridis",
                           vmin=vmin, vmax=vmax, interpolation="nearest")
            for b in buildings_xy:
                ax.plot(b[:, 0], b[:, 1], color="white", lw=0.15, alpha=0.25)
            for t in towers:
                ax.scatter([t["x"]], [t["y"]], c="red", s=55, marker="^",
                           edgecolors="white", zorder=5)
            s = variants_out[v]["stats_repeat0"]
            ax.set_title(f"{v}\nmedian {s['median_db']:.1f} dB   "
                         f"p10 {s['p10_db']:.1f} / p90 {s['p90_db']:.1f} dB", fontsize=10)
            ax.set_aspect("equal"); ax.set_xlabel("x [m]")
            if i == 0:
                ax.set_ylabel("y [m]")
            fig.colorbar(im, ax=ax, shrink=0.75, pad=0.02, label="path gain [dB]")

        ax = fig.add_subplot(gs[1, 0])
        for v in present:
            d = best_db[v][np.isfinite(best_db[v])]
            ax.plot(np.sort(d), np.linspace(0, 1, d.size), lw=2, label=v)
        ax.set_xlabel("best-server path gain [dB]"); ax.set_ylabel("CDF")
        ax.grid(alpha=0.3); ax.legend(fontsize=8); ax.set_title("CDF per variant", fontsize=10)

        if len(present) > 1:
            ax = fig.add_subplot(gs[1, 1])
            labels, vals = [], []
            for k, p in pairs.items():
                labels.append(k.replace("__vs__", "\nvs "))
                vals.append(p["best_server_change_fraction"])
            ax.bar(range(len(vals)), vals, color="#d62728", alpha=0.8)
            floors = [variants_out[v].get("seed_noise_floor", {}).get(
                "best_server_change_fraction_same_variant_different_seed")
                for v in present]
            floors = [f for f in floors if f is not None]
            if floors:
                ax.axhline(max(floors), color="black", ls="--", lw=1.5,
                           label=f"MC noise floor {max(floors):.3f}")
                ax.legend(fontsize=8)
            ax.set_xticks(range(len(vals)))
            ax.set_xticklabels(labels, fontsize=7)
            ax.set_ylabel("best-server change fraction")
            ax.set_title("Best-server churn vs Monte-Carlo noise floor", fontsize=10)
            ax.grid(alpha=0.3, axis="y")

        if len(present) > 2 and "terrain_plane" in best_db and "terrain_ground" in best_db:
            ax = fig.add_subplot(gs[1, 2])
            delta = best_db["terrain_ground"] - best_db["terrain_plane"]
            im = ax.imshow(delta, origin="lower", extent=ext, cmap="coolwarm",
                           vmin=-20, vmax=20, interpolation="nearest")
            ax.set_aspect("equal")
            ax.set_title("terrain_ground - terrain_plane [dB]", fontsize=10)
            fig.colorbar(im, ax=ax, shrink=0.8, pad=0.02)

        fig.suptitle("C3 — flat vs terrain-plane vs ground-following, Newton (Barbados) "
                     f"@ 3.5 GHz, {CELL_M:g} m cells, common grid", fontsize=12)
        OUT_FIG.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(OUT_FIG, dpi=120, bbox_inches="tight")
        print(f"wrote {OUT_FIG}")
    except Exception as exc:                                     # METHOD rule 5
        failures.append({"cell": "figure", "error": repr(exc),
                         "traceback": traceback.format_exc(limit=3)})
        OUT_JSON.write_text(json.dumps(result, indent=2))

    print("\n--- C3 summary ---")
    for v in VARIANTS:
        o = variants_out.get(v, {})
        if o.get("status") != "ok":
            print(f"{v:>14}  FAILED"); continue
        s = o["stats_repeat0"]
        print(f"{v:>14}  median {s['median_db']:8.2f} dB  p10 {s['p10_db']:8.2f}  "
              f"p90 {s['p90_db']:8.2f}  nocov {s['no_coverage_fraction']:.3f}  "
              f"wall {o['wall_s_median']}s")
    for k, p in pairs.items():
        print(f"{k:>44}  best-server change {p['best_server_change_fraction']:.4f}  "
              f"median delta {p['median_path_gain_delta_db']:+.2f} dB  "
              f"rms {p['rms_delta_db']:.2f} dB")
    print(f"failures: {len(failures)}")
    for f in failures:
        print("  FAIL", f)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
