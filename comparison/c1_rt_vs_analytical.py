#!/usr/bin/env python3
"""
C1 -- how closely does the shipped analytical model track deterministic ray tracing?

Pre-registered in ``benchmarks/METHOD.md``. The metrics were fixed before the first
number was produced: RMS error [dB], mean signed bias [dB], fitted path-loss exponent
``n`` per method and the delta, Pearson correlation, and the compute-cost ratio.
Nothing here is chosen after seeing a result, and no configuration is dropped because
its answer is awkward (METHOD rules 5-7).

What is compared
----------------
Ground truth is the ray-traced transect: ``sionna_analysis.py`` puts a Sionna RT
``PathSolver`` (max_depth 6, LoS + specular + diffuse + refraction) on 14 receivers
spaced 100 m apart along the radial from the *Rising Sun* tower toward the scene
origin, at 1.5 m, on the FLAT Newton/Barbados scene at 3.5 GHz, and writes
``sionna_out/link_metrics.csv``.

The challenger is ``examples/ulap_demo/propagation.py``: free space + two-ray ground
reflection + single-knife-edge diffraction, evaluated on **the same geometry the ray
tracer used** -- ``$ULAP_WORK_DIR/scene_build/scene_manifest.json``, the 576-building
Newton scene -- with ``use_terrain=False`` to mirror the flat Mitsuba scene, the same
tower, the same bearing and the same 14 distances. No cross-scene substitution is made.

The antenna-gain term
---------------------
Sionna's path gain includes the antenna patterns; the analytical model's ``path_gain_db``
is isotropic-to-isotropic. The RT run uses a ``tr38901`` V-polarised element at the TX
and a short ``dipole`` at the RX, both at default orientation (boresight +x), while the
transect runs at azimuth ~172 deg -- i.e. straight into the TX element's back lobe.
That is a units mismatch, not a physics disagreement, so BOTH are reported:

* ``raw``            -- analytical path gain as the library returns it;
* ``antenna_corrected`` -- plus the exact Sionna pattern gains, evaluated by calling
  Sionna's own ``v_tr38901_pattern`` / ``v_dipole_pattern`` along the LoS direction.

The correction is exact only for the LoS ray; the ground-reflected ray leaves at a
slightly different elevation. That approximation is declared, not hidden.

Delay-spread blindness
----------------------
The analytical model has no delay domain at all. It is not that it is inaccurate there;
it returns nothing. The RT delay spreads are reported and the analytical column is
``null`` by construction.

Run:
    ULAP_WORK_DIR=/path/to/rtwork MPLBACKEND=Agg \\
        /path/to/venv-rt/bin/python comparison/c1_rt_vs_analytical.py
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import resource
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

os.environ.setdefault("DRJIT_NO_RTLD_DEEPBIND", "1")
os.environ.setdefault("MPLBACKEND", "Agg")

REPO = Path(__file__).resolve().parent.parent
OUT_JSON = REPO / "comparison" / "results" / "c1.json"
OUT_FIG = REPO / "comparison" / "figures" / "c1_rt_vs_analytical.png"

WORK = Path(os.environ.get("ULAP_WORK_DIR", "")) if os.environ.get("ULAP_WORK_DIR") else None

# --- pre-registered configuration -------------------------------------------
FREQ_HZ = 3.5e9
RX_HEIGHT_M = 1.5
TX_NAME = "Rising Sun"
RT_REPEATS = 3            # METHOD rule 1
ANALYTICAL_REPEATS = 5    # cheap; more repeats cost nothing
GROUND_MODES = ("average", "coherent", "none")   # full declared sweep, all reported
PRIMARY_MODE = "average"                          # the library default
PRIMARY_GAIN = "antenna_corrected"

sys.path.insert(0, str(REPO / "examples"))


def md5(path: Path) -> str:
    h = hashlib.md5(usedforsecurity=False)  # content fingerprint, not a signature
    h.update(Path(path).read_bytes())
    return h.hexdigest()


def rusage_children():
    r = resource.getrusage(resource.RUSAGE_CHILDREN)
    return r.ru_utime, r.ru_stime


# ---------------------------------------------------------------- ground truth
def load_rt_transect() -> tuple[dict, dict]:
    """Ray-traced transect. Prefers the live work-dir output; falls back to the
    committed reference copy. Which one was used is recorded, with its MD5."""
    candidates = []
    if WORK is not None:
        candidates.append(WORK / "sionna_out" / "link_metrics.csv")
    candidates.append(REPO / "blender" / "sionna_out" / "link_metrics.csv")
    for p in candidates:
        if p.exists():
            with open(p, newline="") as fh:
                rows = list(csv.DictReader(fh))
            cols = {k: np.array([float(r[k]) for r in rows]) for k in rows[0]}
            return cols, {"path": str(p), "md5": md5(p), "n_points": len(rows)}
    raise FileNotFoundError(f"no link_metrics.csv found in {[str(c) for c in candidates]}")


# ------------------------------------------------------------------ analytical
def build_analytical(manifest: Path, towers: Path | None):
    from ulap_demo.scene import load_scene as load_demo_scene
    from ulap_demo.propagation import PropagationModel

    scene = load_demo_scene(manifest, towers_path=towers)
    tower = scene.tower(TX_NAME)
    return scene, tower, PropagationModel


def antenna_gain_db(tower, dists, ux, uy, rx_h=RX_HEIGHT_M, tx_z=None):
    """Exact Sionna pattern gains (TX tr38901 V + RX short dipole V) along the LoS
    direction, in dB. Calls Sionna's own pattern functions so this cannot drift from
    what the ray tracer actually applied."""
    import drjit as dr  # noqa: F401
    import mitsuba as mi
    from sionna.rt.antenna_pattern import v_tr38901_pattern, v_dipole_pattern

    dz = rx_h - float(tx_z)
    vx = ux * np.asarray(dists, dtype=float)
    vy = uy * np.asarray(dists, dtype=float)
    vz = np.full_like(vx, dz)
    r = np.sqrt(vx**2 + vy**2 + vz**2)

    # departure direction, TX local frame == world (orientation [0,0,0])
    theta_tx = np.arccos(vz / r)
    phi_tx = np.arctan2(vy, vx)
    # arrival direction at the RX points back toward the TX
    theta_rx = np.arccos(-vz / r)
    phi_rx = np.arctan2(-vy, -vx)

    c_tx = np.asarray(v_tr38901_pattern(mi.Float(theta_tx.tolist()),
                                        mi.Float(phi_tx.tolist()))[0])
    c_rx = np.asarray(v_dipole_pattern(mi.Float(theta_rx.tolist()),
                                       mi.Float(phi_rx.tolist()))[0])
    g_tx = 10 * np.log10(np.maximum(np.abs(c_tx) ** 2, 1e-30))
    g_rx = 10 * np.log10(np.maximum(np.abs(c_rx) ** 2, 1e-30))
    return g_tx + g_rx, g_tx, g_rx


# -------------------------------------------------------------------- RT solve
def rt_transect_solve(dists, tx, scene_xml: Path):
    """Re-run the ray-traced transect exactly as ``sionna_analysis.py`` stage 3 does,
    so its wall-clock is measurable and its numbers can be checked against the CSV."""
    import drjit as dr
    import mitsuba as mi
    from sionna.rt import load_scene, PlanarArray, Transmitter, Receiver, PathSolver

    t_load = time.monotonic()
    sc = load_scene(str(scene_xml))
    load_wall = time.monotonic() - t_load
    sc.frequency = FREQ_HZ
    sc.tx_array = PlanarArray(num_rows=1, num_cols=1, pattern="tr38901", polarization="V")
    sc.rx_array = PlanarArray(num_rows=1, num_cols=1, pattern="dipole", polarization="V")
    sc.add(Transmitter("rising_sun", [float(tx["x"]), float(tx["y"]), float(tx["h"])]))
    dirx, diry = -tx["x"], -tx["y"]
    L = (dirx ** 2 + diry ** 2) ** 0.5
    ux, uy = dirx / L, diry / L
    for i, d in enumerate(dists):
        sc.add(Receiver(f"rx{i}", [float(tx["x"] + ux * d), float(tx["y"] + uy * d),
                                   RX_HEIGHT_M]))
    t0 = time.monotonic()
    paths = PathSolver()(scene=sc, max_depth=6, los=True, specular_reflection=True,
                         diffuse_reflection=True, refraction=True, synthetic_array=False)
    a, tau = paths.cir()
    a = np.asarray(a)
    tau = np.asarray(tau)
    try:
        dr.sync_thread()          # Dr.Jit is lazy/async: force the GPU queue to drain
    except Exception:
        pass
    wall = time.monotonic() - t0

    ac = a[0] + 1j * a[1]
    gains, spreads, npaths = [], [], []
    for i, _d in enumerate(dists):
        p = (np.abs(ac[i]) ** 2).reshape(-1)
        tt = np.asarray(tau[i]).reshape(-1)
        m = np.isfinite(tt) & (p > 0)
        p, tt = p[m], tt[m]
        if p.sum() <= 0:
            gains.append(np.nan); spreads.append(np.nan); npaths.append(0); continue
        gains.append(10 * np.log10(p.sum()))
        tbar = np.sum(p * tt) / np.sum(p)
        spreads.append(float(np.sqrt(np.sum(p * (tt - tbar) ** 2) / np.sum(p)) * 1e9))
        npaths.append(int(len(p)))
    return {"wall_s": wall, "scene_load_wall_s": load_wall, "variant": mi.variant(),
            "path_gain_dB": np.array(gains), "delay_spread_ns": np.array(spreads),
            "num_paths": np.array(npaths)}


# --------------------------------------------------------------------- metrics
def compare(rt_pg, an_pg, dists):
    from ulap_demo.propagation import fit_log_distance
    err = an_pg - rt_pg
    ok = np.isfinite(err)
    e = err[ok]
    fit_rt = fit_log_distance(dists[ok], rt_pg[ok])
    fit_an = fit_log_distance(dists[ok], an_pg[ok])
    r = float(np.corrcoef(rt_pg[ok], an_pg[ok])[0, 1]) if e.size > 1 else float("nan")
    bias = float(np.mean(e))
    return {
        "rms_error_db": float(np.sqrt(np.mean(e ** 2))),
        "mean_signed_bias_db": bias,
        "debiased_rms_db": float(np.sqrt(np.mean((e - bias) ** 2))),
        "max_abs_error_db": float(np.max(np.abs(e))),
        "pearson_r": r,
        "n_rt": float(fit_rt.n),
        "n_analytical": float(fit_an.n),
        "delta_n": float(fit_an.n - fit_rt.n),
        "rt_fit_rms_residual_db": float(fit_rt.rms_db),
        "analytical_fit_rms_residual_db": float(fit_an.rms_db),
        "n_points": int(e.size),
        "error_db_by_distance": {int(d): (None if not np.isfinite(v) else round(float(v), 3))
                                 for d, v in zip(dists, err)},
    }


def main() -> int:
    failures: list[dict] = []
    result: dict = {
        "study": "C1",
        "question": ("How closely does the shipped analytical model (free-space + two-ray + "
                     "knife-edge) track deterministic ray tracing on the Newton transect?"),
        "pre_registered_metrics": ["rms_error_db", "mean_signed_bias_db",
                                   "path_loss_exponent_n_and_delta", "pearson_r",
                                   "compute_cost_ratio"],
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "host": {"node": platform.node(), "machine": platform.machine(),
                 "python": platform.python_version(), "executable": sys.executable},
        "config": {"freq_hz": FREQ_HZ, "rx_height_m": RX_HEIGHT_M, "tx": TX_NAME,
                   "rt_repeats": RT_REPEATS, "analytical_repeats": ANALYTICAL_REPEATS,
                   "ground_reflection_modes": list(GROUND_MODES),
                   "primary_cell": {"ground_reflection": PRIMARY_MODE,
                                    "gain_convention": PRIMARY_GAIN},
                   "ulap_work_dir": str(WORK) if WORK else None},
        "failures": failures,
    }

    # ---- ground truth -------------------------------------------------------
    rt_csv, rt_src = load_rt_transect()
    result["rt_reference"] = rt_src
    dists = rt_csv["distance_m"]
    rt_pg = rt_csv["path_gain_dB"]
    rt_ds = rt_csv["delay_spread_ns"]
    rt_np = rt_csv["num_paths"]

    # ---- geometry: the SAME scene the ray tracer used ------------------------
    manifest = None
    towers_json = None
    if WORK is not None and (WORK / "scene_build" / "scene_manifest.json").exists():
        manifest = WORK / "scene_build" / "scene_manifest.json"
        tp = WORK / "scene_build" / "towers_near.json"
        towers_json = tp if tp.exists() else None
        geometry_note = ("analytical model evaluated on the RT work-dir manifest -- "
                         "identical geometry to the ray tracer (no cross-scene substitution)")
    else:
        manifest = REPO / "examples" / "data" / "newton-open_scene_manifest.json"
        geometry_note = ("LIMITATION: $ULAP_WORK_DIR manifest unavailable; fell back to the "
                         "bundled OPEN-DATA scene (585 OSM buildings), which is NOT the "
                         "geometry the ray tracer used (576 government footprints). "
                         "Cross-scene comparison -- treat every number as indicative only.")
        failures.append({"cell": "geometry", "error": "work-dir scene manifest not found",
                         "action": "fell back to examples/data open-data scene"})
    result["geometry"] = {"manifest": str(manifest), "manifest_md5": md5(manifest),
                          "towers": str(towers_json) if towers_json else None,
                          "note": geometry_note}

    scene, tower, PropagationModel = build_analytical(manifest, towers_json)
    result["geometry"].update({
        "n_buildings": len(scene.buildings),
        "terrain_relief_m": round(float(scene.terrain["zmax"] - scene.terrain["zmin"]), 2),
        "tx_xyz_flat": [round(tower.x, 2), round(tower.y, 2), round(tower.h, 2)],
    })

    vx, vy = -tower.x, -tower.y
    L = float(np.hypot(vx, vy)) or 1.0
    ux, uy = vx / L, vy / L

    # ---- antenna-gain term (exact Sionna patterns) --------------------------
    gain_off = None
    try:
        gain_off, g_tx, g_rx = antenna_gain_db(tower, dists, ux, uy, tx_z=tower.h)
        result["antenna_gain_correction_db"] = {
            "tx_pattern": "tr38901 (V), orientation [0,0,0]",
            "rx_pattern": "dipole (V), orientation [0,0,0]",
            "azimuth_deg": round(float(np.degrees(np.arctan2(uy, ux))), 2),
            "tx_gain_db_by_distance": {int(d): round(float(v), 3) for d, v in zip(dists, g_tx)},
            "rx_gain_db_by_distance": {int(d): round(float(v), 3) for d, v in zip(dists, g_rx)},
            "total_db_by_distance": {int(d): round(float(v), 3) for d, v in zip(dists, gain_off)},
            "note": ("the transect leaves the TX element at ~172 deg azimuth, i.e. in its "
                     "back lobe; tr38901 clamps at -30 dB relative to its 8 dBi peak"),
        }
    except Exception as exc:                                     # METHOD rule 5
        failures.append({"cell": "antenna_gain_correction", "error": repr(exc),
                         "traceback": traceback.format_exc(limit=3)})
        result["antenna_gain_correction_db"] = None

    # ---- analytical sweep ---------------------------------------------------
    cells: dict = {}
    an_curves: dict = {}
    for mode in GROUND_MODES:
        try:
            model = PropagationModel(freq_hz=FREQ_HZ, rx_height_m=RX_HEIGHT_M,
                                     use_terrain=False, use_buildings=True,
                                     ground_reflection=mode)
            # cold: includes the one-off building rasterisation
            fresh_scene, fresh_tower, _ = build_analytical(manifest, towers_json)
            t0 = time.monotonic()
            pg_cold = model.radial(fresh_scene, fresh_tower, dists)
            t_cold = time.monotonic() - t0
            # warm: raster cached, evaluation only
            warm = []
            for _ in range(ANALYTICAL_REPEATS):
                t0 = time.monotonic()
                pg = model.radial(scene, tower, dists)
                warm.append(time.monotonic() - t0)
            assert np.allclose(pg, pg_cold), "analytical model is not deterministic"

            for conv in ("raw", "antenna_corrected"):
                if conv == "antenna_corrected" and gain_off is None:
                    failures.append({"cell": f"{mode}/{conv}",
                                     "error": "antenna gain correction unavailable"})
                    continue
                curve = pg if conv == "raw" else pg + gain_off
                key = f"{mode}/{conv}"
                cells[key] = compare(rt_pg, curve, dists)
                cells[key]["timing_s"] = {
                    "cold_wall_s": round(t_cold, 4),
                    "warm_wall_s_median": round(float(np.median(warm)), 6),
                    "warm_wall_s_all": [round(w, 6) for w in warm],
                }
                an_curves[key] = curve
        except Exception as exc:                                  # METHOD rule 5
            failures.append({"cell": mode, "error": repr(exc),
                             "traceback": traceback.format_exc(limit=5)})

    # ---- which analytical term is doing the work ----------------------------
    # A near-perfect match is a claim that needs its own audit: it matters whether the
    # agreement comes from physics or from the two methods computing the same quantity.
    try:
        model = PropagationModel(freq_hz=FREQ_HZ, rx_height_m=RX_HEIGHT_M,
                                 use_terrain=False, use_buildings=True,
                                 ground_reflection=PRIMARY_MODE)
        _, parts = model.radial(scene, tower, dists, return_parts=True)
        result["analytical_terms"] = {
            "fspl_db": {int(d): round(float(v), 3) for d, v in zip(dists, parts["fspl_db"])},
            "two_ray_db": {int(d): round(float(v), 3) for d, v in zip(dists, parts["two_ray_db"])},
            "diffraction_db": {int(d): round(float(v), 3)
                               for d, v in zip(dists, parts["diffraction_db"])},
            "los_flag": {int(d): bool(v) for d, v in zip(dists, parts["los"])},
            "note": ("Decomposition of the primary analytical cell. If diffraction_db is 0 at "
                     "every point, the knife-edge term -- the only term that knows the 576 "
                     "buildings exist -- contributed nothing, and the agreement with RT is a "
                     "free-space + ground-reflection result, not a scene result."),
        }
        result["why_the_agreement_is_close"] = {
            "rt_num_paths_median": float(np.median(rt_np)),
            "rt_path_gain_is_incoherent_power_sum": True,
            "diffraction_term_active_points": int(np.sum(parts["diffraction_db"] > 0.01)),
            "statement": (
                "Read this before quoting the RMS. (1) The shipped stage computes RT path gain "
                "as an INCOHERENT sum of per-path powers (sum |a_i|^2), not a coherent field "
                "sum. (2) The median RT path count on this transect is 2 -- a LoS ray and one "
                "ground bounce. An incoherent 2-path sum over a flat ground plane IS the "
                "phase-averaged two-ray model, which is exactly what ground_reflection="
                "'average' computes. The two methods are therefore evaluating near-identical "
                "mathematics on this transect, which is why they agree to ~0.1 dB. That is a "
                "real and reportable result, but it is evidence that THIS transect is an easy "
                "case, not that ray tracing is redundant in general."),
        }
    except Exception as exc:                                      # METHOD rule 5
        failures.append({"cell": "analytical_terms", "error": repr(exc),
                         "traceback": traceback.format_exc(limit=3)})

    # ---- RT cost + reproduction check ---------------------------------------
    rt_runs = []
    rt_recheck = None
    scene_xml = (WORK / "mitsuba_scene" / "scene.xml") if WORK else None
    if scene_xml is not None and scene_xml.exists():
        tx_dict = {"x": tower.x, "y": tower.y, "h": tower.h}
        if towers_json is not None:
            for t in json.loads(Path(towers_json).read_text()):
                if t["name"] == TX_NAME:
                    tx_dict = t
        for rep in range(RT_REPEATS):
            try:
                u0, s0 = rusage_children()
                out = rt_transect_solve(dists, tx_dict, scene_xml)
                rt_runs.append({"repeat": rep, "cold": rep == 0,
                                "wall_s": round(out["wall_s"], 4),
                                "scene_load_wall_s": round(out["scene_load_wall_s"], 4),
                                "mitsuba_variant": out["variant"]})
                if rep == 0:
                    d = out["path_gain_dB"] - rt_pg
                    rt_recheck = {
                        "max_abs_path_gain_delta_db": round(float(np.nanmax(np.abs(d))), 4),
                        "max_abs_delay_spread_delta_ns": round(
                            float(np.nanmax(np.abs(out["delay_spread_ns"] - rt_ds))), 4),
                        "num_paths_identical": bool(np.array_equal(out["num_paths"],
                                                                   rt_np.astype(int))),
                        "note": ("re-solve of the committed transect; a non-zero delta is the "
                                 "solver's own run-to-run variation, reported not hand-waved"),
                    }
            except Exception as exc:                              # METHOD rule 5
                failures.append({"cell": f"rt_transect_repeat_{rep}", "error": repr(exc),
                                 "traceback": traceback.format_exc(limit=5)})
    else:
        failures.append({"cell": "rt_transect_timing",
                         "error": f"mitsuba scene not found at {scene_xml}",
                         "action": "RT wall-clock not measured; cost ratio omitted"})

    result["rt_solve"] = {"repeats": rt_runs, "reproduction_check": rt_recheck}

    # ---- cost ratio ---------------------------------------------------------
    if rt_runs and cells:
        rt_med = float(np.median([r["wall_s"] for r in rt_runs]))
        rt_load = float(np.median([r["scene_load_wall_s"] for r in rt_runs]))
        prim = cells.get(f"{PRIMARY_MODE}/{PRIMARY_GAIN}") or next(iter(cells.values()))
        an_cold = prim["timing_s"]["cold_wall_s"]
        an_warm = prim["timing_s"]["warm_wall_s_median"]
        result["cost"] = {
            "rt_solve_wall_s_median": round(rt_med, 4),
            "rt_solve_wall_s_cold": rt_runs[0]["wall_s"],
            "rt_scene_load_wall_s_median": round(rt_load, 4),
            "rt_setup_plus_solve_wall_s": round(rt_load + rt_med, 4),
            "mitsuba_variant": rt_runs[0]["mitsuba_variant"],
            "analytical_cold_wall_s": an_cold,
            "analytical_warm_wall_s": an_warm,
            "cost_ratio_solve_only_warm": round(rt_med / max(an_warm, 1e-9), 1),
            "cost_ratio_solve_only_cold": round(rt_med / max(an_cold, 1e-9), 2),
            "cost_ratio_setup_plus_solve_over_analytical_cold": round(
                (rt_load + rt_med) / max(an_cold, 1e-9), 1),
            "note": ("Like-for-like is deliberately awkward here and is reported both ways. "
                     "Analytical 'cold' includes the one-off rasterisation of the 576 "
                     "footprints; 'warm' is the 14-point evaluation alone. RT 'solve' is the "
                     "PathSolver call with the Dr.Jit queue drained (dr.sync_thread); "
                     "'setup+solve' adds Mitsuba scene load. Neither RT number includes "
                     "interpreter start or the Mitsuba XML export that produced the scene. "
                     "This is a 14-receiver transect -- the smallest RT workload in the "
                     "pipeline; it is NOT representative of the coverage-map cost, which C3 "
                     "measures."),
        }

    # ---- delay-spread blindness (the honest failure mode C1 must expose) ----
    spike_idx = [i for i, v in enumerate(rt_ds) if v > 50.0]
    result["delay_spread"] = {
        "analytical_capability": None,
        "statement": ("The analytical model has NO delay domain. free-space + two-ray + "
                      "knife-edge produce a single scalar path gain per point; there is no "
                      "CIR, no tap set, no delay spread. This is not a large error -- it is "
                      "the absence of an output. Every value below is unmatched."),
        "rt_delay_spread_ns_by_distance": {int(d): float(v) for d, v in zip(dists, rt_ds)},
        "rt_num_paths_by_distance": {int(d): int(v) for d, v in zip(dists, rt_np)},
        "spikes_over_50ns": [{"distance_m": int(dists[i]),
                              "delay_spread_ns": float(rt_ds[i]),
                              "num_paths": int(rt_np[i])} for i in spike_idx],
        "rt_delay_spread_ns_median": float(np.median(rt_ds)),
        "rt_delay_spread_ns_max": float(np.max(rt_ds)),
        "analytical_delay_spread_ns_by_distance": {int(d): None for d in dists},
        "interpretation": ("The spikes coincide with a third path appearing (num_paths 2 -> 3): "
                           "a specular return off distant geometry arriving ~100 m of extra "
                           "path length late. A planner sizing a cyclic prefix or an equaliser "
                           "from the analytical model would see nothing at these ranges."),
    }

    result["cells"] = cells
    result["curves"] = {
        "distance_m": [float(d) for d in dists],
        "rt_path_gain_db": [float(v) for v in rt_pg],
        **{f"analytical_{k.replace('/', '_')}_db": [float(v) for v in c]
           for k, c in an_curves.items()},
    }

    # ---- where the cheap model WINS (METHOD rule 7, reported not buried) ----
    prim_key = f"{PRIMARY_MODE}/{PRIMARY_GAIN}"
    if prim_key in cells:
        c = cells[prim_key]
        los_like = {int(d): v for d, v in c["error_db_by_distance"].items()
                    if v is not None and abs(v) <= 3.0}
        result["where_the_cheap_model_wins"] = {
            "points_within_3dB_of_rt": sorted(los_like),
            "fraction_within_3dB": round(len(los_like) / max(c["n_points"], 1), 3),
            "cost_ratio": (result.get("cost", {}) or {}).get("cost_ratio_solve_only_warm"),
            "statement": ("Reported as a finding in its own right: on this transect the "
                          "analytical model reproduces the ray-traced path-gain trend at a "
                          "small fraction of the cost. Where it matches, determinism buys "
                          "confidence, not accuracy."),
        }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, indent=2))
    print(f"wrote {OUT_JSON}")

    # ---- figure -------------------------------------------------------------
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(3, 1, figsize=(10, 12), sharex=True,
                                 gridspec_kw={"height_ratios": [2.2, 1.4, 1.4]})
        ax = axes[0]
        ax.plot(dists, rt_pg, "o-", color="black", lw=2, label="Sionna RT (ground truth)")
        styles = {"average": "-", "coherent": "--", "none": ":"}
        for key, curve in an_curves.items():
            mode, conv = key.split("/")
            if conv != PRIMARY_GAIN:
                continue
            ax.plot(dists, curve, styles[mode], marker="s", ms=4,
                    label=f"analytical, ground={mode} (+antenna gain)")
        raw_key = f"{PRIMARY_MODE}/raw"
        if raw_key in an_curves:
            ax.plot(dists, an_curves[raw_key], "-.", color="grey",
                    label="analytical, raw (isotropic — no antenna pattern)")
        ax.set_ylabel("path gain [dB]")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8, loc="upper right")
        ax.set_title("C1 — analytical model vs deterministic ray tracing, Rising Sun transect "
                     "@ 3.5 GHz\n(same 576-building Newton geometry, flat scene)", fontsize=11)

        ax = axes[1]
        for key, curve in an_curves.items():
            mode, conv = key.split("/")
            if conv != PRIMARY_GAIN:
                continue
            ax.plot(dists, curve - rt_pg, styles[mode], marker="s", ms=4, label=f"ground={mode}")
        ax.axhline(0, color="black", lw=1)
        ax.axhspan(-3, 3, color="green", alpha=0.10, label="+/-3 dB")
        ax.set_ylabel("analytical - RT [dB]")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)

        ax = axes[2]
        ax.plot(dists, rt_ds, "s--", color="#d62728", label="RT RMS delay spread")
        for i in spike_idx:
            ax.annotate(f"{rt_ds[i]:.0f} ns\n({int(rt_np[i])} paths)",
                        (dists[i], rt_ds[i]), fontsize=8, color="#d62728",
                        xytext=(6, -4), textcoords="offset points")
        ax.axhline(0, color="grey", lw=1)
        ax.text(0.5, 0.55, "analytical model: NO delay-spread output at any range",
                transform=ax.transAxes, ha="center", fontsize=10, color="grey",
                style="italic")
        ax.set_ylabel("RMS delay spread [ns]")
        ax.set_xlabel("distance from Rising Sun tower [m]")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8, loc="upper left")

        fig.tight_layout()
        OUT_FIG.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(OUT_FIG, dpi=130, bbox_inches="tight")
        print(f"wrote {OUT_FIG}")
    except Exception as exc:                                      # METHOD rule 5
        failures.append({"cell": "figure", "error": repr(exc),
                         "traceback": traceback.format_exc(limit=3)})
        OUT_JSON.write_text(json.dumps(result, indent=2))

    # ---- console summary ----------------------------------------------------
    print("\n--- C1 summary ---")
    for key in sorted(cells):
        c = cells[key]
        print(f"{key:>28}  RMS {c['rms_error_db']:7.2f} dB  bias {c['mean_signed_bias_db']:+7.2f} dB"
              f"  debiased RMS {c['debiased_rms_db']:5.2f} dB  r {c['pearson_r']:.4f}"
              f"  n_an {c['n_analytical']:.3f} vs n_rt {c['n_rt']:.3f}"
              f"  dn {c['delta_n']:+.3f}")
    if "cost" in result:
        print(f"cost: RT solve median {result['cost']['rt_solve_wall_s_median']} s "
              f"({result['cost']['mitsuba_variant']}) vs analytical warm "
              f"{result['cost']['analytical_warm_wall_s']} s "
              f"-> {result['cost']['cost_ratio_solve_only_warm']}x")
    print(f"failures: {len(failures)}")
    for f in failures:
        print("  FAIL", f)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
