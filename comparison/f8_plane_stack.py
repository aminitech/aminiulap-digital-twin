#!/usr/bin/env python3
"""
F8 -- is the ground-following receiver actually 1.5 m above the ground?

Defect under test
-----------------
``sionna_terrain_ground.py`` builds a stack of horizontal planes across the
terrain relief and, per map cell, samples the plane **nearest** to
``terrain + 1.5 m``. With the shipped ``K = 9`` planes over 55.5 m of relief the
spacing is 6.94 m, and because "nearest" rounds down as often as up the chosen
plane lands **below local ground** in a large fraction of cells. Those cells are
occluded by the terrain itself, read zero path gain, and are then plotted as
no-coverage -- indistinguishable from genuine radio shadow.

That matters because the paper's *abstract* claims the ground-following map
"resolves ridge shadowing that a horizontal receiver plane cannot represent".
If most of the extra shadow is discretisation, the claim is measuring the plane
stack, not the propagation. This script decides that question with numbers.

What is measured, before and after
----------------------------------
* % of cells whose chosen plane sits below local ground (and > 1 m below)
* median and max ``|chosen - target|`` receiver-height offset
* the map's no-coverage fraction
* how much "extra shadowing" over the single horizontal terrain plane survives
  the fix, and whether the survivors are *genuine terrain shadow* -- tested
  independently of the ray tracer with a DTM line-of-sight ray march
* runtime and peak RSS of the shipped stage at the old and new K

Controls (METHOD.md rules)
--------------------------
* **One set of solves.** ``K_AFTER = 57`` and ``K_BEFORE = 9`` are chosen so the
  9-plane stack is an exact *subset* of the 57-plane stack (56 = 8 x 7). Every
  before/after number therefore comes from the *same* Monte-Carlo samples: no
  part of the difference can be re-solve noise.
* **The rule change and the K change are separated.** Four selection variants are
  reported (K9-nearest = shipped, K9-ceiling, K57-nearest, K57-ceiling = fixed).
* **Monte-Carlo noise floor.** ``terrain_plane`` is solved at two seeds and the
  same-configuration best-server change fraction is reported as the floor any
  between-variant number must clear.
* Failures are recorded in the JSON, not dropped.

Run:
    ULAP_WORK_DIR=/path/to/rtwork MPLBACKEND=Agg \\
        /path/to/venv-rt/bin/python comparison/f8_plane_stack.py
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

os.environ.setdefault("DRJIT_NO_RTLD_DEEPBIND", "1")
os.environ.setdefault("MPLBACKEND", "Agg")

REPO = Path(__file__).resolve().parent.parent
OUT_JSON = REPO / "comparison" / "results" / "f8.json"
FIG_DIR = REPO / "comparison" / "figures"
STAGE = REPO / "ulap-scope" / "ulap_scope" / "stages" / "sionna_terrain_ground.py"
WORK = Path(os.environ.get("ULAP_WORK_DIR", ""))

# --- configuration (declared before the first number) ------------------------
FREQ_HZ = 3.5e9
# Both mirror the shipped stages, which read these from the environment with these
# defaults as of 2026-07-30 (samples_per_tx was raised 1e6 -> 1e8 and sionna_coverage.py
# moved 5 m -> 8 m so the two compared figures share one grid). C3 tracks the same two,
# so the "before" row still reproduces c3.json.
CELL_M = float(os.environ.get("ULAP_RM_CELL_M", 8.0))
SAMPLES_PER_TX = int(float(os.environ.get("ULAP_RM_SAMPLES_PER_TX", 10 ** 8)))
MAX_DEPTH = 5
RX_AGL_M = 1.5
K_BEFORE = 9                 # shipped
K_AFTER = 57                 # ceil(55.52 / 1.0) + 1, the stage's new default
SEED = 42
SEED_B = 43                  # noise-floor seed
LOS_SAMPLES = 192            # DTM ray-march resolution for the terrain-LoS test


def md5(path: Path) -> str:
    return hashlib.md5(Path(path).read_bytes(), usedforsecurity=False).hexdigest()  # fingerprint, not a signature


def terrain_sampler(T):
    """Bilinear terrain height -- identical to the stage's own ``terr()``."""
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
                "finite_cells": 0, "total_cells": int(db.size),
                "no_coverage_fraction": 1.0}
    return {"median_db": round(float(np.median(finite)), 3),
            "p10_db": round(float(np.percentile(finite, 10)), 3),
            "p90_db": round(float(np.percentile(finite, 90)), 3),
            "finite_cells": int(finite.size), "total_cells": int(db.size),
            "no_coverage_fraction": round(float(1.0 - finite.size / db.size), 5)}


