#!/usr/bin/env python3
"""
F8 residual probe -- what ARE the 51.5 % "unexplained by geometry" cells?

Context
-------
At the shipped 1e8 samples/tx default, the ground-following (K=57 ceiling) map
shows 1 032 "extra shadow" cells vs the horizontal terrain plane. The DTM +
building-footprint line-of-sight march in ``comparison/f8_plane_stack.py``
attributes 26.4 % to ridge shadow and 22.2 % to building shadow, leaving
51.5 % (531 cells) "unexplained by geometry" -- the S1 criterion miss in
``docs/audits/2026-07-30-sampling-and-resolution.md``. This script classifies
those 531 cells into mechanisms.

Hypotheses (verdicts published either way)
------------------------------------------
* H0 -- estimator starvation: the cell is reachable, 1e8 rays just never hit it.
  Anchors: the same-seed 1e9 solve, an alternate-seed 1e8 solve, and a
  deterministic ``PathSolver`` probe (does a path exist at all?).
* H1 -- grazing / sub-Fresnel clearance: LOS is technically clear but skims the
  surface within one Fresnel radius, so the binary march calls it "explained by
  nothing" while the physics (and the hit statistics) are marginal.
* H2 -- multi-bounce-only reachability: the cell is reachable only via >=1
  reflection; reflected hits are far rarer per launched ray.
* H3 -- test-artefact family: the S1 march itself is wrong about the cell --
  (a) its 192 samples over 2--98 % of the link step over thin obstacles,
  (b) the 2 m footprint raster / bilinear DTM disagree with the triangulated
  meshes the ray tracer actually intersects (receiver under a roof, below the
  terrain mesh, or mesh-LOS-blocked where the raster march said clear).
* H4 -- receiver-plane transition edges: residuals cluster where the ceiling
  rule switches planes.

Method rules honoured
---------------------
* All 531 residual cells are probed (>= 300 required); matched seeded control
  samples of 320 explained-dark and 320 lit cells run through the SAME probes.
* Pass criteria are declared in ``CRITERIA`` below, printed before any solve,
  and written to the JSON verbatim.
* The attribution logic is REUSED from f8_plane_stack (imported read-only);
  reproduction against comparison/results/f8.json is checked cell-for-cell.
* No stage files touched; writes only f8_residual.json / f8_residual_*.png.

Run:
    ULAP_WORK_DIR=... MPLBACKEND=Agg MI_DEFAULT_VARIANT=cuda_ad_mono_polarized \
        venv-rt/bin/python comparison/f8_residual_probe.py
"""
from __future__ import annotations

import json
import os
import platform
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

os.environ.setdefault("DRJIT_NO_RTLD_DEEPBIND", "1")
os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("MI_DEFAULT_VARIANT", "cuda_ad_mono_polarized")

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "comparison"))
import f8_plane_stack as f8  # noqa: E402  -- reused read-only

OUT_JSON = REPO / "comparison" / "results" / "f8_residual.json"
F8_JSON = REPO / "comparison" / "results" / "f8.json"
FIG_DIR = REPO / "comparison" / "figures"
WORK = Path(os.environ.get("ULAP_WORK_DIR", ""))

FREQ_HZ = f8.FREQ_HZ
CELL_M = f8.CELL_M
SAMPLES = f8.SAMPLES_PER_TX          # 1e8, the shipped default under test
MAX_DEPTH = f8.MAX_DEPTH
RX_AGL = f8.RX_AGL_M
K = f8.K_AFTER                       # 57
SEED = f8.SEED                       # 42
SEED_ALT = 202607                    # alternate-seed 1e8 anchor (43 is f8's floor seed)
SAMPLES_HI = 10 ** 9                 # convergence anchor
LAMBDA_M = 299792458.0 / FREQ_HZ
N_CONTROL = 320
RNG_SEED = 20260730
PS_SAMPLES = 10 ** 7                 # PathSolver samples per source
PS_BATCH = 96
FINE_MARCH_N = 1024                  # vs the S1 march's 192
E_HITS_LOW = 10.0                    # "expected direct hits at 1e8" starvation bar

# --- per-hypothesis pass criteria, DECLARED BEFORE ANY MEASUREMENT -----------
CRITERIA = {
    "H0_estimator_starvation": (
        "PASS if >= 60 % of the 531 residual cells are covered at 1e9 samples/tx, "
        "same seed, same K=57 ceiling configuration."),
    "H1_grazing_subfresnel": (
        "PASS if >= 30 % of residual cells are reachable (lit at 1e9, or lit at the "
        "alternate 1e8 seed, or PathSolver finds >= 1 path) AND have best-tower "
        "minimum LOS clearance below 1 Fresnel radius at the pinch point; AND the "
        "residual population's median clearance ratio (clearance / Fresnel radius) "
        "is < 0.5x the lit-control median with Mann-Whitney p < 0.01."),
    "H2_multibounce_only": (
        "PASS if >= 20 % of residual cells have >= 1 valid PathSolver path but zero "
        "line-of-sight paths (reachable only via interactions)."),
    "H3_test_artefact": (
        "PASS if >= 20 % of residual cells are misjudged by the S1 test itself: "
        "blocked to ALL towers by a 1024-sample march where the 192-sample march "
        "said clear, OR receiver under a roof / below the terrain mesh per actual-"
        "mesh upward ray_test, OR mesh-LOS-blocked to all towers per ray_test."),
    "H4_plane_transition": (
        "PASS if the fraction of residual cells lying on a kbest transition "
        "boundary (4-neighbour plane index differs) is >= 2x the lit-control "
        "fraction and the difference exceeds 3 binomial sigma."),
    "classification": (
        "Every residual cell gets exactly one class by declared precedence: "
        "march_undersampled > below_terrain_mesh > under_roof_mesh > "
        "mesh_los_blocked > grazing_subfresnel > reflection_only > "
        "low_hit_expectation (E[direct hits at 1e8] < 10) > plain_starved > "
        "unreachable_depth5 > unknown. The E-family requires reachability "
        "evidence (1e9 / alt-seed / PathSolver)."),
}