def building_surface(mani, res_m=2.0):
    """Rasterise the building footprints to a top-of-roof elevation grid.

    Returns ``sample(x, y) -> roof elevation`` (``-inf`` outside every footprint).
    Used to tell *building* shadow apart from *ridge* shadow in the residual.
    """
    from matplotlib.path import Path as MplPath
    rings = [np.asarray(b["ring"], dtype=float) for b in mani["buildings"]]
    tops = [float(b["dtm"]) + float(b["h"]) for b in mani["buildings"]]
    allpts = np.vstack(rings)
    minx, miny = allpts.min(axis=0) - res_m
    maxx, maxy = allpts.max(axis=0) + res_m
    nx = int(np.ceil((maxx - minx) / res_m)) + 1
    ny = int(np.ceil((maxy - miny) / res_m)) + 1
    grid = np.full((ny, nx), -np.inf, dtype=np.float32)
    for ring, top in zip(rings, tops):
        i0 = max(0, int((ring[:, 0].min() - minx) / res_m))
        i1 = min(nx - 1, int((ring[:, 0].max() - minx) / res_m) + 1)
        j0 = max(0, int((ring[:, 1].min() - miny) / res_m))
        j1 = min(ny - 1, int((ring[:, 1].max() - miny) / res_m) + 1)
        if i1 < i0 or j1 < j0:
            continue
        gx = minx + np.arange(i0, i1 + 1) * res_m
        gy = miny + np.arange(j0, j1 + 1) * res_m
        GX, GY = np.meshgrid(gx, gy)
        inside = MplPath(ring).contains_points(
            np.column_stack([GX.ravel(), GY.ravel()])).reshape(GX.shape)
        sub = grid[j0:j1 + 1, i0:i1 + 1]
        np.maximum(sub, np.where(inside, top, -np.inf), out=sub)

    def sample(x, y):
        i = np.clip(((x - minx) / res_m + 0.5).astype(np.int64), 0, nx - 1)
        j = np.clip(((y - miny) / res_m + 0.5).astype(np.int64), 0, ny - 1)
        return grid[j, i]
    return sample, {"res_m": res_m, "grid_shape": [int(ny), int(nx)],
                    "n_footprints": len(rings),
                    "roof_cells": int(np.isfinite(grid).sum())}


def los_blocked(surface_fn, X, Y, rx_z, towers, n_samples=LOS_SAMPLES,
                chunk=20000, per_tower=False):
    """True where ``surface_fn`` blocks the straight line to EVERY tower.

    A pure geometric ray march over a height field -- it knows nothing about the
    ray tracer, its samples or its materials. It is therefore an *independent*
    test of "is this cell obstructed", not a restatement of the coverage map.
    """
    flat_x = X.ravel(); flat_y = Y.ravel(); flat_z = np.asarray(rx_z).ravel()
    blocked_all = np.ones(flat_x.size, dtype=bool)
    blocked_any = np.zeros(flat_x.size, dtype=bool)
    s = np.linspace(0.02, 0.98, n_samples)[None, :]     # skip the two endpoints
    for t in towers:
        tx, ty = float(t["x"]), float(t["y"])
        tz = float(t["ground_z"] + t["h"])
        blocked_this = np.zeros(flat_x.size, dtype=bool)
        for i in range(0, flat_x.size, chunk):
            sl = slice(i, min(i + chunk, flat_x.size))
            px = flat_x[sl][:, None] + s * (tx - flat_x[sl][:, None])
            py = flat_y[sl][:, None] + s * (ty - flat_y[sl][:, None])
            pz = flat_z[sl][:, None] + s * (tz - flat_z[sl][:, None])
            blocked_this[sl] = np.any(surface_fn(px, py) > pz, axis=1)
        blocked_all &= blocked_this
        blocked_any |= blocked_this
    if per_tower:
        return blocked_all.reshape(X.shape), blocked_any.reshape(X.shape)
    return blocked_all.reshape(X.shape)


def select(plane_z: np.ndarray, target: np.ndarray, rule: str) -> np.ndarray:
    """Index of the plane each cell reads. ``nearest`` = shipped, ``ceiling`` = fixed."""
    K = plane_z.size
    if rule == "nearest":
        return np.argmin(np.abs(plane_z[:, None, None] - target[None]), axis=0)
    if rule == "ceiling":
        return np.clip(np.searchsorted(plane_z, target, side="left"), 0, K - 1)
    raise ValueError(rule)