def main() -> int:  # noqa: C901
    failures: list[dict] = []
    t_start = time.monotonic()
    result: dict = {
        "study": "F8-residual",
        "question": ("What are the 51.5 % of 1e8 extra-shadow cells that the DTM+"
                     "building LOS march cannot explain (S1 criterion miss)?"),
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "host": {"node": platform.node(), "machine": platform.machine(),
                 "python": platform.python_version(), "executable": sys.executable},
        "config": {"freq_hz": FREQ_HZ, "cell_m": CELL_M, "samples_per_tx": SAMPLES,
                   "samples_per_tx_hi": SAMPLES_HI, "max_depth": MAX_DEPTH,
                   "rx_agl_m": RX_AGL, "k_planes": K, "seed": SEED,
                   "seed_alt": SEED_ALT, "rng_seed": RNG_SEED,
                   "pathsolver_samples_per_src": PS_SAMPLES,
                   "fine_march_samples": FINE_MARCH_N,
                   "s1_march_samples": f8.LOS_SAMPLES,
                   "fresnel_lambda_m": round(LAMBDA_M, 5),
                   "e_hits_low_bar": E_HITS_LOW,
                   "n_control": N_CONTROL,
                   "ulap_work_dir": str(WORK)},
        "criteria_pre_stated": CRITERIA,
        "failures": failures,
    }
    print("=== pre-stated pass criteria ===")
    for k, v in CRITERIA.items():
        print(f"  {k}: {v}")

    import drjit as dr
    import mitsuba as mi
    from sionna.rt import (load_scene, PlanarArray, Transmitter, Receiver,
                           RadioMapSolver, PathSolver)

    mani = json.loads((WORK / "scene_build" / "scene_manifest.json").read_text())
    towers = [t for t in json.loads(
        (WORK / "scene_build" / "towers_near.json").read_text()) if t["in_scene"]]
    T = mani["terrain"]
    terr = f8.terrain_sampler(T)

    scene = load_scene(str(WORK / "mitsuba_scene_terrain" / "scene.xml"))
    scene.frequency = FREQ_HZ
    scene.tx_array = PlanarArray(num_rows=1, num_cols=1, pattern="tr38901",
                                 polarization="V")
    scene.rx_array = PlanarArray(num_rows=1, num_cols=1, pattern="dipole",
                                 polarization="V")
    for t in towers:
        scene.add(Transmitter(t["name"].lower().replace(" ", "_"),
                              [float(t["x"]), float(t["y"]),
                               float(t["ground_z"] + t["h"])]))
    variant = mi.variant()
    result["config"]["mitsuba_variant"] = variant
    if variant != "cuda_ad_mono_polarized":
        print(f"ABORT: mitsuba variant is {variant}, need cuda_ad_mono_polarized")
        failures.append({"cell": "variant", "error": variant})
        OUT_JSON.write_text(json.dumps(result, indent=2))
        return 1

    bb = scene.mi_scene.bbox()
    cx = float((bb.min[0] + bb.max[0]) / 2); cy = float((bb.min[1] + bb.max[1]) / 2)
    sx = float(bb.max[0] - bb.min[0]); sy = float(bb.max[1] - bb.min[1])
    solver = RadioMapSolver()

    def solve_cov(z, seed=SEED, n=SAMPLES):
        """Boolean coverage (max-over-tx path gain > 0) of one plane."""
        rm = solver(scene=scene, max_depth=MAX_DEPTH, cell_size=(CELL_M, CELL_M),
                    samples_per_tx=int(n), center=[cx, cy, float(z)],
                    size=[sx, sy], orientation=[0., 0., 0.], seed=seed)
        pg = np.array(rm.path_gain)
        cc = np.array(rm.cell_centers)
        dr.sync_thread()
        return (pg.max(axis=0) > 0), cc

    # ---- base maps at the shipped default (reproduces f8's masks) ----------
    plane_z = np.linspace(T["zmin"] + RX_AGL, T["zmax"] + RX_AGL, K)
    tp_z = T["zmax"] + 5.0
    print(f"\nsolving base stack: K={K} @ {SAMPLES:.0e}, seed {SEED} ...")
    t0 = time.monotonic()
    cov_stack, cc = None, None
    covs = []
    for z in plane_z:
        cv, c = solve_cov(z)
        covs.append(cv)
        if cc is None:
            cc = c
    cov_stack = np.stack(covs, axis=0)
    cov_tp, _ = solve_cov(tp_z)
    print(f"  base stack: {time.monotonic() - t0:.1f} s")

    X = cc[..., 0]; Y = cc[..., 1]
    ground = terr(X, Y)
    target = ground + RX_AGL
    Hh, Ww = target.shape
    kb = f8.select(plane_z, target, "ceiling")
    sel_z = plane_z[kb]
    cov_gf = np.take_along_axis(cov_stack, kb[None], axis=0)[0]

    # ---- S1 attribution, exactly as f8 does it -----------------------------
    bld_sample, bld_meta = f8.building_surface(mani)

    def terr_only(x, y):
        return terr(x, y)

    def terr_and_bld(x, y):
        return np.maximum(terr(x, y), bld_sample(x, y))

    plane_full = np.full(target.shape, tp_z)
    print("S1 marches (192 samples, 2-98 %), as shipped ...")
    los_blocked_agl = f8.los_blocked(terr_only, X, Y, target, towers)
    los_blocked_plane = f8.los_blocked(terr_only, X, Y, plane_full, towers)
    losb_blocked_agl = f8.los_blocked(terr_and_bld, X, Y, target, towers)

    extra = (~cov_gf) & cov_tp
    genuine = extra & los_blocked_agl & ~los_blocked_plane
    by_bld = extra & ~genuine & losb_blocked_agl
    resid = extra & ~genuine & ~by_bld

    # reproduction check against the published f8.json
    ref = json.loads(F8_JSON.read_text())
    ref_v = ref["variants"]["K57_ceiling__fixed"]["vs_terrain_plane"]
    rep = {
        "extra_shadow_cells": {"ref": ref_v["extra_shadow_cells"],
                               "here": int(extra.sum())},
        "ridge_cells": {"ref": int(round(ref_v["extra_shadow_attribution_fraction"]
                                         ["ridge_shadow_terrain_only"]
                                         * ref_v["extra_shadow_cells"])),
                        "here": int(genuine.sum())},
        "building_cells": {"ref": int(round(ref_v["extra_shadow_attribution_fraction"]
                                            ["building_shadow"]
                                            * ref_v["extra_shadow_cells"])),
                           "here": int(by_bld.sum())},
        "unexplained_cells": {"ref": int(round(ref_v["extra_shadow_attribution_fraction"]
                                               ["unexplained_by_geometry"]
                                               * ref_v["extra_shadow_cells"])),
                              "here": int(resid.sum())},
        "gf_no_coverage_fraction": {
            "ref": ref["variants"]["K57_ceiling__fixed"]["no_coverage_fraction"],
            "here": round(float(np.mean(~cov_gf)), 5)},
        "tp_no_coverage_fraction": {
            "ref": ref["terrain_plane"]["no_coverage_fraction"],
            "here": round(float(np.mean(~cov_tp)), 5)},
    }
    rep["exact"] = all(d["ref"] == d["here"] for d in
                       (rep["extra_shadow_cells"], rep["unexplained_cells"]))
    result["reproduction_vs_f8_json"] = rep
    print(f"reproduction: extra {rep['extra_shadow_cells']}  "
          f"resid {rep['unexplained_cells']}  exact={rep['exact']}")

    n_res = int(resid.sum())

    # ---- convergence / seed anchors ----------------------------------------
    print(f"anchor stack: K={K} @ 1e9, seed {SEED} ...")
    t0 = time.monotonic()
    cov9 = np.stack([solve_cov(z, n=SAMPLES_HI)[0] for z in plane_z], axis=0)
    cov9_gf = np.take_along_axis(cov9, kb[None], axis=0)[0]
    cov9_tp, _ = solve_cov(tp_z, n=SAMPLES_HI)
    del cov9
    print(f"  1e9 stack: {time.monotonic() - t0:.1f} s "
          f"(gf nocov {np.mean(~cov9_gf):.5f}, tp nocov {np.mean(~cov9_tp):.5f})")

    print(f"anchor stack: K={K} @ {SAMPLES:.0e}, alternate seed {SEED_ALT} ...")
    t0 = time.monotonic()
    cova = np.stack([solve_cov(z, seed=SEED_ALT)[0] for z in plane_z], axis=0)
    cova_gf = np.take_along_axis(cova, kb[None], axis=0)[0]
    del cova
    print(f"  alt-seed stack: {time.monotonic() - t0:.1f} s "
          f"(gf nocov {np.mean(~cova_gf):.5f})")

    # ---- populations --------------------------------------------------------
    rng = np.random.default_rng(RNG_SEED)
    flat = lambda m: np.flatnonzero(m.ravel())  # noqa: E731
    idx_res = flat(resid)
    idx_expl = flat(genuine | by_bld)
    idx_lit_all = flat(cov_gf & cov_tp)
    idx_expl_s = rng.choice(idx_expl, size=min(N_CONTROL, idx_expl.size),
                            replace=False)
    idx_lit_s = rng.choice(idx_lit_all, size=N_CONTROL, replace=False)
    pops = {"residual": idx_res, "explained_dark": idx_expl_s, "lit": idx_lit_s}
    result["populations"] = {k: int(v.size) for k, v in pops.items()}
    result["populations"]["explained_dark_total"] = int(idx_expl.size)
    print(f"populations: residual {idx_res.size}, explained-dark sample "
          f"{idx_expl_s.size}/{idx_expl.size}, lit sample {idx_lit_s.size}")

    fx = X.ravel(); fy = Y.ravel(); fg = ground.ravel()
    fsel = sel_z.ravel(); ftgt = target.ravel()

    # ---- per-cell geometry metrics ------------------------------------------
    def march_margin(idx, z_of, n=FINE_MARCH_N):
        """Per tower: min clearance (m) of the line rx->tower over terr+bld,
        the link fraction s* where it pinches, and the Fresnel radius there.
        Full-span sampling (0.001..0.999) -- unlike the S1 march's 2-98 %."""
        s = np.linspace(0.001, 0.999, n)[None, :]
        m = np.empty((len(towers), idx.size))
        sstar = np.empty_like(m)
        fres = np.empty_like(m)
        for ti, t in enumerate(towers):
            tx, ty = float(t["x"]), float(t["y"])
            tz = float(t["ground_z"] + t["h"])
            px = fx[idx][:, None] + s * (tx - fx[idx][:, None])
            py = fy[idx][:, None] + s * (ty - fy[idx][:, None])
            pz = z_of[idx][:, None] + s * (tz - z_of[idx][:, None])
            clear = pz - terr_and_bld(px, py)
            j = np.argmin(clear, axis=1)
            m[ti] = clear[np.arange(idx.size), j]
            sstar[ti] = s[0][j]
            d3 = np.sqrt((tx - fx[idx]) ** 2 + (ty - fy[idx]) ** 2
                         + (tz - z_of[idx]) ** 2)
            d1 = sstar[ti] * d3
            fres[ti] = np.sqrt(LAMBDA_M * d1 * (d3 - d1) / d3)
        return m, sstar, fres

    def coarse_blocked_all(idx, z_of):
        """The S1 march re-run at 1024 samples over the FULL span: does it now
        block the cell to every tower?"""
        m, _, _ = march_margin(idx, z_of)
        return np.all(m <= 0, axis=0)

    def mesh_rays(idx):
        """Actual-mesh tests: upward ray hit, and per-tower LOS occlusion from
        just above the selected receiver plane."""
        n = idx.size
        ox = fx[idx]; oy = fy[idx]; oz = fsel[idx] + 0.02
        up_o = mi.Point3f(ox, oy, oz)
        up_ray = mi.Ray3f(up_o, mi.Vector3f(np.zeros(n), np.zeros(n),
                                            np.ones(n)))
        up_ray.maxt = mi.Float(np.full(n, 500.0))
        up_hit = np.array(scene.mi_scene.ray_test(up_ray))
        blocked = np.zeros((len(towers), n), dtype=bool)
        for ti, t in enumerate(towers):
            dx = float(t["x"]) - ox; dy = float(t["y"]) - oy
            dz = float(t["ground_z"] + t["h"]) - oz
            dist = np.sqrt(dx * dx + dy * dy + dz * dz)
            ray = mi.Ray3f(mi.Point3f(ox, oy, oz),
                           mi.Vector3f(dx / dist, dy / dist, dz / dist))
            ray.maxt = mi.Float(dist - 0.5)
            blocked[ti] = np.array(scene.mi_scene.ray_test(ray))
        return up_hit, blocked

    def inside_footprint(idx):
        from matplotlib.path import Path as MplPath
        pts = np.column_stack([fx[idx], fy[idx]])
        inside = np.zeros(idx.size, dtype=bool)
        for b in mani["buildings"]:
            ring = np.asarray(b["ring"], dtype=float)
            lo = ring.min(axis=0); hi = ring.max(axis=0)
            cand = ((pts[:, 0] >= lo[0]) & (pts[:, 0] <= hi[0])
                    & (pts[:, 1] >= lo[1]) & (pts[:, 1] <= hi[1]) & ~inside)
            if cand.any():
                inside[cand] = MplPath(ring).contains_points(pts[cand])
        return inside

    def edge_distance(idx):
        """Distance from cell centre to the nearest building-footprint edge."""
        pts = np.column_stack([fx[idx], fy[idx]])
        best = np.full(idx.size, np.inf)
        for b in mani["buildings"]:
            ring = np.asarray(b["ring"], dtype=float)
            a = ring; bq = np.roll(ring, -1, axis=0)
            ab = bq - a
            ab2 = (ab ** 2).sum(axis=1)
            ab2[ab2 == 0] = 1e-12
            # broadcast cells x segments
            ap = pts[:, None, :] - a[None]
            tt = np.clip((ap * ab[None]).sum(axis=2) / ab2[None], 0, 1)
            proj = a[None] + tt[..., None] * ab[None]
            dd = np.sqrt(((pts[:, None, :] - proj) ** 2).sum(axis=2)).min(axis=1)
            best = np.minimum(best, dd)
        return best

    # kbest transition boundary
    trans = np.zeros_like(kb, dtype=bool)
    trans[:-1] |= kb[:-1] != kb[1:]
    trans[1:] |= kb[1:] != kb[:-1]
    trans[:, :-1] |= kb[:, :-1] != kb[:, 1:]
    trans[:, 1:] |= kb[:, 1:] != kb[:, :-1]
    ftrans = trans.ravel()

    # intra-cell burial: selected plane below the bilinear ground at any cell corner
    hx = CELL_M / 2.0
    corner_max = np.maximum.reduce([terr(X + sxn * hx, Y + syn * hx)
                                    for sxn in (-1, 1) for syn in (-1, 1)])
    fburial = (sel_z - corner_max).ravel()          # <0 => partly buried plane

    metrics: dict[str, dict] = {}
    print("geometry probes per population ...")
    for name, idx in pops.items():
        t0 = time.monotonic()
        m_sel, sstar, fres = march_margin(idx, fsel)          # at the RT rx height
        best_t = np.argmax(m_sel, axis=0)
        ar = np.arange(idx.size)
        margin = m_sel[best_t, ar]
        fresnel = fres[best_t, ar]
        ratio = margin / fresnel
        coarse_blk = coarse_blocked_all(idx, ftgt)            # S1 height, fine march
        up_hit, mesh_blk = mesh_rays(idx)
        mesh_blk_all = np.all(mesh_blk, axis=0)
        in_fp = inside_footprint(idx)
        edist = edge_distance(idx)
        # expected direct hits at 1e8 through the best-margin tower
        tarr = towers[0]
        txs = np.array([[t["x"], t["y"], t["ground_z"] + t["h"]] for t in towers])
        dx = txs[best_t, 0] - fx[idx]; dy = txs[best_t, 1] - fy[idx]
        dz = txs[best_t, 2] - fsel[idx]
        dh = np.sqrt(dx * dx + dy * dy)
        d3 = np.sqrt(dh * dh + dz * dz)
        elev = np.arctan2(np.abs(dz), dh)
        e_hits = SAMPLES * (CELL_M ** 2) * np.sin(elev) / (4 * np.pi * d3 ** 2)
        lit9 = cov9_gf.ravel()[idx]
        lita = cova_gf.ravel()[idx]
        metrics[name] = {
            "idx": idx, "margin_m": margin, "fresnel_m": fresnel, "ratio": ratio,
            "sstar": sstar[best_t, ar], "coarse_blocked_all": coarse_blk,
            "up_hit": up_hit, "mesh_blocked_all": mesh_blk_all,
            "mesh_blocked_per_tower": mesh_blk, "inside_fp": in_fp,
            "edge_dist_m": edist, "elev_rad": elev, "dist_m": d3,
            "e_hits": e_hits, "lit_1e9": lit9, "lit_altseed": lita,
            "on_transition": ftrans[idx], "burial_m": fburial[idx],
        }
        print(f"  {name:15s} n={idx.size:4d}  {time.monotonic() - t0:.1f} s  "
              f"median margin {np.median(margin):+.2f} m  "
              f"median ratio {np.median(ratio):+.2f}  "
              f"lit@1e9 {np.mean(lit9):.3f}")

    # ---- PathSolver probe ----------------------------------------------------
    print("PathSolver probes ...")
    ps = PathSolver()

    def pathsolver_probe(idx):
        n_paths = np.zeros(idx.size, dtype=int)
        n_los = np.zeros(idx.size, dtype=int)
        gain_db = np.full(idx.size, -np.inf)
        for i0 in range(0, idx.size, PS_BATCH):
            sl = slice(i0, min(i0 + PS_BATCH, idx.size))
            ids = idx[sl]
            names = []
            for j, cid in enumerate(ids):
                nm = f"probe_{i0 + j}"
                scene.add(Receiver(nm, [float(fx[cid]), float(fy[cid]),
                                        float(fsel[cid] + 0.02)]))
                names.append(nm)
            try:
                paths = ps(scene=scene, max_depth=MAX_DEPTH,
                           samples_per_src=PS_SAMPLES, seed=7)
                valid = np.asarray(paths.valid)                # [rx, tx, p]
                if valid.size:
                    inter = np.asarray(paths.interactions)     # [d, rx, tx, p]
                    is_los = np.all(inter == 0, axis=0) & valid
                    n_paths[sl] = valid.sum(axis=(1, 2))
                    n_los[sl] = is_los.sum(axis=(1, 2))
                    a_re, a_im = paths.a
                    a_re = np.asarray(a_re); a_im = np.asarray(a_im)
                    p = (a_re ** 2 + a_im ** 2).reshape(valid.shape[0], -1)
                    g = p.sum(axis=1)
                    with np.errstate(divide="ignore"):
                        gain_db[sl] = 10 * np.log10(g)
            except Exception as exc:                            # METHOD rule 5
                failures.append({"cell": f"pathsolver/{i0}", "error": repr(exc),
                                 "traceback": traceback.format_exc(limit=5)})
                print(f"  FAIL pathsolver batch {i0}: {exc!r}")
            finally:
                for nm in names:
                    scene.remove(nm)
        return n_paths, n_los, gain_db

    for name, idx in pops.items():
        t0 = time.monotonic()
        n_paths, n_los, gain_db = pathsolver_probe(idx)
        metrics[name]["ps_n_paths"] = n_paths
        metrics[name]["ps_n_los"] = n_los
        metrics[name]["ps_gain_db"] = gain_db
        print(f"  {name:15s} paths>0: {np.mean(n_paths > 0):.3f}  "
              f"LoS>0: {np.mean(n_los > 0):.3f}  "
              f"reflection-only: {np.mean((n_paths > 0) & (n_los == 0)):.3f}  "
              f"({time.monotonic() - t0:.1f} s)")

    # ---- classification cascade (residual population) ------------------------
    r = metrics["residual"]
    reachable = r["lit_1e9"] | r["lit_altseed"] | (r["ps_n_paths"] > 0)
    cls = np.full(n_res, "unknown", dtype=object)

    def assign(mask, label):
        m = mask & (cls == "unknown")
        cls[m] = label
        return int(m.sum())

    order = [
        ("march_undersampled", r["coarse_blocked_all"]),
        ("below_terrain_mesh", r["up_hit"] & ~r["inside_fp"]),
        ("under_roof_mesh", r["up_hit"] & r["inside_fp"]),
        ("mesh_los_blocked", r["mesh_blocked_all"]),
        ("grazing_subfresnel", reachable & (r["ratio"] < 1.0)),
        ("reflection_only", reachable & (r["ps_n_paths"] > 0) & (r["ps_n_los"] == 0)),
        ("low_hit_expectation", reachable & (r["e_hits"] < E_HITS_LOW)),
        ("plain_starved", reachable),
        ("unreachable_depth5", (~reachable) & (r["ps_n_paths"] == 0)),
    ]
    breakdown = {}
    for label, mask in order:
        breakdown[label] = assign(np.asarray(mask, dtype=bool), label)
    breakdown["unknown"] = int((cls == "unknown").sum())
    result["class_breakdown_of_residual"] = {
        "counts": breakdown,
        "fractions_of_residual": {k: round(v / n_res, 5)
                                  for k, v in breakdown.items()},
        "fractions_of_extra_shadow": {k: round(v / int(extra.sum()), 5)
                                      for k, v in breakdown.items()},
        "precedence": [label for label, _ in order] + ["unknown"],
    }
    print("\nclass breakdown of the residual "
          f"({n_res} cells = {100 * n_res / extra.sum():.1f} % of extra shadow):")
    for k2, v2 in breakdown.items():
        print(f"  {k2:22s} {v2:4d}  ({100 * v2 / n_res:.1f} %)")

    # secondary (non-exclusive) facts about the residual
    result["residual_facts"] = {
        "lit_at_1e9_same_seed": round(float(np.mean(r["lit_1e9"])), 5),
        "lit_at_1e8_alt_seed": round(float(np.mean(r["lit_altseed"])), 5),
        "pathsolver_reachable": round(float(np.mean(r["ps_n_paths"] > 0)), 5),
        "reachable_any_anchor": round(float(np.mean(reachable)), 5),
        "subfresnel_clearance": round(float(np.mean(r["ratio"] < 1.0)), 5),
        "negative_margin_some_tower_all": round(
            float(np.mean(r["margin_m"] <= 0)), 5),
        "e_hits_below_10": round(float(np.mean(r["e_hits"] < E_HITS_LOW)), 5),
        "on_kbest_transition": round(float(np.mean(r["on_transition"])), 5),
        "plane_buried_in_cell": round(float(np.mean(r["burial_m"] < 0)), 5),
        "within_16m_of_footprint_edge": round(
            float(np.mean(r["edge_dist_m"] < 16.0)), 5),
        "median_elevation_deg": round(float(np.degrees(
            np.median(r["elev_rad"]))), 3),
        "median_e_hits": round(float(np.median(r["e_hits"])), 2),
        "median_ps_gain_db_where_reachable": (
            round(float(np.median(r["ps_gain_db"][r["ps_n_paths"] > 0])), 2)
            if (r["ps_n_paths"] > 0).any() else None),
    }

    # ---- population comparison + hypothesis verdicts --------------------------
    from scipy import stats as sst

    def pop_summary(m):
        return {
            "median_margin_m": round(float(np.median(m["margin_m"])), 3),
            "median_fresnel_ratio": round(float(np.median(m["ratio"])), 3),
            "median_e_hits": round(float(np.median(m["e_hits"])), 2),
            "median_elev_deg": round(float(np.degrees(np.median(m["elev_rad"]))), 3),
            "median_edge_dist_m": round(float(np.median(m["edge_dist_m"])), 2),
            "frac_on_transition": round(float(np.mean(m["on_transition"])), 5),
            "frac_subfresnel": round(float(np.mean(m["ratio"] < 1.0)), 5),
            "frac_lit_1e9": round(float(np.mean(m["lit_1e9"])), 5),
            "frac_ps_reachable": round(float(np.mean(m["ps_n_paths"] > 0)), 5),
            "frac_reflection_only": round(
                float(np.mean((m["ps_n_paths"] > 0) & (m["ps_n_los"] == 0))), 5),
            "frac_mesh_blocked_all": round(float(np.mean(m["mesh_blocked_all"])), 5),
            "frac_up_hit": round(float(np.mean(m["up_hit"])), 5),
        }

    result["population_summary"] = {k: pop_summary(v) for k, v in metrics.items()}

    lit = metrics["lit"]
    mwu = sst.mannwhitneyu(r["ratio"], lit["ratio"], alternative="less")
    ks = sst.ks_2samp(r["ratio"], lit["ratio"])
    result["stats"] = {
        "mannwhitney_ratio_residual_lt_lit": {"U": float(mwu.statistic),
                                              "p": float(mwu.pvalue)},
        "ks_ratio_residual_vs_lit": {"D": float(ks.statistic),
                                     "p": float(ks.pvalue)},
    }

    # H verdicts against the pre-stated criteria
    h0_frac = float(np.mean(r["lit_1e9"]))
    h1_frac = float(np.mean(reachable & (r["ratio"] < 1.0)))
    med_ratio_res = float(np.median(r["ratio"]))
    med_ratio_lit = float(np.median(lit["ratio"]))
    h1_pass = (h1_frac >= 0.30 and med_ratio_res < 0.5 * med_ratio_lit
               and mwu.pvalue < 0.01)
    h2_frac = float(np.mean((r["ps_n_paths"] > 0) & (r["ps_n_los"] == 0)))
    h3_mask = (r["coarse_blocked_all"] | r["up_hit"] | r["mesh_blocked_all"])
    h3_frac = float(np.mean(h3_mask))
    tr_res = float(np.mean(r["on_transition"]))
    tr_lit = float(np.mean(lit["on_transition"]))
    sig = np.sqrt(tr_lit * (1 - tr_lit) / n_res + tr_lit * (1 - tr_lit)
                  / lit["idx"].size) or 1e-9
    h4_pass = (tr_res >= 2 * tr_lit) and ((tr_res - tr_lit) > 3 * sig)
    result["hypothesis_verdicts"] = {
        "H0_estimator_starvation": {
            "measured_frac_lit_1e9": round(h0_frac, 5),
            "bar": 0.60, "verdict": "PASS" if h0_frac >= 0.60 else "FAIL"},
        "H1_grazing_subfresnel": {
            "measured_frac_reachable_and_subfresnel": round(h1_frac, 5),
            "median_ratio_residual": round(med_ratio_res, 3),
            "median_ratio_lit": round(med_ratio_lit, 3),
            "mannwhitney_p": float(mwu.pvalue),
            "verdict": "PASS" if h1_pass else "FAIL"},
        "H2_multibounce_only": {
            "measured_frac_reflection_only": round(h2_frac, 5),
            "bar": 0.20, "verdict": "PASS" if h2_frac >= 0.20 else "FAIL"},
        "H3_test_artefact": {
            "measured_frac": round(h3_frac, 5),
            "components": {
                "march_undersampled_fine_blocked": round(
                    float(np.mean(r["coarse_blocked_all"])), 5),
                "mesh_up_hit": round(float(np.mean(r["up_hit"])), 5),
                "mesh_los_blocked_all": round(
                    float(np.mean(r["mesh_blocked_all"])), 5)},
            "bar": 0.20, "verdict": "PASS" if h3_frac >= 0.20 else "FAIL"},
        "H4_plane_transition": {
            "frac_on_transition_residual": round(tr_res, 5),
            "frac_on_transition_lit": round(tr_lit, 5),
            "verdict": "PASS" if h4_pass else "FAIL"},
    }
    print("\nhypothesis verdicts:")
    for k2, v2 in result["hypothesis_verdicts"].items():
        print(f"  {k2}: {v2['verdict']}  {json.dumps({a: b for a, b in v2.items() if a != 'verdict'})[:160]}")

    result["wall_s"] = round(time.monotonic() - t_start, 1)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, indent=2))
    print(f"wrote {OUT_JSON}")

    # ---- figures ---------------------------------------------------------------
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.colors import ListedColormap, BoundaryNorm

        FIG_DIR.mkdir(parents=True, exist_ok=True)
        ext = [X.min(), X.max(), Y.min(), Y.max()]

        # --- figure 1: where the residual is and what it is ---
        cls_order = [label for label, _ in order] + ["unknown"]
        palette = {"march_undersampled": "#8c564b", "below_terrain_mesh": "#e377c2",
                   "under_roof_mesh": "#9467bd", "mesh_los_blocked": "#7f7f7f",
                   "grazing_subfresnel": "#d62728", "reflection_only": "#ff7f0e",
                   "low_hit_expectation": "#bcbd22", "plain_starved": "#2ca02c",
                   "unreachable_depth5": "#17becf", "unknown": "#000000"}
        fig, axes = plt.subplots(1, 2, figsize=(17, 7))
        ax = axes[0]
        img = np.zeros(target.shape)
        img[genuine] = 1.0
        img[by_bld] = 2.0
        img[resid] = 3.0
        ax.imshow(img, origin="lower", extent=ext,
                  cmap=ListedColormap(["#f2f2f2", "#1f77b4", "#ff7f0e", "#d62728"]),
                  norm=BoundaryNorm([-.5, .5, 1.5, 2.5, 3.5], 4),
                  interpolation="nearest")
        ax.contour(np.linspace(ext[0], ext[1], Ww), np.linspace(ext[2], ext[3], Hh),
                   ground, levels=10, colors="k", linewidths=0.3, alpha=0.4)
        for t in towers:
            ax.scatter([t["x"]], [t["y"]], c="k", s=60, marker="^", zorder=5)
        ax.set_aspect("equal")
        ax.set_title(f"extra shadow at 1e8: blue ridge ({genuine.sum()}), orange "
                     f"building ({by_bld.sum()}), red residual ({n_res})", fontsize=10)
        ax = axes[1]
        iy, ix = np.unravel_index(idx_res, target.shape)
        for label in cls_order:
            m = cls == label
            if m.any():
                ax.scatter(X[iy[m], ix[m]], Y[iy[m], ix[m]], s=8,
                           c=palette[label],
                           label=f"{label} ({int(m.sum())}, "
                                 f"{100 * m.sum() / n_res:.0f} %)")
        ax.contour(np.linspace(ext[0], ext[1], Ww), np.linspace(ext[2], ext[3], Hh),
                   ground, levels=10, colors="k", linewidths=0.3, alpha=0.4)
        for t in towers:
            ax.scatter([t["x"]], [t["y"]], c="k", s=60, marker="^", zorder=5)
        ax.set_xlim(ext[0], ext[1]); ax.set_ylim(ext[2], ext[3])
        ax.set_aspect("equal"); ax.legend(fontsize=7, loc="upper left")
        ax.set_title("the 531 residual cells, classified", fontsize=10)
        fig.suptitle("F8 residual — what the 51.5 % 'unexplained' cells actually are",
                     fontsize=12)
        fig.tight_layout(rect=[0, 0, 1, 0.95])
        f1 = FIG_DIR / "f8_residual_classes.png"
        fig.savefig(f1, dpi=120, bbox_inches="tight"); plt.close(fig)
        print(f"wrote {f1}")

        # --- figure 2: the mechanism metrics ---
        fig, axes = plt.subplots(1, 3, figsize=(19, 5.5))
        ax = axes[0]
        bins = np.linspace(-5, 30, 71)
        for name, color in (("residual", "#d62728"), ("explained_dark", "#7f7f7f"),
                            ("lit", "#2ca02c")):
            ax.hist(np.clip(metrics[name]["ratio"], bins[0], bins[-1]), bins=bins,
                    density=True, histtype="step", lw=2, color=color, label=name)
        ax.axvline(1.0, color="k", ls=":", lw=1.5, label="1 Fresnel radius")
        ax.set_xlabel("best-tower min clearance / Fresnel radius")
        ax.set_ylabel("density"); ax.legend(fontsize=8); ax.grid(alpha=0.3)
        ax.set_title("clearance ratio: residual cells graze the surface", fontsize=10)
        ax = axes[1]
        for name, color in (("residual", "#d62728"), ("lit", "#2ca02c")):
            m = metrics[name]
            ax.scatter(m["ratio"], np.maximum(m["e_hits"], 1e-3), s=6, alpha=0.4,
                       c=color, label=name)
        ax.set_yscale("log"); ax.set_xlim(-3, 30)
        ax.axhline(E_HITS_LOW, color="k", ls=":", lw=1)
        ax.axvline(1.0, color="k", ls=":", lw=1)
        ax.set_xlabel("clearance / Fresnel radius")
        ax.set_ylabel("expected direct-ray hits at 1e8")
        ax.legend(fontsize=8); ax.grid(alpha=0.3)
        ax.set_title("hit expectation vs clearance", fontsize=10)
        ax = axes[2]
        labels = [label for label in cls_order if breakdown.get(label, 0) > 0]
        vals = [breakdown[label] for label in labels]
        ax.barh(range(len(labels)), vals,
                color=[palette[label] for label in labels])
        for i, v in enumerate(vals):
            ax.text(v + 3, i, f"{v} ({100 * v / n_res:.1f} %)", va="center",
                    fontsize=8)
        ax.set_yticks(range(len(labels))); ax.set_yticklabels(labels, fontsize=8)
        ax.invert_yaxis(); ax.set_xlabel("residual cells")
        ax.set_title(f"class breakdown of the {n_res} residual cells", fontsize=10)
        fig.suptitle("F8 residual — mechanism metrics", fontsize=12)
        fig.tight_layout(rect=[0, 0, 1, 0.93])
        f2 = FIG_DIR / "f8_residual_margins.png"
        fig.savefig(f2, dpi=120, bbox_inches="tight"); plt.close(fig)
        print(f"wrote {f2}")
        result["figures"] = [str(f1), str(f2)]
    except Exception as exc:                                    # METHOD rule 5
        failures.append({"cell": "figures", "error": repr(exc),
                         "traceback": traceback.format_exc(limit=5)})
        print(f"FAIL figures: {exc!r}")

    OUT_JSON.write_text(json.dumps(result, indent=2))
    print(f"failures: {len(failures)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