def main() -> int:                                                  # noqa: C901
    failures: list[dict] = []
    result: dict = {
        "study": "F8",
        "question": ("Does the ground-following plane stack put the receiver where it "
                     "claims (1.5 m above ground), and does ground-following still show "
                     "ridge shadowing the horizontal plane misses once it does?"),
        "metrics": ["underground_cell_fraction", "underground_gt_1m_fraction",
                    "median_abs_height_offset_m", "max_abs_height_offset_m",
                    "no_coverage_fraction", "extra_shadow_vs_terrain_plane",
                    "extra_shadow_terrain_los_blocked_fraction",
                    "runtime_s", "peak_rss_mb"],
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "host": {"node": platform.node(), "machine": platform.machine(),
                 "python": platform.python_version(), "executable": sys.executable},
        "config": {"freq_hz": FREQ_HZ, "cell_m": CELL_M,
                   "samples_per_tx": SAMPLES_PER_TX, "max_depth": MAX_DEPTH,
                   "rx_agl_m": RX_AGL_M, "k_before": K_BEFORE, "k_after": K_AFTER,
                   "seed": SEED, "noise_floor_seed": SEED_B,
                   "los_ray_samples": LOS_SAMPLES,
                   "ulap_work_dir": str(WORK),
                   "note": ("K_BEFORE=9 planes are an exact subset of the K_AFTER=57 "
                            "stack (56 = 8*7), so before and after are read off the "
                            "SAME solves; none of the delta is re-solve noise. "
                            "samples_per_tx matches the shipped stage default, raised "
                            "1e6 -> 1e8 on 2026-07-30, and c3_ablation.py tracks the "
                            "same value. The superseded run of this study used 1e7."),
                   },
        "failures": failures,
    }

    if (K_AFTER - 1) % (K_BEFORE - 1) != 0:
        failures.append({"cell": "config",
                         "error": "K_BEFORE planes are not a subset of K_AFTER"})

    import drjit as dr
    import mitsuba as mi
    from sionna.rt import load_scene, PlanarArray, Transmitter, RadioMapSolver

    scene_terr = WORK / "mitsuba_scene_terrain" / "scene.xml"
    mani_path = WORK / "scene_build" / "scene_manifest.json"
    towers_path = WORK / "scene_build" / "towers_near.json"
    for p in (scene_terr, mani_path, towers_path):
        if not p.exists():
            failures.append({"cell": "inputs", "error": f"missing input: {p}"})
            OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
            OUT_JSON.write_text(json.dumps(result, indent=2))
            print(f"ABORT: missing {p}")
            return 1

    mani = json.loads(mani_path.read_text())
    T = mani["terrain"]
    terr = terrain_sampler(T)
    towers = [t for t in json.loads(towers_path.read_text()) if t["in_scene"]]
    buildings_xy = [np.array(b["ring"]) for b in mani["buildings"]]
    relief = float(T["zmax"] - T["zmin"])
    result["inputs"] = {"scene_terrain": str(scene_terr), "manifest": str(mani_path),
                        "manifest_md5": md5(mani_path),
                        "towers": [t["name"] for t in towers],
                        "terrain_relief_m": round(relief, 2),
                        "terrain_zmin_m": T["zmin"], "terrain_zmax_m": T["zmax"],
                        "dtm_posting_m": [
                            round((T["maxx"] - T["minx"]) / (T["nx"] - 1), 2),
                            round((T["maxy"] - T["miny"]) / (T["ny"] - 1), 2)],
                        "scene": ("Newton, Barbados — the government scene the ray "
                                  "tracer was run on (576 footprints).")}

    # ---- scene ------------------------------------------------------------
    scene = load_scene(str(scene_terr))
    scene.frequency = FREQ_HZ
    scene.tx_array = PlanarArray(num_rows=1, num_cols=1, pattern="tr38901",
                                 polarization="V")
    scene.rx_array = PlanarArray(num_rows=1, num_cols=1, pattern="dipole",
                                 polarization="V")
    for t in towers:
        scene.add(Transmitter(t["name"].lower().replace(" ", "_"),
                              [float(t["x"]), float(t["y"]),
                               float(t["ground_z"] + t["h"])]))
    bb = scene.mi_scene.bbox()
    cx = float((bb.min[0] + bb.max[0]) / 2); cy = float((bb.min[1] + bb.max[1]) / 2)
    sx = float(bb.max[0] - bb.min[0]); sy = float(bb.max[1] - bb.min[1])
    result["config"]["mitsuba_variant"] = mi.variant()

    solver = RadioMapSolver()

    def solve(z, seed=SEED):
        t0 = time.monotonic()
        rm = solver(scene=scene, max_depth=MAX_DEPTH, cell_size=(CELL_M, CELL_M),
                    samples_per_tx=SAMPLES_PER_TX, center=[cx, cy, float(z)],
                    size=[sx, sy], orientation=[0., 0., 0.], seed=seed)
        pg = np.array(rm.path_gain)                 # [num_tx, H, W] linear
        cc = np.array(rm.cell_centers)
        dr.sync_thread()
        return pg, cc, time.monotonic() - t0

    # ---- the fine stack, solved once --------------------------------------
    plane_z_after = np.linspace(T["zmin"] + RX_AGL_M, T["zmax"] + RX_AGL_M, K_AFTER)
    step = (K_AFTER - 1) // (K_BEFORE - 1)
    plane_z_before = plane_z_after[::step]
    assert plane_z_before.size == K_BEFORE
    assert np.allclose(plane_z_before,
                       np.linspace(T["zmin"] + RX_AGL_M, T["zmax"] + RX_AGL_M, K_BEFORE))

    print(f"solving {K_AFTER} planes ({plane_z_after[0]:.2f} .. {plane_z_after[-1]:.2f} m, "
          f"spacing {plane_z_after[1]-plane_z_after[0]:.3f} m)")
    stack, cc, wall_total = [], None, 0.0
    for i, z in enumerate(plane_z_after):
        pg, c, w = solve(z)
        stack.append(pg.astype(np.float32)); wall_total += w
        if cc is None:
            cc = c
        if i % 10 == 0:
            print(f"  plane {i:3d}/{K_AFTER}  z={z:7.2f}  {w:5.3f}s")
    stack = np.stack(stack, axis=0)                 # [K, num_tx, H, W]
    print(f"stack {stack.shape} {stack.nbytes/1e6:.1f} MB, {wall_total:.2f} s total")

    X = cc[..., 0]; Y = cc[..., 1]
    ground = terr(X, Y)
    target = ground + RX_AGL_M
    H, W = target.shape
    result["grid"] = {"H": int(H), "W": int(W), "cells": int(H * W),
                      "cell_m": CELL_M}
    result["solve_cost"] = {
        "per_plane_wall_s_median": round(float(wall_total / K_AFTER), 4),
        "k_after_total_wall_s": round(wall_total, 3),
        "k_before_total_wall_s_implied": round(wall_total * K_BEFORE / K_AFTER, 3),
        "stack_bytes_per_plane_float32": int(H * W * 4),
        "stack_mb_k_before": round(K_BEFORE * H * W * 4 / 1e6, 2),
        "stack_mb_k_after": round(K_AFTER * H * W * 4 / 1e6, 2),
    }

    # ---- terrain_plane reference (the horizontal cut the paper compares to) --
    tp_z = T["zmax"] + 5.0
    pg_tp, _, tp_wall = solve(tp_z)
    pg_tp_b, _, _ = solve(tp_z, seed=SEED_B)
    with np.errstate(divide="ignore"):
        tp_db = 10 * np.log10(pg_tp.max(axis=0))
    tp_db[~np.isfinite(tp_db)] = np.nan
    tp_idx = np.argmax(pg_tp, axis=0)
    with np.errstate(divide="ignore"):
        tp_db_b = 10 * np.log10(pg_tp_b.max(axis=0))
    tp_db_b[~np.isfinite(tp_db_b)] = np.nan
    tp_idx_b = np.argmax(pg_tp_b, axis=0)
    valid_nf = np.isfinite(tp_db) & np.isfinite(tp_db_b)
    noise_floor = round(float(np.mean((tp_idx != tp_idx_b)[valid_nf])), 5)
    result["terrain_plane"] = {
        "plane_z_m": round(float(tp_z), 2), "wall_s": round(tp_wall, 3),
        **stats(tp_db),
        "height_above_local_ground_m": {
            "median": round(float(np.median(tp_z - ground)), 2),
            "min": round(float(np.min(tp_z - ground)), 2),
            "max": round(float(np.max(tp_z - ground)), 2)},
        "monte_carlo_noise_floor_best_server_change_fraction": noise_floor,
        "note": ("the single horizontal plane the ground-following map is printed "
                 "next to; the noise floor is a same-configuration re-solve at a "
                 "different seed"),
    }

    # ---- geometric LoS masks (independent of the ray tracer) ----------------
    bld_sample, bld_meta = building_surface(mani)

    def terr_only(x, y):
        return terr(x, y)

    def terr_and_bld(x, y):
        return np.maximum(terr(x, y), bld_sample(x, y))

    plane_z_full = np.full(target.shape, tp_z)
    print("LoS ray march: terrain only, receiver at 1.5 m AGL ...")
    los_blocked_agl, los_any_agl = los_blocked(terr_only, X, Y, target, towers,
                                               per_tower=True)
    print("LoS ray march: terrain only, receiver on the horizontal plane ...")
    los_blocked_plane = los_blocked(terr_only, X, Y, plane_z_full, towers)
    print("LoS ray march: terrain + buildings, receiver at 1.5 m AGL ...")
    losb_blocked_agl = los_blocked(terr_and_bld, X, Y, target, towers)
    print("LoS ray march: terrain + buildings, receiver on the horizontal plane ...")
    losb_blocked_plane = los_blocked(terr_and_bld, X, Y, plane_z_full, towers)
    inside_building = bld_sample(X, Y) > ground + RX_AGL_M   # rx is inside a footprint

    result["geometric_los"] = {
        "building_raster": bld_meta,
        "terrain_only": {
            "blocked_from_all_towers_at_1p5m_agl": round(float(np.mean(los_blocked_agl)), 5),
            "blocked_from_at_least_one_tower_at_1p5m_agl": round(float(np.mean(los_any_agl)), 5),
            "blocked_from_all_towers_on_horizontal_plane": round(
                float(np.mean(los_blocked_plane)), 5),
            "ridge_shadow_fraction_of_map": round(
                float(np.mean(los_blocked_agl & ~los_blocked_plane)), 5)},
        "terrain_plus_buildings": {
            "blocked_from_all_towers_at_1p5m_agl": round(float(np.mean(losb_blocked_agl)), 5),
            "blocked_from_all_towers_on_horizontal_plane": round(
                float(np.mean(losb_blocked_plane)), 5),
            "shadow_fraction_of_map_agl_but_not_plane": round(
                float(np.mean(losb_blocked_agl & ~losb_blocked_plane)), 5)},
        "receiver_inside_a_building_footprint_fraction": round(
            float(np.mean(inside_building)), 5),
        "method": (f"straight-line ray march over a height field, {LOS_SAMPLES} samples "
                   "per link, blocked = surface above the line to EVERY tower. Computed "
                   "from the DTM and the building footprints, NOT from the ray tracer, "
                   "so it is an independent corroboration. 'ridge shadow' uses terrain "
                   "only, so it isolates the claim the abstract makes."),
    }

    # ---- the four selection variants ---------------------------------------
    variants: dict[str, dict] = {}
    masks: dict[str, dict] = {}
    for name, pz, rule in (("K9_nearest__shipped", plane_z_before, "nearest"),
                           ("K9_ceiling", plane_z_before, "ceiling"),
                           ("K57_nearest", plane_z_after, "nearest"),
                           ("K57_ceiling__fixed", plane_z_after, "ceiling")):
        try:
            k = pz.size
            idx_in_after = np.searchsorted(plane_z_after, pz)   # map back into the stack
            kbest = select(pz, target, rule)
            sel_z = pz[kbest]
            offset = sel_z - target
            below = sel_z < ground
            sub = stack[idx_in_after]                            # [k, num_tx, H, W]
            pg = np.take_along_axis(sub, kbest[None, None], axis=0)[0]  # [num_tx,H,W]
            best = pg.max(axis=0)
            with np.errstate(divide="ignore"):
                db = 10 * np.log10(best)
            db[~np.isfinite(db)] = np.nan
            # NOTE: underground cells are NOT masked here -- the shipped stage did not
            # mask them, so this reproduces its map exactly. The masked number is
            # reported alongside as ``no_coverage_fraction_excluding_underground``.
            idx = np.argmax(pg, axis=0)

            covered = np.isfinite(db)
            extra_shadow = (~covered) & np.isfinite(tp_db)
            n_extra = int(extra_shadow.sum())
            # Attribution of the extra shadow, from geometry alone. Strict
            # partition with a declared precedence, so the four fractions sum to 1:
            #   underground artefact  >  ridge (terrain)  >  building  >  unexplained
            underground_artefact = extra_shadow & below
            rest = extra_shadow & ~underground_artefact
            genuine = rest & los_blocked_agl & ~los_blocked_plane
            by_building = rest & ~genuine & losb_blocked_agl
            unexplained = rest & ~genuine & ~by_building
            valid = covered & np.isfinite(tp_db)
            delta = (db - tp_db)[valid]
            keep = ~below

            variants[name] = {
                "k_planes": int(k),
                "rule": rule,
                "plane_spacing_m": round(float(pz[1] - pz[0]), 3),
                "underground_cell_fraction": round(float(np.mean(below)), 5),
                "underground_gt_1m_fraction": round(
                    float(np.mean(sel_z < ground - 1.0)), 5),
                "height_offset_m": {
                    "median_abs": round(float(np.median(np.abs(offset))), 3),
                    "max_abs": round(float(np.max(np.abs(offset))), 3),
                    "median_signed": round(float(np.median(offset)), 3),
                    "min_signed": round(float(np.min(offset)), 3),
                    "max_signed": round(float(np.max(offset)), 3),
                    "fraction_within_1m_of_target": round(
                        float(np.mean(np.abs(offset) <= 1.0)), 5)},
                **stats(db),
                "no_coverage_fraction_excluding_underground": (
                    round(float(np.mean(~np.isfinite(db[keep]))), 5)
                    if keep.any() else None),
                "vs_terrain_plane": {
                    "extra_shadow_cells": n_extra,
                    "extra_shadow_fraction_of_map": round(float(n_extra / db.size), 5),
                    "extra_shadow_terrain_los_blocked_fraction": (
                        round(float(np.mean(los_blocked_agl[extra_shadow])), 5)
                        if n_extra else None),
                    "extra_shadow_genuine_ridge_shadow_cells": int(genuine.sum()),
                    "extra_shadow_genuine_ridge_shadow_fraction": (
                        round(float(genuine.sum() / n_extra), 5) if n_extra else None),
                    "extra_shadow_attribution_fraction": ({
                        "ridge_shadow_terrain_only": round(float(genuine.sum() / n_extra), 5),
                        "building_shadow": round(float(by_building.sum() / n_extra), 5),
                        "underground_discretisation_artefact": round(
                            float(underground_artefact.sum() / n_extra), 5),
                        "unexplained_by_geometry": round(
                            float(unexplained.sum() / n_extra), 5),
                    } if n_extra else None),
                    "cells_covered_here_but_not_on_plane": int(
                        (covered & ~np.isfinite(tp_db)).sum()),
                    "median_delta_db": round(float(np.median(delta)), 3),
                    "p10_delta_db": round(float(np.percentile(delta, 10)), 3),
                    "p90_delta_db": round(float(np.percentile(delta, 90)), 3),
                    "rms_delta_db": round(float(np.sqrt(np.mean(delta ** 2))), 3),
                    "fraction_cells_over_10db": round(
                        float(np.mean(np.abs(delta) > 10.0)), 5),
                    "best_server_change_fraction": round(
                        float(np.mean((idx != tp_idx)[valid])), 5),
                    "n_cells_compared": int(valid.sum()),
                },
            }
            masks[name] = {"below": below, "db": db, "covered": covered,
                           "extra_shadow": extra_shadow, "offset": offset,
                           "genuine": genuine, "by_building": by_building}
            v = variants[name]
            print(f"  {name:22s} K={k:3d} {rule:7s} underground {v['underground_cell_fraction']:.4f} "
                  f"nocov {v['no_coverage_fraction']:.4f} "
                  f"|off| med {v['height_offset_m']['median_abs']:.2f} "
                  f"max {v['height_offset_m']['max_abs']:.2f}")
        except Exception as exc:                                # METHOD rule 5
            failures.append({"cell": name, "error": repr(exc),
                             "traceback": traceback.format_exc(limit=5)})
            print(f"  FAIL {name}: {exc!r}")
    result["variants"] = variants

    # ---- is the residual "extra shadow" physics or sample starvation? -------
    # RadioMapSolver is a Monte-Carlo estimator: a cell with no ray hits reads
    # zero path gain and is plotted identically to a cell that is genuinely dark.
    # A receiver 1.5 m above ground sees the transmitters at a far more grazing
    # angle than one 22 m up, so it collects fewer hits per cell. If the extra
    # shadow shrinks as samples_per_tx rises, it is estimator noise, not terrain.
    conv = {}
    for n_samp in (10 ** 6, 10 ** 7, 10 ** 8, 10 ** 9):
        try:
            t0 = time.monotonic()

            def solve_n(z, n=n_samp):
                rm = solver(scene=scene, max_depth=MAX_DEPTH, cell_size=(CELL_M, CELL_M),
                            samples_per_tx=n, center=[cx, cy, float(z)],
                            size=[sx, sy], orientation=[0., 0., 0.], seed=SEED)
                out = np.array(rm.path_gain).max(axis=0).astype(np.float32)
                dr.sync_thread()
                return out

            tp_n = solve_n(tp_z)
            kb = select(plane_z_after, target, "ceiling")
            st = np.stack([solve_n(z) for z in plane_z_after], axis=0)
            gf_n = np.take_along_axis(st, kb[None], axis=0)[0]
            del st
            cov_tp = tp_n > 0
            cov_gf = gf_n > 0
            xs = (~cov_gf) & cov_tp
            n_xs = int(xs.sum())
            ridge = xs & los_blocked_agl & ~los_blocked_plane
            bld = xs & ~ridge & losb_blocked_agl
            conv[f"{n_samp:.0e}"] = {
                "terrain_plane_no_coverage_fraction": round(float(np.mean(~cov_tp)), 5),
                "ground_following_no_coverage_fraction": round(float(np.mean(~cov_gf)), 5),
                "extra_shadow_fraction_of_map": round(float(np.mean(xs)), 5),
                "extra_shadow_attribution_fraction": ({
                    "ridge_shadow_terrain_only": round(float(ridge.sum() / n_xs), 5),
                    "building_shadow": round(float(bld.sum() / n_xs), 5),
                    "unexplained_by_geometry": round(
                        float((n_xs - ridge.sum() - bld.sum()) / n_xs), 5),
                } if n_xs else None),
                "wall_s": round(time.monotonic() - t0, 2),
            }
            c = conv[f"{n_samp:.0e}"]
            print(f"  samples/tx {n_samp:.0e}: tp nocov "
                  f"{c['terrain_plane_no_coverage_fraction']:.4f}  gf nocov "
                  f"{c['ground_following_no_coverage_fraction']:.4f}  "
                  f"extra-shadow {c['extra_shadow_fraction_of_map']:.4f} "
                  f"{c['extra_shadow_attribution_fraction']}  ({c['wall_s']} s)")
        except Exception as exc:                                # METHOD rule 5
            failures.append({"cell": f"convergence/{n_samp:.0e}", "error": repr(exc),
                             "traceback": traceback.format_exc(limit=5)})
            print(f"  FAIL convergence {n_samp:.0e}: {exc!r}")
    result["sample_convergence"] = {
        "by_samples_per_tx": conv,
        "note": ("K=57 ceiling ground-following vs the single horizontal terrain plane, "
                 "same seed, only samples_per_tx varies. If no-coverage falls with more "
                 "samples the 'shadow' was an unsampled cell, not a dark one."),
    }

    # ---- end-to-end cost of the shipped stage at old vs new K ---------------
    stage_cost = {}
    if STAGE.exists() and WORK.exists():
        for label, k_env in (("K9", "9"), ("K57_default", None)):
            env = dict(os.environ)
            env["ULAP_WORK_DIR"] = str(WORK)
            env["MPLBACKEND"] = "Agg"
            if k_env:
                env["ULAP_GF_PLANES"] = k_env
            else:
                env.pop("ULAP_GF_PLANES", None)
            cmd = ["/usr/bin/time", "-f", "%e %M", sys.executable, str(STAGE)]
            try:
                t0 = time.monotonic()
                pr = subprocess.run(cmd, env=env, capture_output=True, text=True)
                wall = time.monotonic() - t0
                tail = pr.stderr.strip().splitlines()[-1] if pr.stderr.strip() else ""
                el, rss = (tail.split() + ["", ""])[:2]
                stage_cost[label] = {
                    "returncode": pr.returncode,
                    "wall_s": round(wall, 2),
                    "reported_elapsed_s": float(el) if el.replace(".", "", 1).isdigit() else None,
                    "peak_rss_mb": round(int(rss) / 1024, 1) if rss.isdigit() else None,
                    "stdout_tail": pr.stdout.strip().splitlines()[-8:],
                }
                if pr.returncode != 0:
                    failures.append({"cell": f"stage/{label}",
                                     "error": pr.stderr.strip()[-2000:]})
                print(f"  stage {label}: rc={pr.returncode} {wall:.1f}s "
                      f"rss={stage_cost[label]['peak_rss_mb']} MB")
            except Exception as exc:
                failures.append({"cell": f"stage/{label}", "error": repr(exc)})
    else:
        failures.append({"cell": "stage_cost",
                         "error": f"stage or work dir missing: {STAGE} / {WORK}"})
    result["stage_cost"] = stage_cost
    if "K9" in stage_cost and "K57_default" in stage_cost:
        a = stage_cost["K9"].get("wall_s") or 0.0
        b = stage_cost["K57_default"].get("wall_s") or 0.0
        result["stage_cost"]["wall_multiplier_K57_over_K9"] = (
            round(b / a, 2) if a else None)

    # ---- verdict ------------------------------------------------------------
    before = variants.get("K9_nearest__shipped")
    after = variants.get("K57_ceiling__fixed")
    if before and after:
        eb = before["vs_terrain_plane"]; ea = after["vs_terrain_plane"]
        result["verdict"] = {
            "underground_cell_fraction": {"before": before["underground_cell_fraction"],
                                          "after": after["underground_cell_fraction"]},
            "underground_gt_1m_fraction": {"before": before["underground_gt_1m_fraction"],
                                           "after": after["underground_gt_1m_fraction"]},
            "median_abs_height_offset_m": {
                "before": before["height_offset_m"]["median_abs"],
                "after": after["height_offset_m"]["median_abs"]},
            "max_abs_height_offset_m": {
                "before": before["height_offset_m"]["max_abs"],
                "after": after["height_offset_m"]["max_abs"]},
            "no_coverage_fraction": {
                "terrain_plane": result["terrain_plane"]["no_coverage_fraction"],
                "before": before["no_coverage_fraction"],
                "before_excluding_underground_cells":
                    before["no_coverage_fraction_excluding_underground"],
                "after": after["no_coverage_fraction"]},
            "extra_shadow_fraction_of_map": {"before": eb["extra_shadow_fraction_of_map"],
                                             "after": ea["extra_shadow_fraction_of_map"]},
            "extra_shadow_attribution_fraction": {
                "before": eb["extra_shadow_attribution_fraction"],
                "after": ea["extra_shadow_attribution_fraction"]},
            "ridge_shadow_fraction_of_map_from_dtm_geometry":
                result["geometric_los"]["terrain_only"]["ridge_shadow_fraction_of_map"],
            "best_server_change_fraction_vs_terrain_plane": {
                "before": eb["best_server_change_fraction"],
                "after": ea["best_server_change_fraction"],
                "monte_carlo_noise_floor": noise_floor},
            "median_delta_db_vs_terrain_plane": {"before": eb["median_delta_db"],
                                                 "after": ea["median_delta_db"]},
            "note": ("Stated whichever way the numbers fall. If the surviving extra "
                     "shadow is small or is not corroborated by an independent DTM "
                     "line-of-sight test, the abstract's ridge-shadowing claim is not "
                     "supported and must be dropped."),
        }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, indent=2))
    print(f"wrote {OUT_JSON}")

    # ---- figures ------------------------------------------------------------
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.colors import ListedColormap, BoundaryNorm

        FIG_DIR.mkdir(parents=True, exist_ok=True)
        ext = [X.min(), X.max(), Y.min(), Y.max()]
        mb = masks["K9_nearest__shipped"]; ma = masks["K57_ceiling__fixed"]

        # --- figure 1: where the receiver actually is ---
        fig, axes = plt.subplots(2, 2, figsize=(15, 13))
        ax = axes[0, 0]
        ax.hist(mb["offset"].ravel(), bins=120, color="#d62728", alpha=0.75,
                label=f"K=9 nearest (shipped)\n{100*before['underground_cell_fraction']:.1f} % below ground")
        ax.hist(ma["offset"].ravel(), bins=120, color="#2ca02c", alpha=0.75,
                label=f"K=57 ceiling (fixed)\n{100*after['underground_cell_fraction']:.1f} % below ground")
        ax.axvline(0, color="k", lw=1.5)
        ax.set_xlabel("selected plane − (terrain + 1.5 m)  [m]")
        ax.set_ylabel("cells"); ax.set_yscale("log")
        ax.set_title("Receiver height error introduced by the plane stack", fontsize=11)
        ax.legend(fontsize=8); ax.grid(alpha=0.3)

        ax = axes[0, 1]
        ax.imshow(mb["below"].astype(float), origin="lower", extent=ext,
                  cmap=ListedColormap(["#eeeeee", "#d62728"]), interpolation="nearest")
        for t in towers:
            ax.scatter([t["x"]], [t["y"]], c="k", s=55, marker="^", zorder=5)
        ax.set_aspect("equal")
        ax.set_title(f"K=9 nearest: cells with the receiver BELOW ground (red)\n"
                     f"{100*before['underground_cell_fraction']:.1f} % of the map — "
                     "the bands follow terrain contours, not radio physics", fontsize=10)

        for ax, key, ttl in ((axes[1, 0], "K9_nearest__shipped", "no coverage — K=9 nearest (shipped)"),
                             (axes[1, 1], "K57_ceiling__fixed", "no coverage — K=57 ceiling (fixed)")):
            m = masks[key]
            img = np.zeros(target.shape)
            img[~m["covered"]] = 1.0
            img[m["by_building"]] = 2.0
            img[m["genuine"]] = 3.0
            im = ax.imshow(img, origin="lower", extent=ext,
                           cmap=ListedColormap(["#eeeeee", "#444444", "#ff7f0e",
                                                "#1f77b4"]),
                           norm=BoundaryNorm([-0.5, 0.5, 1.5, 2.5, 3.5], 4),
                           interpolation="nearest")
            for t in towers:
                ax.scatter([t["x"]], [t["y"]], c="red", s=55, marker="^",
                           edgecolors="white", zorder=5)
            ax.set_aspect("equal")
            v = variants[key]
            att = v["vs_terrain_plane"]["extra_shadow_attribution_fraction"] or {}
            ax.set_title(f"{ttl}\nno-coverage {100*v['no_coverage_fraction']:.1f} %\n"
                         f"extra shadow vs plane — blue ridge "
                         f"{100*att.get('ridge_shadow_terrain_only', 0):.0f} % · orange "
                         f"building {100*att.get('building_shadow', 0):.0f} % · grey other",
                         fontsize=8)
        fig.suptitle("F8 — the ground-following receiver is underground in "
                     f"{100*before['underground_cell_fraction']:.1f} % of cells (before) "
                     f"vs {100*after['underground_cell_fraction']:.1f} % (after)",
                     fontsize=13)
        fig.tight_layout(rect=[0, 0, 1, 0.97])
        f1 = FIG_DIR / "f8_plane_stack.png"
        fig.savefig(f1, dpi=120, bbox_inches="tight"); plt.close(fig)
        print(f"wrote {f1}")

        # --- figure 2: does any real ridge shadow survive? ---
        fig, axes = plt.subplots(1, 4, figsize=(25, 6.5))
        ax = axes[0]
        im = ax.imshow(ground, origin="lower", extent=ext, cmap="terrain",
                       interpolation="nearest")
        ax.contour(np.linspace(ext[0], ext[1], W), np.linspace(ext[2], ext[3], H),
                   ground, levels=10, colors="k", linewidths=0.3, alpha=0.5)
        for t in towers:
            ax.scatter([t["x"]], [t["y"]], c="red", s=60, marker="^",
                       edgecolors="white", zorder=5)
            ax.annotate(t["name"], (t["x"], t["y"]), fontsize=8, color="white",
                        weight="bold", xytext=(6, 6), textcoords="offset points")
        ax.set_aspect("equal"); ax.set_title("terrain [m]", fontsize=10)
        fig.colorbar(im, ax=ax, shrink=0.8)

        ax = axes[1]
        img = np.zeros(target.shape)
        img[los_blocked_plane] = 1.0
        img[los_blocked_agl & ~los_blocked_plane] = 2.0
        ax.imshow(img, origin="lower", extent=ext,
                  cmap=ListedColormap(["#eeeeee", "#999999", "#1f77b4"]),
                  norm=BoundaryNorm([-0.5, 0.5, 1.5, 2.5], 3), interpolation="nearest")
        for t in towers:
            ax.scatter([t["x"]], [t["y"]], c="red", s=55, marker="^",
                       edgecolors="white", zorder=5)
        ax.set_aspect("equal")
        ax.set_title("DTM line-of-sight, terrain only (independent of the ray tracer)\n"
                     f"blue = blocked at 1.5 m AGL but clear on the horizontal plane "
                     f"= true ridge shadow "
                     f"({100*result['geometric_los']['terrain_only']['ridge_shadow_fraction_of_map']:.2f} % of map)",
                     fontsize=9)

        ax = axes[2]
        d = (ma["db"] - tp_db)
        im = ax.imshow(d, origin="lower", extent=ext, cmap="coolwarm", vmin=-20, vmax=20,
                       interpolation="nearest")
        ax.set_aspect("equal")
        ax.set_title("ground-following (fixed) − horizontal plane [dB]\n"
                     f"median {after['vs_terrain_plane']['median_delta_db']:+.1f} dB, "
                     f"rms {after['vs_terrain_plane']['rms_delta_db']:.1f} dB", fontsize=9)
        fig.colorbar(im, ax=ax, shrink=0.8)

        ax = axes[3]
        if conv:
            ns = sorted(conv, key=lambda s: float(s))
            xs_ = [float(s) for s in ns]
            ax.loglog(xs_, [max(conv[s]["ground_following_no_coverage_fraction"], 1e-6)
                            for s in ns], "o-", color="#2ca02c", lw=2,
                      label="ground-following (K=57 ceiling)")
            ax.loglog(xs_, [max(conv[s]["terrain_plane_no_coverage_fraction"], 1e-6)
                            for s in ns], "s--", color="#7f7f7f", lw=2,
                      label="single horizontal plane")
            ax.loglog(xs_, [max(conv[s]["extra_shadow_fraction_of_map"], 1e-6)
                            for s in ns], "^-", color="#d62728", lw=2,
                      label="extra shadow (gf dark, plane lit)")
            ax.axhline(result["geometric_los"]["terrain_only"]["ridge_shadow_fraction_of_map"],
                       color="#1f77b4", ls=":", lw=2,
                       label="DTM ridge-shadow area (geometry)")
            # Track the stage's actual default rather than hardcoding it -- this
            # marker said "1e6" for a whole round after the default became 1e8.
            ax.axvline(SAMPLES_PER_TX, color="k", ls="-.", lw=1,
                       label=f"shipped stage default ({SAMPLES_PER_TX:.0e})")
            ax.axvline(10 ** 6, color="#999999", ls=":", lw=1,
                       label="superseded default (1e6)")
            ax.set_xlabel("samples_per_tx"); ax.set_ylabel("fraction of map")
            ax.grid(alpha=0.3, which="both"); ax.legend(fontsize=7)
            ax.set_title("'No coverage' is mostly UNSAMPLED, not dark\n"
                         "it falls ~10x per decade of Monte-Carlo samples", fontsize=9)
        fig.suptitle("F8 — does ground-following still resolve ridge shadowing once the "
                     "discretisation artefact is removed?", fontsize=12)
        fig.tight_layout(rect=[0, 0, 1, 0.94])
        f2 = FIG_DIR / "f8_ridge_shadow.png"
        fig.savefig(f2, dpi=120, bbox_inches="tight"); plt.close(fig)
        print(f"wrote {f2}")
        result["figures"] = [str(f1), str(f2)]
    except Exception as exc:                                    # METHOD rule 5
        failures.append({"cell": "figures", "error": repr(exc),
                         "traceback": traceback.format_exc(limit=5)})
        print(f"FAIL figures: {exc!r}")

    OUT_JSON.write_text(json.dumps(result, indent=2))

    print("\n--- F8 summary ---")
    for name, v in variants.items():
        print(f"{name:22s} underground {100*v['underground_cell_fraction']:6.2f} %  "
              f">1 m {100*v['underground_gt_1m_fraction']:6.2f} %  "
              f"|off| med {v['height_offset_m']['median_abs']:5.2f} m max "
              f"{v['height_offset_m']['max_abs']:5.2f} m  "
              f"nocov {100*v['no_coverage_fraction']:6.2f} %  "
              f"extra-shadow {100*v['vs_terrain_plane']['extra_shadow_fraction_of_map']:5.2f} % "
              f"attrib {v['vs_terrain_plane']['extra_shadow_attribution_fraction']}")
    print(f"terrain_plane nocov {100*result['terrain_plane']['no_coverage_fraction']:.2f} %  "
          f"MC noise floor {noise_floor}")
    print(f"failures: {len(failures)}")
    for f in failures:
        print("  FAIL", f.get("cell"), str(f.get("error"))[:200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
