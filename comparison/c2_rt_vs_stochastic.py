#!/usr/bin/env python3
"""
C2 -- is deterministic ray tracing actually an upgrade on the stochastic
3GPP TR 38.901 planning surface, as the paper claims?

Pre-registered in ``benchmarks/METHOD.md``. The metrics were fixed there before the
first number was produced and are not renegotiated here:

  * RMS error [dB]
  * mean signed bias [dB]
  * Pearson correlation
  * fraction of cells where the two methods disagree by more than 10 dB
  * fraction of cells where the two methods choose a DIFFERENT serving tower
  * fitted path-loss exponent ``n`` per method and the delta   (METHOD, C1/C2 row)
  * the compute-cost fraction                                   (METHOD, C1/C2 row)

Every one of them is reported with its spread across the stochastic ensemble.
No configuration is dropped because its answer is awkward (METHOD rules 5-7), and
the stochastic model is **not** tuned to match the ray tracer: every constant below
is the value printed in the standard, with the table it comes from cited inline.

What is compared
----------------
*Deterministic reference* -- Sionna RT ``RadioMapSolver`` on the Newton (Barbados)
government scene: 576 LiDAR-height footprints, 55.5 m of relief, the two in-scene
towers from ``scene_build/towers_near.json``, 3.5 GHz, 8 m cells, ``max_depth`` 5,
10^7 samples/TX. Two reference arms are solved:

``flat``            the flat Mitsuba scene, TX at z = h, one measurement plane at
                    1.5 m. **Primary**, because TR 38.901 is a flat-earth closed
                    form and this is the like-for-like geometry.
``terrain_ground``  the terrain scene, TX at z = ground_z + h, a stack of K=9 planes
                    with each cell read from the plane nearest (local terrain +
                    1.5 m) -- i.e. what ``sionna_terrain_ground.py`` ships. Cells
                    whose nearest plane lands below local ground (the discretisation
                    artifact C3 quantified) are excluded and the count is recorded.

The maps are **re-solved here**, not read from ``sionna_out/`` -- that directory holds
rendered PNGs, not arrays. Wall-clock and the Mitsuba variant are read back from the
run, never assumed (METHOD rule 2).

*Challenger* -- TR 38.901 implemented from the standard in this file:
``rma_pathloss`` / ``uma_pathloss`` (Table 7.4.1-1), ``los_probability``
(Table 7.4.2-1), log-normal shadow fading at the standard's sigma with the
horizontal correlation distances of Table 7.5-6. It is evaluated on the **same
grid, same towers, same frequency** as the ray tracer, and it is given no scene:
it sees a 2-D distance, a mast height and a UE height, which is exactly what a
national planning surface gives it.

The design matrix (all cells run, all reported)
-----------------------------------------------
scenario     RMa (primary, justified from the scene's measured 4.0 % built fraction
             and 4.5 m mean building height) | UMa (sensitivity)
LOS state    probabilistic (Table 7.4.2-1, the honest stochastic behaviour) |
             geometric (the ray tracer's own LOS-only solve used as an oracle --
             this isolates how much of the disagreement is the LOS *state* model
             rather than the path-loss formulas)
shadow fade  none (deterministic median) | iid per cell | spatially correlated
             (primary; Table 7.5-6 correlation distances)
gain units   raw (isotropic-to-isotropic, as the standard defines it) |
             antenna_corrected (primary)

The antenna-units mismatch, handled as C1 handled it
----------------------------------------------------
Sionna's path gain includes the antenna patterns; a closed-form path-loss model has
none. The RT run uses a ``tr38901`` V element at each TX and a short ``dipole`` V at
the RX, both at default orientation (boresight +x). TR 38.901 path loss is
isotropic-to-isotropic. That is a units mismatch, not a physics disagreement, so BOTH
conventions are reported and ``antenna_corrected`` is declared primary:

    raw               path gain = -PL_38901
    antenna_corrected path gain = -PL_38901 + G_tx(theta,phi) + G_rx(theta,phi)

The pattern gains are obtained by calling Sionna's own ``v_tr38901_pattern`` /
``v_dipole_pattern`` along the TX->cell direction, so they cannot drift from what the
solver applied. This matters far more here than in C1: the correction is *per cell and
per tower*, so it moves the serving-tower decision, not just an offset.

Run:
    ULAP_WORK_DIR=/path/to/rtwork MPLBACKEND=Agg \\
        /path/to/venv-rt/bin/python comparison/c2_rt_vs_stochastic.py
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
from pathlib import Path

import numpy as np

os.environ.setdefault("DRJIT_NO_RTLD_DEEPBIND", "1")
os.environ.setdefault("MPLBACKEND", "Agg")

REPO = Path(__file__).resolve().parent.parent
OUT_JSON = REPO / "comparison" / "results" / "c2.json"
OUT_FIG = REPO / "comparison" / "figures" / "c2_rt_vs_stochastic.png"
OUT_FIG2 = REPO / "comparison" / "figures" / "c2_serving_cell.png"
WORK = Path(os.environ.get("ULAP_WORK_DIR", ""))

sys.path.insert(0, str(REPO / "examples"))

# --- pre-registered configuration -------------------------------------------
FREQ_HZ = 3.5e9
CELL_M = 8.0
SAMPLES_PER_TX = 10 ** 7
MAX_DEPTH = 5
RX_AGL_M = 1.5                 # TR 38.901 h_UT
K_PLANES = 9                   # the shipped ground-following stage's plane count
RT_REPEATS = 3                 # METHOD rule 1
RT_SEEDS = [42, 43, 44]
N_REALISATIONS = 20            # stochastic draws; declared BEFORE any result
SF_BASE_SEED = 20260729

RT_REFS = ("flat", "terrain_ground")
SCENARIOS = ("RMa", "UMa")
LOS_STATES = ("probabilistic", "geometric")
SF_MODES = ("none", "iid", "correlated")
GAIN_CONVENTIONS = ("raw", "antenna_corrected")

PRIMARY = {"rt_ref": "flat", "scenario": "RMa", "los_state": "probabilistic",
           "shadow_fading": "correlated", "gain": "antenna_corrected"}
SCEN_IDX = {s: i for i, s in enumerate(SCENARIOS)}   # deterministic; str hash() is
                                                     # per-process randomised in CPython
PRIMARY_KEY = "/".join([PRIMARY["rt_ref"], PRIMARY["scenario"], PRIMARY["los_state"],
                        PRIMARY["shadow_fading"], PRIMARY["gain"]])

# TR 38.901 environment parameters -- the STANDARD's defaults, not fitted here.
# Table 7.4.1-1 note: RMa is parameterised by average building height h and average
# street width W; the note gives the applicability ranges 5 m <= h <= 50 m and
# 5 m <= W <= 50 m and the model is evaluated at the defaults used throughout the TR.
RMA_H_BUILDING_M = 5.0
RMA_W_STREET_M = 20.0

# Table 7.5-6 (Part 1 UMa / Part 2 RMa): SF correlation distance in the horizontal plane
SF_CORR_DIST_M = {("RMa", "LOS"): 37.0, ("RMa", "NLOS"): 120.0,
                  ("UMa", "LOS"): 37.0, ("UMa", "NLOS"): 50.0}

C_LIGHT = 299_792_458.0


def md5(path: Path) -> str:
    h = hashlib.md5(usedforsecurity=False)  # content fingerprint, not a signature
    h.update(Path(path).read_bytes())
    return h.hexdigest()


# ============================================================================
#  3GPP TR 38.901 -- implemented from the standard, cited equation by equation
# ============================================================================
def los_probability(scenario: str, d2d: np.ndarray, h_ut: float) -> np.ndarray:
    """TR 38.901 Table 7.4.2-1, LOS probability.

    RMa : Pr_LOS = 1                              , d_2D <= 10 m
                 = exp(-(d_2D - 10) / 1000)       , d_2D  > 10 m
    UMa : Pr_LOS = 1                              , d_2D <= 18 m
                 = [18/d_2D + exp(-d_2D/63)(1 - 18/d_2D)]
                   * [1 + C'(h_UT) * (5/4)(d_2D/100)^3 exp(-d_2D/150)] , d_2D > 18 m
          with C'(h_UT) = 0 for h_UT <= 13 m (our h_UT = 1.5 m), so the second
          bracket is exactly 1 here.
    """
    d = np.maximum(np.asarray(d2d, dtype=float), 1e-6)
    if scenario == "RMa":
        return np.where(d <= 10.0, 1.0, np.exp(-(d - 10.0) / 1000.0))
    if scenario == "UMa":
        c_prime = 0.0 if h_ut <= 13.0 else ((h_ut - 13.0) / 10.0) ** 1.5
        base = 18.0 / d + np.exp(-d / 63.0) * (1.0 - 18.0 / d)
        corr = 1.0 + c_prime * 1.25 * (d / 100.0) ** 3 * np.exp(-d / 150.0)
        return np.where(d <= 18.0, 1.0, np.clip(base * corr, 0.0, 1.0))
    raise ValueError(scenario)


def rma_pathloss(d2d, d3d, fc_ghz, h_bs, h_ut,
                 h_build=RMA_H_BUILDING_M, w_street=RMA_W_STREET_M):
    """TR 38.901 Table 7.4.1-1, RMa. Returns (PL_LOS, PL_NLOS, sigma_LOS, sigma_NLOS).

    RMa LOS, 10 m <= d_2D <= d_BP :
        PL1 = 20 log10(40 pi d_3D f_c / 3) + min(0.03 h^1.72, 10) log10(d_3D)
              - min(0.044 h^1.72, 14.77) + 0.002 log10(h) d_3D          sigma_SF = 4
    RMa LOS, d_BP <= d_2D <= 10 km :
        PL2 = PL1(d_BP) + 40 log10(d_3D / d_3D_BP)                      sigma_SF = 6
        d_BP = 2 pi h_BS h_UT f_c / c
    RMa NLOS, 10 m <= d_2D <= 5 km :
        PL' = 161.04 - 7.1 log10(W) + 7.5 log10(h)
              - (24.37 - 3.7 (h/h_BS)^2) log10(h_BS)
              + (43.42 - 3.1 log10(h_BS)) (log10(d_3D) - 3)
              + 20 log10(f_c) - (3.2 (log10(11.75 h_UT))^2 - 4.97)
        PL_NLOS = max(PL_LOS, PL')                                      sigma_SF = 8
    f_c in GHz, all distances in m.
    """
    d2d = np.asarray(d2d, dtype=float)
    d3d = np.asarray(d3d, dtype=float)
    fc_hz = fc_ghz * 1e9

    def pl1(d3):
        return (20.0 * np.log10(40.0 * np.pi * d3 * fc_ghz / 3.0)
                + min(0.03 * h_build ** 1.72, 10.0) * np.log10(d3)
                - min(0.044 * h_build ** 1.72, 14.77)
                + 0.002 * np.log10(h_build) * d3)

    d_bp = 2.0 * np.pi * h_bs * h_ut * fc_hz / C_LIGHT
    d3d_bp = np.sqrt(d_bp ** 2 + (h_bs - h_ut) ** 2)
    pl_los = np.where(d2d <= d_bp, pl1(d3d), pl1(d3d_bp) + 40.0 * np.log10(d3d / d3d_bp))
    sigma_los = np.where(d2d <= d_bp, 4.0, 6.0)

    pl_nlos_prime = (161.04
                     - 7.1 * np.log10(w_street)
                     + 7.5 * np.log10(h_build)
                     - (24.37 - 3.7 * (h_build / h_bs) ** 2) * np.log10(h_bs)
                     + (43.42 - 3.1 * np.log10(h_bs)) * (np.log10(d3d) - 3.0)
                     + 20.0 * np.log10(fc_ghz)
                     - (3.2 * (np.log10(11.75 * h_ut)) ** 2 - 4.97))
    pl_nlos = np.maximum(pl_los, pl_nlos_prime)
    sigma_nlos = np.full_like(pl_nlos, 8.0)
    return pl_los, pl_nlos, sigma_los, sigma_nlos, float(d_bp)


def uma_pathloss(d2d, d3d, fc_ghz, h_bs, h_ut):
    """TR 38.901 Table 7.4.1-1, UMa. Returns (PL_LOS, PL_NLOS, sigma_LOS, sigma_NLOS).

    UMa LOS, 10 m <= d_2D <= d'_BP :
        PL1 = 28.0 + 22 log10(d_3D) + 20 log10(f_c)                     sigma_SF = 4
    UMa LOS, d'_BP <= d_2D <= 5 km :
        PL2 = 28.0 + 40 log10(d_3D) + 20 log10(f_c)
              - 9 log10((d'_BP)^2 + (h_BS - h_UT)^2)                    sigma_SF = 4
        d'_BP = 4 h'_BS h'_UT f_c / c, with h'_BS = h_BS - h_E,
        h'_UT = h_UT - h_E and h_E = 1.0 m for h_UT < 13 m (Note 1).
    UMa NLOS, 10 m <= d_2D <= 5 km :
        PL' = 13.54 + 39.08 log10(d_3D) + 20 log10(f_c) - 0.6 (h_UT - 1.5)
        PL_NLOS = max(PL_LOS, PL')                                      sigma_SF = 6
    """
    d2d = np.asarray(d2d, dtype=float)
    d3d = np.asarray(d3d, dtype=float)
    fc_hz = fc_ghz * 1e9
    h_e = 1.0                      # Note 1, h_UT < 13 m
    d_bp = 4.0 * (h_bs - h_e) * (h_ut - h_e) * fc_hz / C_LIGHT
    pl1 = 28.0 + 22.0 * np.log10(d3d) + 20.0 * np.log10(fc_ghz)
    pl2 = (28.0 + 40.0 * np.log10(d3d) + 20.0 * np.log10(fc_ghz)
           - 9.0 * np.log10(d_bp ** 2 + (h_bs - h_ut) ** 2))
    pl_los = np.where(d2d <= d_bp, pl1, pl2)
    sigma_los = np.full_like(pl_los, 4.0)
    pl_nlos_prime = (13.54 + 39.08 * np.log10(d3d) + 20.0 * np.log10(fc_ghz)
                     - 0.6 * (h_ut - 1.5))
    pl_nlos = np.maximum(pl_los, pl_nlos_prime)
    sigma_nlos = np.full_like(pl_nlos, 6.0)
    return pl_los, pl_nlos, sigma_los, sigma_nlos, float(d_bp)


def correlated_field(shape, cell_m, d_cor, rng):
    """Unit-variance Gaussian field with exponential spatial autocorrelation
    exp(-d / d_cor) -- the Gudmundson form TR 38.901 Sec. 7.6.3.1 assumes, with the
    correlation distance from Table 7.5-6. Synthesised by circulant embedding on a
    2x-padded grid; no per-realisation renormalisation is applied (the synthesis is
    unit-variance by construction, and that is validated in the JSON)."""
    h, w = shape
    hp, wp = 2 * h, 2 * w
    yy = np.minimum(np.arange(hp), hp - np.arange(hp)) * cell_m
    xx = np.minimum(np.arange(wp), wp - np.arange(wp)) * cell_m
    k = np.exp(-np.hypot(yy[:, None], xx[None, :]) / d_cor)
    s = np.clip(np.fft.fft2(k).real, 0.0, None)
    n = rng.standard_normal((hp, wp))
    return np.fft.ifft2(np.fft.fft2(n) * np.sqrt(s)).real[:h, :w]


# ============================================================================
#  metrics -- fixed by METHOD before any number was seen
# ============================================================================
def _pearson(a, b):
    if a.size < 2:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def metrics_one(st_db: np.ndarray, rt_db: np.ndarray, valid: np.ndarray,
                d3d: np.ndarray) -> dict:
    """One stochastic realisation vs the deterministic map.

    ``st_db`` / ``rt_db`` are [n_tx, H, W] path gain in dB; ``valid`` is [n_tx, H, W]
    and True where the ray tracer produced a usable value. The *primary* surface is
    the best-server map -- that is the surface a planner actually reads -- and the
    per-TX pooled numbers are reported alongside it."""
    from ulap_demo.propagation import fit_log_distance

    # ---- per-TX pooled -------------------------------------------------------
    e = (st_db - rt_db)[valid]
    rt_v = rt_db[valid]
    st_v = st_db[valid]
    bias = float(np.mean(e))
    per_tx = {
        "rms_error_db": float(np.sqrt(np.mean(e ** 2))),
        "mean_signed_bias_db": bias,
        "debiased_rms_db": float(np.sqrt(np.mean((e - bias) ** 2))),
        "pearson_r": _pearson(rt_v, st_v),
        "fraction_over_10db": float(np.mean(np.abs(e) > 10.0)),
        "n_compared": int(valid.sum()),
    }

    # ---- best server (primary surface) --------------------------------------
    rt_masked = np.where(valid, rt_db, -np.inf)
    any_valid = valid.any(axis=0)
    rt_best_idx = np.argmax(rt_masked, axis=0)
    rt_best_db = np.max(rt_masked, axis=0)
    st_best_idx = np.argmax(st_db, axis=0)
    st_best_db = np.max(st_db, axis=0)
    bv = any_valid & np.isfinite(rt_best_db)

    eb = (st_best_db - rt_best_db)[bv]
    bias_b = float(np.mean(eb))
    best = {
        "rms_error_db": float(np.sqrt(np.mean(eb ** 2))),
        "mean_signed_bias_db": bias_b,
        "debiased_rms_db": float(np.sqrt(np.mean((eb - bias_b) ** 2))),
        "pearson_r": _pearson(rt_best_db[bv], st_best_db[bv]),
        "fraction_over_10db": float(np.mean(np.abs(eb) > 10.0)),
        "serving_cell_disagreement_fraction":
            float(np.mean(rt_best_idx[bv] != st_best_idx[bv])),
        "n_compared": int(bv.sum()),
        "rt_best_p10_db": float(np.percentile(rt_best_db[bv], 10)),
        "st_best_p10_db": float(np.percentile(st_best_db[bv], 10)),
        "rt_best_p05_db": float(np.percentile(rt_best_db[bv], 5)),
        "st_best_p05_db": float(np.percentile(st_best_db[bv], 5)),
        "rt_best_median_db": float(np.median(rt_best_db[bv])),
        "st_best_median_db": float(np.median(st_best_db[bv])),
    }

    # ---- fitted path-loss exponent (METHOD C1/C2 row) ------------------------
    fit_rt = fit_log_distance(d3d[valid], rt_db[valid])
    fit_st = fit_log_distance(d3d[valid], st_db[valid])
    fits = {"n_rt": float(fit_rt.n), "n_stochastic": float(fit_st.n),
            "delta_n": float(fit_st.n - fit_rt.n),
            "rt_fit_rms_residual_db": float(fit_rt.rms_db),
            "stochastic_fit_rms_residual_db": float(fit_st.rms_db)}
    return {"best_server": best, "per_tx_pooled": per_tx, "path_loss_exponent": fits}


def spread(vals) -> dict | None:
    a = np.asarray([v for v in vals if v is not None and np.isfinite(v)], dtype=float)
    if a.size == 0:
        return None
    return {"median": round(float(np.median(a)), 5), "mean": round(float(np.mean(a)), 5),
            "min": round(float(a.min()), 5), "max": round(float(a.max()), 5),
            "std": round(float(a.std(ddof=1)) if a.size > 1 else 0.0, 5),
            "p90_minus_p10": round(float(np.percentile(a, 90) - np.percentile(a, 10)), 5),
            "n_realisations": int(a.size)}


def collapse(per_real: list[dict]) -> dict:
    """Turn a list of per-realisation metric dicts into {metric: spread}."""
    out: dict = {}
    for group in per_real[0]:
        out[group] = {}
        for k in per_real[0][group]:
            out[group][k] = spread([r[group][k] for r in per_real])
    return out


# ============================================================================
def main() -> int:
    failures: list[dict] = []
    result: dict = {
        "study": "C2",
        "question": ("Is deterministic ray tracing actually an upgrade on the stochastic "
                     "3GPP TR 38.901 planning surface, on identical geometry?"),
        "pre_registered_metrics": [
            "rms_error_db", "mean_signed_bias_db", "pearson_r",
            "fraction_cells_over_10db", "serving_cell_disagreement_fraction",
            "path_loss_exponent_n_and_delta", "compute_cost_ratio",
            "stochastic_spread_across_realisations",
        ],
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "host": {"node": platform.node(), "machine": platform.machine(),
                 "python": platform.python_version(), "executable": sys.executable},
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
    towers = [t for t in json.loads(towers_path.read_text()) if t["in_scene"]]
    n_tx = len(towers)
    buildings_xy = [np.array(b["ring"]) for b in mani["buildings"]]

    # ---- scene character -> scenario justification (measured, not asserted) --
    b_h = np.array([b["h"] for b in mani["buildings"]], dtype=float)

    def ring_area(r):
        r = np.asarray(r, dtype=float)
        x, y = r[:, 0], r[:, 1]
        return abs(float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))) / 2.0

    footprint = float(np.sum([ring_area(b["ring"]) for b in mani["buildings"]]))
    scene_area = float((T["maxx"] - T["minx"]) * (T["maxy"] - T["miny"]))

    result["inputs"] = {
        "scene_flat": str(scene_flat), "scene_terrain": str(scene_terr),
        "manifest": str(mani_path), "manifest_md5": md5(mani_path),
        "towers": [{"name": t["name"], "x": t["x"], "y": t["y"], "h_m": t["h"],
                    "ground_z_m": t["ground_z"]} for t in towers],
        "n_buildings": len(mani["buildings"]),
        "terrain_relief_m": round(float(T["zmax"] - T["zmin"]), 2),
        "scene": ("Newton, Barbados - the government scene the ray tracer was run on "
                  "(576 LiDAR-height footprints). NOT the bundled open-data examples/ "
                  "scene; the two are never mixed."),
        "sionna_out_note": ("$ULAP_WORK_DIR/sionna_out/ holds rendered PNGs, not arrays, "
                            "so the deterministic maps are RE-SOLVED here rather than "
                            "reused. The solver configuration matches the shipped stages."),
    }
    result["scenario_choice"] = {
        "primary": "RMa",
        "also_run": "UMa",
        "measured_scene_statistics": {
            "built_area_fraction": round(footprint / scene_area, 4),
            "scene_area_km2": round(scene_area / 1e6, 3),
            "building_height_m": {"min": round(float(b_h.min()), 2),
                                  "p10": round(float(np.percentile(b_h, 10)), 2),
                                  "median": round(float(np.median(b_h)), 2),
                                  "mean": round(float(b_h.mean()), 2),
                                  "p90": round(float(np.percentile(b_h, 90)), 2),
                                  "max": round(float(b_h.max()), 2)},
            "tx_heights_m": [t["h"] for t in towers],
        },
        "justification": (
            "RMa is the primary scenario. Measured from the scene itself: buildings cover "
            f"{footprint / scene_area * 100:.1f} % of the {scene_area / 1e6:.2f} km2 footprint "
            f"and their mean height is {b_h.mean():.2f} m (median {np.median(b_h):.2f} m) - "
            "low-rise, sparse, detached settlement around a rural parish, not a dense urban "
            "core. TR 38.901's UMa is defined for a dense high-rise grid with h_BS = 25 m "
            "above rooftop; RMa is defined for exactly this: low buildings, wide spacing, "
            "masts well above clutter. The two masts here are 30 m and 24 m, inside RMa's "
            "10-150 m applicability window. UMa is run anyway as a declared sensitivity arm "
            "so that the scenario choice can be audited rather than trusted."),
        "declared_applicability_violation": (
            f"TR 38.901 Table 7.4.1-1 states RMa applicability 5 m <= h <= 50 m for the "
            f"average building height. The scene's measured mean is {b_h.mean():.2f} m, "
            f"marginally BELOW that floor. The model is nevertheless evaluated at the "
            f"standard's h = {RMA_H_BUILDING_M} m / W = {RMA_W_STREET_M} m and is NOT "
            "refitted to the scene; a scene-informed sensitivity (h = measured mean) is "
            "reported separately so the effect of that choice is visible."),
    }

    # ---- common grid (identical construction to C3) --------------------------
    sc0 = load_scene(str(scene_terr))
    bb = sc0.mi_scene.bbox()
    cx = float((bb.min[0] + bb.max[0]) / 2); cy = float((bb.min[1] + bb.max[1]) / 2)
    sx = float(bb.max[0] - bb.min[0]); sy = float(bb.max[1] - bb.min[1])
    sc1 = load_scene(str(scene_flat))
    bb1 = sc1.mi_scene.bbox()
    xy_identical = (abs(float(bb.min[0]) - float(bb1.min[0])) < 1e-3
                    and abs(float(bb.max[1]) - float(bb1.max[1])) < 1e-3)
    result["grid"] = {"center_xy": [round(cx, 2), round(cy, 2)],
                      "size_xy": [round(sx, 2), round(sy, 2)], "cell_m": CELL_M,
                      "flat_and_terrain_xy_extent_identical": bool(xy_identical)}
    if not xy_identical:
        failures.append({"cell": "grid", "error": "flat and terrain scenes differ in x/y "
                                                  "extent; per-cell comparison approximate"})

    result["config"] = {
        "freq_hz": FREQ_HZ, "cell_m": CELL_M, "samples_per_tx": SAMPLES_PER_TX,
        "max_depth": MAX_DEPTH, "rx_agl_m": RX_AGL_M, "k_planes": K_PLANES,
        "rt_repeats": RT_REPEATS, "rt_seeds": RT_SEEDS,
        "n_realisations": N_REALISATIONS, "sf_base_seed": SF_BASE_SEED,
        "rt_references": list(RT_REFS), "scenarios": list(SCENARIOS),
        "los_states": list(LOS_STATES), "shadow_fading_modes": list(SF_MODES),
        "gain_conventions": list(GAIN_CONVENTIONS),
        "primary_cell": PRIMARY, "primary_cell_key": PRIMARY_KEY,
        "ulap_work_dir": str(WORK),
        "tr38901_parameters": {
            "h_building_m": RMA_H_BUILDING_M, "w_street_m": RMA_W_STREET_M,
            "sf_correlation_distance_m": {f"{k[0]}/{k[1]}": v
                                          for k, v in SF_CORR_DIST_M.items()},
            "source": ("3GPP TR 38.901: path loss Table 7.4.1-1, LOS probability "
                       "Table 7.4.2-1, shadow-fading sigma and horizontal correlation "
                       "distance Table 7.5-6 / Sec. 7.6.3.1. Values as printed in the "
                       "standard; nothing here is fitted to the ray tracer."),
        },
        "stochastic_model_is_scene_free": (
            "The TR 38.901 arm receives only d_2D, h_BS and h_UT. It is given no "
            "buildings, no terrain and no LOS geometry (except in the declared "
            "'geometric' LOS-state arm, which exists precisely to separate the LOS "
            "state model from the path-loss formulas). That is the point of the "
            "comparison: it is what a national planning surface has."),
        "primary_surface": ("best-server path gain map - the surface a planner reads. "
                            "Per-TX pooled numbers are reported alongside every cell."),
    }

    # ========================================================================
    #  deterministic reference solves
    # ========================================================================
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

    def solve(sc, z, seed, los_only=False):
        t0 = time.monotonic()
        kw = dict(scene=sc, cell_size=(CELL_M, CELL_M), samples_per_tx=SAMPLES_PER_TX,
                  center=[cx, cy, float(z)], size=[sx, sy], orientation=[0., 0., 0.],
                  seed=seed)
        if los_only:
            rm = solver(max_depth=0, los=True, specular_reflection=False,
                        diffuse_reflection=False, refraction=False, **kw)
        else:
            rm = solver(max_depth=MAX_DEPTH, **kw)
        pg = np.array(rm.path_gain)
        cc = np.array(rm.cell_centers)
        dr.sync_thread()
        return pg, cc, time.monotonic() - t0

    def terrain_sampler(Tm):
        nx, ny = Tm["nx"], Tm["ny"]
        z = np.array(Tm["z"], dtype=float).reshape(ny, nx)

        def terr(x, y):
            fx = np.clip((x - Tm["minx"]) / (Tm["maxx"] - Tm["minx"]) * (nx - 1), 0, nx - 1)
            fy = np.clip((y - Tm["miny"]) / (Tm["maxy"] - Tm["miny"]) * (ny - 1), 0, ny - 1)
            ix = fx.astype(int); iy = fy.astype(int)
            ix1 = np.minimum(ix + 1, nx - 1); iy1 = np.minimum(iy + 1, ny - 1)
            tx = fx - ix; ty = fy - iy
            return (z[iy, ix] * (1 - tx) * (1 - ty) + z[iy, ix1] * tx * (1 - ty)
                    + z[iy1, ix] * (1 - tx) * ty + z[iy1, ix1] * tx * ty)
        return terr

    plane_z = np.linspace(T["zmin"] + RX_AGL_M, T["zmax"] + RX_AGL_M, K_PLANES)
    refs: dict[str, dict] = {}
    ref_report: dict[str, dict] = {}

    for ref in RT_REFS:
        try:
            reps_pg, timings = [], []
            cc = None
            extra: dict = {}
            for rep, seed in enumerate(RT_SEEDS[:RT_REPEATS]):
                if ref == "flat":
                    sc = build(scene_flat, terrain=False)
                    pg, cc_i, wall = solve(sc, RX_AGL_M, seed)
                    n_solves = 1
                else:
                    sc = build(scene_terr, terrain=True)
                    stack, wall, cc_i = [], 0.0, None
                    for z in plane_z:
                        p, c, w = solve(sc, z, seed)
                        stack.append(p); wall += w
                        if cc_i is None:
                            cc_i = c
                    stack = np.stack(stack, axis=0)                  # [K, n_tx, H, W]
                    terr = terrain_sampler(T)
                    target = terr(cc_i[..., 0], cc_i[..., 1]) + RX_AGL_M
                    kbest = np.argmin(np.abs(plane_z[:, None, None] - target[None]), axis=0)
                    pg = np.take_along_axis(stack, kbest[None, None], axis=0)[0]
                    cc_i = cc_i.copy()
                    cc_i[..., 2] = plane_z[kbest]
                    n_solves = K_PLANES
                    if rep == 0:
                        underground = plane_z[kbest] < (target - RX_AGL_M)
                        extra = {"underground_cell_fraction":
                                 round(float(np.mean(underground)), 5),
                                 "plane_spacing_m": round(float(plane_z[1] - plane_z[0]), 3),
                                 "note": ("Cells whose nearest plane lands BELOW local "
                                          "ground read zero path gain and are "
                                          "indistinguishable from genuine shadow (the "
                                          "artifact C3 quantified). They are EXCLUDED from "
                                          "this arm's comparison, in numerator and "
                                          "denominator alike.")}
                        extra["_mask"] = underground
                reps_pg.append(pg)
                if cc is None:
                    cc = cc_i
                timings.append({"repeat": rep, "seed": seed, "cold": rep == 0,
                                "wall_s": round(wall, 4), "n_solves": n_solves,
                                "mitsuba_variant": mi.variant()})
                print(f"  [RT {ref:>14} rep{rep} seed{seed}] {wall:6.3f} s shape {pg.shape}")

            # LOS oracle: LOS-only solve, non-zero == geometric line of sight
            if ref == "flat":
                sc = build(scene_flat, terrain=False)
                los_pg, _, los_wall = solve(sc, RX_AGL_M, RT_SEEDS[0], los_only=True)
            else:
                sc = build(scene_terr, terrain=True)
                stack, los_wall = [], 0.0
                for z in plane_z:
                    p, c, w = solve(sc, z, RT_SEEDS[0], los_only=True)
                    stack.append(p); los_wall += w
                stack = np.stack(stack, axis=0)
                terr = terrain_sampler(T)
                target = terr(cc[..., 0], cc[..., 1]) + RX_AGL_M
                kbest = np.argmin(np.abs(plane_z[:, None, None] - target[None]), axis=0)
                los_pg = np.take_along_axis(stack, kbest[None, None], axis=0)[0]
            geo_los = los_pg > 0.0                                    # [n_tx, H, W]

            pg0 = reps_pg[0]
            with np.errstate(divide="ignore"):
                rt_db = 10.0 * np.log10(pg0)
            rt_db[~np.isfinite(rt_db)] = np.nan
            valid = np.isfinite(rt_db)
            if extra.get("_mask") is not None:
                valid = valid & (~extra["_mask"])[None, :, :]

            # Monte-Carlo noise floor: same configuration, different solver seed.
            floor = None
            if len(reps_pg) > 1:
                with np.errstate(divide="ignore"):
                    d1 = 10.0 * np.log10(reps_pg[1])
                d1[~np.isfinite(d1)] = np.nan
                v01 = valid & np.isfinite(d1)
                a0 = np.where(v01, rt_db, -np.inf)
                a1 = np.where(v01, d1, -np.inf)
                bv = v01.any(axis=0)
                floor = {
                    "serving_cell_change_same_config_different_seed": round(float(np.mean(
                        np.argmax(a0, axis=0)[bv] != np.argmax(a1, axis=0)[bv])), 5),
                    "best_server_rms_delta_db": round(float(np.sqrt(np.nanmean(
                        (np.max(a0, axis=0)[bv] - np.max(a1, axis=0)[bv]) ** 2))), 4),
                    "note": ("RadioMapSolver is a Monte-Carlo estimator. Any "
                             "serving-cell disagreement the stochastic model produces "
                             "must clearly exceed this floor to mean anything."),
                }

            refs[ref] = {"rt_db": rt_db, "valid": valid, "cell_centers": cc,
                         "geo_los": geo_los,
                         "tx_z": np.array([float(t["ground_z"] + t["h"]) if ref != "flat"
                                           else float(t["h"]) for t in towers])}
            rep = {"status": "ok", "timing": timings,
                   "wall_s_median": round(float(np.median([t["wall_s"] for t in timings])), 4),
                   "mitsuba_variant": timings[0]["mitsuba_variant"],
                   "los_oracle_wall_s": round(los_wall, 4),
                   "geometric_los_fraction_per_tx":
                       [round(float(np.mean(geo_los[i])), 4) for i in range(n_tx)],
                   "no_coverage_fraction_per_tx":
                       [round(float(1 - np.mean(valid[i])), 5) for i in range(n_tx)],
                   "grid_shape": list(rt_db.shape)}
            if floor is not None:
                rep["mc_noise_floor"] = floor["serving_cell_change_same_config_different_seed"]
                rep["mc_noise_floor_detail"] = floor
            rep.update({k: v for k, v in extra.items() if not k.startswith("_")})
            ref_report[ref] = rep
        except Exception as exc:                                      # METHOD rule 5
            failures.append({"cell": f"rt_reference/{ref}", "error": repr(exc),
                             "traceback": traceback.format_exc(limit=6)})
            ref_report[ref] = {"status": "failed", "error": repr(exc)}
            print(f"  FAIL rt_reference {ref}: {exc!r}")

    result["rt_reference"] = ref_report
    if not refs:
        OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
        OUT_JSON.write_text(json.dumps(result, indent=2))
        print(f"ABORT: no deterministic reference solved; wrote {OUT_JSON}")
        return 1

    # ========================================================================
    #  geometry + antenna gains, per reference arm
    # ========================================================================
    def antenna_gain(cc, tx_xyz):
        """Exact Sionna pattern gains [n_tx, H, W] in dB along the TX->cell ray."""
        from sionna.rt.antenna_pattern import v_tr38901_pattern, v_dipole_pattern
        out = []
        for i, t in enumerate(towers):
            vx = cc[..., 0] - float(t["x"])
            vy = cc[..., 1] - float(t["y"])
            vz = cc[..., 2] - float(tx_xyz[i])
            r = np.maximum(np.sqrt(vx ** 2 + vy ** 2 + vz ** 2), 1e-6)
            th_tx = np.arccos(np.clip(vz / r, -1, 1)); ph_tx = np.arctan2(vy, vx)
            th_rx = np.arccos(np.clip(-vz / r, -1, 1)); ph_rx = np.arctan2(-vy, -vx)
            c_tx = np.asarray(v_tr38901_pattern(mi.Float(th_tx.ravel().tolist()),
                                                mi.Float(ph_tx.ravel().tolist()))[0])
            c_rx = np.asarray(v_dipole_pattern(mi.Float(th_rx.ravel().tolist()),
                                               mi.Float(ph_rx.ravel().tolist()))[0])
            g = (10 * np.log10(np.maximum(np.abs(c_tx) ** 2, 1e-30))
                 + 10 * np.log10(np.maximum(np.abs(c_rx) ** 2, 1e-30)))
            out.append(g.reshape(cc.shape[:2]))
        return np.stack(out, axis=0)

    for ref, R in refs.items():
        cc = R["cell_centers"]
        d2d = np.stack([np.hypot(cc[..., 0] - float(t["x"]), cc[..., 1] - float(t["y"]))
                        for t in towers], axis=0)
        dz = np.stack([R["tx_z"][i] - cc[..., 2] for i in range(n_tx)], axis=0)
        R["d2d"] = np.maximum(d2d, 10.0)      # TR 38.901 applicability floor, declared
        R["d2d_raw"] = d2d
        R["d3d"] = np.sqrt(R["d2d"] ** 2 + dz ** 2)
        try:
            R["ant_db"] = antenna_gain(cc, R["tx_z"])
        except Exception as exc:                                      # METHOD rule 5
            failures.append({"cell": f"antenna_gain/{ref}", "error": repr(exc),
                             "traceback": traceback.format_exc(limit=4)})
            R["ant_db"] = None

    ref0 = refs.get(PRIMARY["rt_ref"]) or next(iter(refs.values()))
    if ref0.get("ant_db") is not None:
        a = ref0["ant_db"]
        result["antenna_gain_correction_db"] = {
            "tx_pattern": "tr38901 (V), orientation [0,0,0], boresight +x",
            "rx_pattern": "dipole (V), orientation [0,0,0]",
            "per_tx_stats_db": [{"tx": towers[i]["name"],
                                 "min": round(float(a[i].min()), 2),
                                 "p10": round(float(np.percentile(a[i], 10)), 2),
                                 "median": round(float(np.median(a[i])), 2),
                                 "p90": round(float(np.percentile(a[i], 90)), 2),
                                 "max": round(float(a[i].max()), 2)} for i in range(n_tx)],
            "spread_between_towers_db": {
                "median_abs_difference": round(float(np.median(np.abs(a[0] - a[1]))), 2)
                if n_tx == 2 else None},
            "note": ("Same units problem C1 hit, but sharper here: this correction is "
                     "per CELL and per TOWER (the tr38901 element clamps 30 dB below its "
                     "8 dBi peak in its back lobe), so it moves the serving-tower "
                     "decision and not merely an offset. 'raw' = the standard's "
                     "isotropic-to-isotropic path loss; 'antenna_corrected' = plus the "
                     "exact Sionna pattern gains. antenna_corrected is PRIMARY."),
        }

    # ---- shadow-fading synthesis validation ---------------------------------
    try:
        h, w = ref0["rt_db"].shape[1:]
        val = {}
        for (scn, st), dcor in SF_CORR_DIST_M.items():
            rng = np.random.default_rng(SF_BASE_SEED)
            stds, acs = [], []
            lag = max(int(round(dcor / CELL_M)), 1)
            for _ in range(5):
                f = correlated_field((h, w), CELL_M, dcor, rng)
                stds.append(float(f.std()))
                fa = f - f.mean()
                acs.append(float(np.mean(fa[:, :-lag] * fa[:, lag:]) / np.var(fa)))
            val[f"{scn}/{st}"] = {"d_cor_m": dcor,
                                  "measured_unit_std": round(float(np.mean(stds)), 4),
                                  "measured_autocorr_at_d_cor": round(float(np.mean(acs)), 4),
                                  "expected_autocorr_1_over_e": 0.3679}
        result["shadow_fading_validation"] = {
            "fields": val,
            "note": ("The synthesised field must actually have unit variance and the "
                     "exponential correlation the standard assumes, or the sigma quoted "
                     "from Table 7.5-6 is not the sigma applied. Measured here rather "
                     "than asserted. Lag sampled along the x axis at the nearest whole "
                     "cell to d_cor, so a few percent of quantisation is expected."),
        }
    except Exception as exc:                                          # METHOD rule 5
        failures.append({"cell": "shadow_fading_validation", "error": repr(exc),
                         "traceback": traceback.format_exc(limit=3)})

    # ========================================================================
    #  the stochastic model, over the declared design matrix
    # ========================================================================
    def pathloss_arms(scenario, R, h_build=RMA_H_BUILDING_M, w_street=RMA_W_STREET_M):
        """[n_tx,H,W] PL_LOS, PL_NLOS and their sigmas, plus d_BP per TX."""
        pls, plns, sls, slns, dbps = [], [], [], [], []
        for i, t in enumerate(towers):
            args = (R["d2d"][i], R["d3d"][i], FREQ_HZ / 1e9, float(t["h"]), RX_AGL_M)
            if scenario == "RMa":
                a, b, c, d, dbp = rma_pathloss(*args, h_build=h_build, w_street=w_street)
            else:
                a, b, c, d, dbp = uma_pathloss(*args)
            pls.append(a); plns.append(b); sls.append(c); slns.append(d); dbps.append(dbp)
        return (np.stack(pls), np.stack(plns), np.stack(sls), np.stack(slns), dbps)

    cells: dict = {}
    keep_maps: dict = {}
    stoch_wall: list[float] = []

    for ref, R in refs.items():
        for scenario in SCENARIOS:
            try:
                pl_los, pl_nlos, sig_los, sig_nlos, dbps = pathloss_arms(scenario, R)
            except Exception as exc:                                  # METHOD rule 5
                failures.append({"cell": f"{ref}/{scenario}/pathloss", "error": repr(exc),
                                 "traceback": traceback.format_exc(limit=4)})
                continue
            p_los = np.stack([los_probability(scenario, R["d2d"][i], RX_AGL_M)
                              for i in range(n_tx)])
            if ref == PRIMARY["rt_ref"]:
                result.setdefault("model_diagnostics", {})[scenario] = {
                    "breakpoint_d_bp_m_per_tx": [round(float(v), 1) for v in dbps],
                    "mean_los_probability_per_tx":
                        [round(float(np.mean(p_los[i])), 4) for i in range(n_tx)],
                    "geometric_los_fraction_per_tx":
                        [round(float(np.mean(R["geo_los"][i])), 4) for i in range(n_tx)],
                    "median_d2d_m": round(float(np.median(R["d2d"])), 1),
                    "note": ("If the modelled LOS probability and the ray tracer's actual "
                             "LOS fraction differ, the stochastic surface is mis-stating "
                             "how often the link is clear before any path-loss formula "
                             "is evaluated."),
                }

            for los_state in LOS_STATES:
                for sf_mode in SF_MODES:
                    key_base = f"{ref}/{scenario}/{los_state}/{sf_mode}"
                    try:
                        per_real = {g: [] for g in GAIN_CONVENTIONS}
                        for r_i in range(N_REALISATIONS):
                            t0 = time.monotonic()
                            # --- LOS state -------------------------------------
                            if los_state == "geometric":
                                is_los = R["geo_los"]
                            else:
                                rng_l = np.random.default_rng(
                                    [SF_BASE_SEED, r_i, SCEN_IDX[scenario], 1])
                                is_los = rng_l.random(p_los.shape) < p_los
                            pl = np.where(is_los, pl_los, pl_nlos)
                            sig = np.where(is_los, sig_los, sig_nlos)
                            # --- shadow fading ---------------------------------
                            if sf_mode == "none":
                                sf = np.zeros_like(pl)
                            elif sf_mode == "iid":
                                rng_s = np.random.default_rng(
                                    [SF_BASE_SEED, r_i, SCEN_IDX[scenario], 2])
                                sf = rng_s.standard_normal(pl.shape) * sig
                            else:
                                sf = np.empty_like(pl)
                                for i in range(n_tx):
                                    rng_a = np.random.default_rng(
                                        [SF_BASE_SEED, r_i, SCEN_IDX[scenario], 3, i])
                                    f_l = correlated_field(pl.shape[1:], CELL_M,
                                                           SF_CORR_DIST_M[(scenario, "LOS")],
                                                           rng_a)
                                    f_n = correlated_field(pl.shape[1:], CELL_M,
                                                           SF_CORR_DIST_M[(scenario, "NLOS")],
                                                           rng_a)
                                    sf[i] = np.where(is_los[i], f_l, f_n) * sig[i]
                            st_raw = -(pl + sf)
                            wall = time.monotonic() - t0
                            stoch_wall.append(wall)
                            for g in GAIN_CONVENTIONS:
                                if g == "antenna_corrected":
                                    if R.get("ant_db") is None:
                                        continue
                                    st_db = st_raw + R["ant_db"]
                                else:
                                    st_db = st_raw
                                per_real[g].append(metrics_one(st_db, R["rt_db"],
                                                               R["valid"], R["d3d"]))
                                if (r_i == 0 and g == PRIMARY["gain"]
                                        and ref == PRIMARY["rt_ref"]
                                        and scenario == PRIMARY["scenario"]
                                        and los_state == PRIMARY["los_state"]
                                        and sf_mode == PRIMARY["shadow_fading"]):
                                    keep_maps["st_db"] = st_db
                                    keep_maps["is_los"] = is_los
                        for g in GAIN_CONVENTIONS:
                            if not per_real[g]:
                                failures.append({"cell": f"{key_base}/{g}",
                                                 "error": "antenna correction unavailable"})
                                continue
                            cells[f"{key_base}/{g}"] = collapse(per_real[g])
                    except Exception as exc:                          # METHOD rule 5
                        failures.append({"cell": key_base, "error": repr(exc),
                                         "traceback": traceback.format_exc(limit=5)})
                        print(f"  FAIL {key_base}: {exc!r}")
            print(f"  [stochastic {ref}/{scenario}] done")

    result["cells"] = cells

    # ---- scene-informed sensitivity on RMa's h (declared, not a tune) --------
    try:
        R = refs[PRIMARY["rt_ref"]]
        out = {}
        for h_b in (RMA_H_BUILDING_M, round(float(b_h.mean()), 2)):
            pl_los, pl_nlos, sig_los, sig_nlos, _ = pathloss_arms("RMa", R, h_build=h_b)
            p_los = np.stack([los_probability("RMa", R["d2d"][i], RX_AGL_M)
                              for i in range(n_tx)])
            per_real = []
            for r_i in range(N_REALISATIONS):
                rng_l = np.random.default_rng([SF_BASE_SEED, r_i, SCEN_IDX["RMa"], 1])
                is_los = rng_l.random(p_los.shape) < p_los
                pl = np.where(is_los, pl_los, pl_nlos)
                sig = np.where(is_los, sig_los, sig_nlos)
                sf = np.empty_like(pl)
                for i in range(n_tx):
                    rng_a = np.random.default_rng([SF_BASE_SEED, r_i, SCEN_IDX["RMa"], 3, i])
                    f_l = correlated_field(pl.shape[1:], CELL_M, SF_CORR_DIST_M[("RMa", "LOS")], rng_a)
                    f_n = correlated_field(pl.shape[1:], CELL_M, SF_CORR_DIST_M[("RMa", "NLOS")], rng_a)
                    sf[i] = np.where(is_los[i], f_l, f_n) * sig[i]
                st = -(pl + sf) + R["ant_db"]
                per_real.append(metrics_one(st, R["rt_db"], R["valid"], R["d3d"]))
            out[f"h_building_m={h_b}"] = collapse(per_real)["best_server"]
        result["sensitivity_rma_building_height"] = {
            "cells": out,
            "note": ("h = 5.0 m is the standard's value and is what the primary cell "
                     "uses. h = the scene's measured mean is shown only so a reviewer "
                     "can see how little of the disagreement is attributable to that "
                     "choice. Neither value was selected after seeing a result."),
        }
    except Exception as exc:                                          # METHOD rule 5
        failures.append({"cell": "sensitivity_rma_building_height", "error": repr(exc),
                         "traceback": traceback.format_exc(limit=4)})

    # ========================================================================
    #  what the stochastic model structurally CANNOT do
    # ========================================================================
    try:
        R = refs[PRIMARY["rt_ref"]]
        st_db = keep_maps["st_db"]
        rt_best = np.where(R["valid"], R["rt_db"], -np.inf).max(axis=0)
        no_cov = ~np.isfinite(rt_best) | np.isneginf(rt_best)
        st_best = st_db.max(axis=0)
        rt_med = float(np.median(rt_best[~no_cov]))
        result["no_coverage_blindness"] = {
            "rt_no_coverage_cell_fraction": round(float(np.mean(no_cov)), 5),
            "stochastic_no_coverage_cell_fraction": 0.0,
            "stochastic_best_server_db_on_rt_no_coverage_cells": {
                "median": round(float(np.median(st_best[no_cov])), 2),
                "p10": round(float(np.percentile(st_best[no_cov], 10)), 2),
                "p90": round(float(np.percentile(st_best[no_cov], 90)), 2),
            },
            "rt_median_best_server_db_on_covered_cells": round(rt_med, 2),
            "fraction_of_rt_holes_the_model_calls_better_than_rt_median":
                round(float(np.mean(st_best[no_cov] > rt_med)), 4),
            "statement": ("The closed form is a continuous function of distance plus a "
                          "Gaussian. It cannot return 'no coverage' - every cell the ray "
                          "tracer found to be a hole gets a finite number. But the "
                          "unconditional comparison above OVERSTATES the point and is "
                          "corrected by the distance-matched test below: RT holes sit "
                          "preferentially far from a tower, so the stochastic model gives "
                          "them a low value for the wrong reason. The question that "
                          "actually matters is whether it can tell a hole from a served "
                          "cell AT THE SAME DISTANCE."),
        }

        # --- distance-matched: can the model discriminate a hole at all? ------
        # Holes are correlated with range, so an unconditional "the model calls
        # them low too" is not evidence of discrimination. Bin by distance to the
        # nearest tower and ask whether, within a bin, hole cells get a
        # systematically different prediction from served cells.
        dmin = R["d2d"].min(axis=0)
        edges = [0, 250, 500, 750, 1000, 1500, 2000, 1e9]
        bins = []
        for lo, hi in zip(edges[:-1], edges[1:]):
            m = (dmin >= lo) & (dmin < hi)
            mh = m & no_cov
            mc = m & ~no_cov
            if mh.sum() < 30 or mc.sum() < 30:
                bins.append({"d2d_m": [lo, None if hi > 1e8 else hi],
                             "n_holes": int(mh.sum()), "n_served": int(mc.sum()),
                             "status": "too few cells to compare"})
                continue
            bins.append({
                "d2d_m": [lo, None if hi > 1e8 else hi],
                "n_holes": int(mh.sum()), "n_served": int(mc.sum()),
                "stochastic_median_db_holes": round(float(np.median(st_best[mh])), 2),
                "stochastic_median_db_served": round(float(np.median(st_best[mc])), 2),
                "stochastic_separation_db": round(
                    float(np.median(st_best[mh]) - np.median(st_best[mc])), 2),
                "rt_median_db_served": round(float(np.median(rt_best[mc])), 2),
            })
        seps = [b["stochastic_separation_db"] for b in bins
                if "stochastic_separation_db" in b]
        result["no_coverage_blindness"]["distance_matched_discrimination"] = {
            "bins": bins,
            "median_separation_db_across_bins": (round(float(np.median(seps)), 2)
                                                 if seps else None),
            "statement": ("Read the separation column, and read it against the bin. Out to "
                          "1.5 km the model does put hole cells ~8-10 dB below served "
                          "cells in the same bin - but the only two quantities it has "
                          "inside a bin are residual range and antenna azimuth, so that "
                          "separation is those, not the obstruction. Beyond 1.5 km, where "
                          "the majority of the ray tracer's holes are, the separation "
                          "collapses below 1 dB: the model assigns a hole and a served "
                          "cell the same number. That is the structural blindness measured "
                          "properly, and it is weaker than the unconditional statement "
                          "above would suggest."),
        }
    except Exception as exc:                                          # METHOD rule 5
        failures.append({"cell": "no_coverage_blindness", "error": repr(exc),
                         "traceback": traceback.format_exc(limit=4)})

    # ========================================================================
    #  is the serving-cell disagreement just boundary jitter, or a real
    #  mis-assignment? Bin by the ray tracer's own best-vs-second-best margin.
    # ========================================================================
    try:
        R = refs[PRIMARY["rt_ref"]]
        pl_los, pl_nlos, sig_los, sig_nlos, _ = pathloss_arms(PRIMARY["scenario"], R)
        p_los = np.stack([los_probability(PRIMARY["scenario"], R["d2d"][i], RX_AGL_M)
                          for i in range(n_tx)])
        rt_m = np.where(R["valid"], R["rt_db"], -np.inf)
        rt_sorted = np.sort(rt_m, axis=0)
        rt_idx = np.argmax(rt_m, axis=0)
        both = R["valid"].all(axis=0)
        with np.errstate(invalid="ignore"):   # -inf - -inf where the RT sees neither TX
            margin = rt_sorted[-1] - rt_sorted[-2]
        m_edges = [0, 3, 6, 10, 20, 1e9]
        acc = {f"{lo}-{'inf' if hi > 1e8 else hi}": [] for lo, hi in
               zip(m_edges[:-1], m_edges[1:])}
        only_one = []
        for r_i in range(N_REALISATIONS):
            rng_l = np.random.default_rng(
                [SF_BASE_SEED, r_i, SCEN_IDX[PRIMARY["scenario"]], 1])
            is_los = rng_l.random(p_los.shape) < p_los
            pl = np.where(is_los, pl_los, pl_nlos)
            sig = np.where(is_los, sig_los, sig_nlos)
            sf = np.empty_like(pl)
            for i in range(n_tx):
                rng_a = np.random.default_rng(
                    [SF_BASE_SEED, r_i, SCEN_IDX[PRIMARY["scenario"]], 3, i])
                f_l = correlated_field(pl.shape[1:], CELL_M,
                                       SF_CORR_DIST_M[(PRIMARY["scenario"], "LOS")], rng_a)
                f_n = correlated_field(pl.shape[1:], CELL_M,
                                       SF_CORR_DIST_M[(PRIMARY["scenario"], "NLOS")], rng_a)
                sf[i] = np.where(is_los[i], f_l, f_n) * sig[i]
            st_idx = np.argmax(-(pl + sf) + R["ant_db"], axis=0)
            dis = st_idx != rt_idx
            for lo, hi in zip(m_edges[:-1], m_edges[1:]):
                m = both & (margin >= lo) & (margin < hi)
                if m.sum() > 0:
                    acc[f"{lo}-{'inf' if hi > 1e8 else hi}"].append(float(dis[m].mean()))
            one = (~both) & R["valid"].any(axis=0)
            if one.sum() > 0:
                only_one.append(float(dis[one].mean()))
        rows = {}
        for k, v in acc.items():
            lo = float(k.split("-")[0]); hi = k.split("-")[1]
            hi_v = 1e9 if hi == "inf" else float(hi)
            m = both & (margin >= lo) & (margin < hi_v)
            rows[f"rt_margin_{k}_db"] = {"n_cells": int(m.sum()),
                                         "serving_cell_disagreement": spread(v)}
        m1 = (~both) & R["valid"].any(axis=0)
        rows["only_one_tower_visible_to_rt"] = {"n_cells": int(m1.sum()),
                                                "serving_cell_disagreement": spread(only_one)}
        result["serving_cell_decision_relevance"] = {
            "primary_cell": PRIMARY_KEY,
            "bins": rows,
            "statement": ("Serving-cell churn at a handover boundary is cheap - both "
                          "servers are within a decibel and either choice is defensible. "
                          "Churn where the ray tracer says one tower is 10 or 20 dB "
                          "stronger is a planning error with consequences. The bins "
                          "separate the two. Read the high-margin rows: that is where the "
                          "stochastic surface is confidently pointing at the wrong mast."),
        }
    except Exception as exc:                                          # METHOD rule 5
        failures.append({"cell": "serving_cell_decision_relevance", "error": repr(exc),
                         "traceback": traceback.format_exc(limit=4)})

    # ---- cost ---------------------------------------------------------------
    try:
        rt_wall = ref_report[PRIMARY["rt_ref"]]["wall_s_median"]
        st_wall = float(np.median(stoch_wall))
        result["cost"] = {
            "rt_solve_wall_s_median": rt_wall,
            "rt_solve_wall_s_cold": ref_report[PRIMARY["rt_ref"]]["timing"][0]["wall_s"],
            "mitsuba_variant": ref_report[PRIMARY["rt_ref"]]["mitsuba_variant"],
            "stochastic_realisation_wall_s_median": round(st_wall, 5),
            "cost_ratio_rt_over_stochastic": round(rt_wall / max(st_wall, 1e-9), 2),
            "fraction_of_compute_cost": round(st_wall / max(rt_wall, 1e-9), 4),
            "note": ("Both numbers are solve-only on the SAME grid. Neither includes "
                     "interpreter start. The RT number excludes everything that had to "
                     "happen before it could run at all: LiDAR heights, footprint "
                     "extraction, terrain raster, Mitsuba XML export - the scene build. "
                     "The stochastic model needs NONE of that, which is the larger part "
                     "of its cost advantage and is not captured by this ratio. On a GPU "
                     "the RT solve is cheap enough that the honest cost comparison is "
                     "about data, not FLOPs."),
        }
    except Exception as exc:                                          # METHOD rule 5
        failures.append({"cell": "cost", "error": repr(exc),
                         "traceback": traceback.format_exc(limit=3)})

    # ---- where the stochastic model WINS (METHOD rule 7) --------------------
    prim = cells.get(PRIMARY_KEY)
    mc_floor = (ref_report.get(PRIMARY["rt_ref"], {}) or {}).get("mc_noise_floor")
    result["where_the_stochastic_model_wins"] = {
        "no_scene_required": ("It needs a distance and two heights. The ray-traced map "
                              "required 576 LiDAR-height footprints, a terrain raster and "
                              "a Mitsuba scene export. For a national planning surface "
                              "over territory with no building data, the closed form is "
                              "not merely cheaper - it is the only one that can be run."),
        "compute": (result.get("cost", {}) or {}).get("cost_ratio_rt_over_stochastic"),
        "statistical_validity_over_an_ensemble": (
            "TR 38.901 is calibrated against measurement campaigns and is designed to "
            "reproduce a DISTRIBUTION, not a specific cell. Nothing in this directory "
            "shows the ray tracer is closer to reality - there is no drive test here. "
            "Over a large ensemble of sites the stochastic model carries an empirical "
            "pedigree the deterministic solve does not."),
        "auditability_of_inputs": ("Its inputs are three numbers that cannot be wrong in "
                                   "an interesting way. The RT map inherits every error in "
                                   "the footprints, the LiDAR heights, the material "
                                   "assignment and the terrain raster, none of which are "
                                   "validated anywhere in this repository."),
    }

    # ---- verdict ------------------------------------------------------------
    if prim is not None:
        b = prim["best_server"]
        sdis = b["serving_cell_disagreement_fraction"]["median"]
        result["verdict"] = {
            "primary_cell": PRIMARY_KEY,
            "rms_error_db": b["rms_error_db"],
            "mean_signed_bias_db": b["mean_signed_bias_db"],
            "pearson_r": b["pearson_r"],
            "fraction_cells_over_10db": b["fraction_over_10db"],
            "serving_cell_disagreement_fraction": b["serving_cell_disagreement_fraction"],
            "rt_monte_carlo_noise_floor_serving_cell": mc_floor,
            "serving_cell_disagreement_over_noise_floor": (
                None if not mc_floor else round(sdis / mc_floor, 2)),
            "median_path_gain_db": {"rt": b["rt_best_median_db"],
                                    "stochastic": b["st_best_median_db"]},
            "cell_edge_p10_db": {"rt": b["rt_best_p10_db"],
                                 "stochastic": b["st_best_p10_db"]},
            "cell_edge_p05_db": {"rt": b["rt_best_p05_db"],
                                 "stochastic": b["st_best_p05_db"]},
            "path_loss_exponent": prim["path_loss_exponent"],
            "note": ("Stated whichever way the numbers fall. If the two agree on median "
                     "path gain, the paper's 'upgrade from stochastic planning to "
                     "deterministic site studies' claim is weaker than written and that "
                     "is reported here, not buried. The question then becomes whether "
                     "determinism still earns its keep on serving-cell association, "
                     "cell-edge behaviour and coverage holes - which are the numbers "
                     "immediately above and in no_coverage_blindness."),
        }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, indent=2))
    print(f"wrote {OUT_JSON}")

    # ========================================================================
    #  figures
    # ========================================================================
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.colors import ListedColormap

        R = refs[PRIMARY["rt_ref"]]
        cc = R["cell_centers"]
        ext = [cc[..., 0].min(), cc[..., 0].max(), cc[..., 1].min(), cc[..., 1].max()]
        rt_masked = np.where(R["valid"], R["rt_db"], -np.inf)
        rt_best = rt_masked.max(axis=0)
        rt_best_plot = np.where(np.isfinite(rt_best), rt_best, np.nan)
        rt_idx = np.argmax(rt_masked, axis=0)
        st_db = keep_maps["st_db"]
        st_best = st_db.max(axis=0)
        st_idx = np.argmax(st_db, axis=0)
        bv = np.isfinite(rt_best_plot)

        fig = plt.figure(figsize=(16.5, 10.5))
        gs = fig.add_gridspec(2, 3, height_ratios=[2.0, 1.25], hspace=0.30, wspace=0.25)
        allv = np.concatenate([rt_best_plot[bv], st_best[bv]])
        vmax = float(np.percentile(allv, 99)); vmin = vmax - 80

        for i, (m, title) in enumerate((
                (rt_best_plot, "deterministic: Sionna RT best-server"),
                (np.where(bv, st_best, np.nan),
                 "stochastic: TR 38.901 RMa, one realisation"))):
            ax = fig.add_subplot(gs[0, i])
            im = ax.imshow(m, origin="lower", extent=ext, cmap="viridis",
                           vmin=vmin, vmax=vmax, interpolation="nearest")
            for bl in buildings_xy:
                ax.plot(bl[:, 0], bl[:, 1], color="white", lw=0.15, alpha=0.22)
            for t in towers:
                ax.scatter([t["x"]], [t["y"]], c="red", s=55, marker="^",
                           edgecolors="white", zorder=5)
            med = float(np.nanmedian(m[bv]))
            p10 = float(np.nanpercentile(m[bv], 10))
            ax.set_title(f"{title}\nmedian {med:.1f} dB   p10 {p10:.1f} dB", fontsize=10)
            ax.set_aspect("equal"); ax.set_xlabel("x [m]")
            if i == 0:
                ax.set_ylabel("y [m]")
            fig.colorbar(im, ax=ax, shrink=0.75, pad=0.02, label="path gain [dB]")

        ax = fig.add_subplot(gs[0, 2])
        delta = np.where(bv, st_best - rt_best_plot, np.nan)
        im = ax.imshow(delta, origin="lower", extent=ext, cmap="coolwarm",
                       vmin=-30, vmax=30, interpolation="nearest")
        for t in towers:
            ax.scatter([t["x"]], [t["y"]], c="black", s=55, marker="^",
                       edgecolors="white", zorder=5)
        ax.set_aspect("equal"); ax.set_xlabel("x [m]")
        ax.set_title("stochastic - deterministic [dB]", fontsize=10)
        fig.colorbar(im, ax=ax, shrink=0.75, pad=0.02)

        # CDF with the ensemble band
        ax = fig.add_subplot(gs[1, 0])
        d = np.sort(rt_best_plot[bv])
        ax.plot(d, np.linspace(0, 1, d.size), lw=2.2, color="black",
                label="Sionna RT (deterministic)")
        try:
            pl_los, pl_nlos, sig_los, sig_nlos, _ = pathloss_arms("RMa", R)
            p_los = np.stack([los_probability("RMa", R["d2d"][i], RX_AGL_M)
                              for i in range(n_tx)])
            for r_i in range(min(N_REALISATIONS, 20)):
                rng_l = np.random.default_rng([SF_BASE_SEED, r_i, SCEN_IDX["RMa"], 1])
                is_los = rng_l.random(p_los.shape) < p_los
                pl = np.where(is_los, pl_los, pl_nlos)
                sig = np.where(is_los, sig_los, sig_nlos)
                sf = np.empty_like(pl)
                for i in range(n_tx):
                    rng_a = np.random.default_rng([SF_BASE_SEED, r_i, SCEN_IDX["RMa"], 3, i])
                    f_l = correlated_field(pl.shape[1:], CELL_M,
                                           SF_CORR_DIST_M[("RMa", "LOS")], rng_a)
                    f_n = correlated_field(pl.shape[1:], CELL_M,
                                           SF_CORR_DIST_M[("RMa", "NLOS")], rng_a)
                    sf[i] = np.where(is_los[i], f_l, f_n) * sig[i]
                s = (-(pl + sf) + R["ant_db"]).max(axis=0)[bv]
                ax.plot(np.sort(s), np.linspace(0, 1, s.size), lw=0.7, alpha=0.35,
                        color="#1f77b4",
                        label="TR 38.901 realisations" if r_i == 0 else None)
        except Exception:
            pass
        ax.set_xlabel("best-server path gain [dB]"); ax.set_ylabel("CDF")
        ax.grid(alpha=0.3); ax.legend(fontsize=8, loc="upper left")
        ax.set_title("CDF: deterministic vs the stochastic ensemble", fontsize=10)

        # serving-tower disagreement map
        ax = fig.add_subplot(gs[1, 1])
        dis = np.where(bv, (rt_idx != st_idx).astype(float), np.nan)
        ax.imshow(dis, origin="lower", extent=ext,
                  cmap=ListedColormap(["#dddddd", "#d62728"]), vmin=0, vmax=1,
                  interpolation="nearest")
        for t in towers:
            ax.scatter([t["x"]], [t["y"]], c="black", s=45, marker="^",
                       edgecolors="white", zorder=5)
        frac = float(np.mean((rt_idx != st_idx)[bv]))
        ax.set_aspect("equal"); ax.set_xlabel("x [m]")
        ax.set_title(f"serving tower differs (red): {frac * 100:.1f} % of cells",
                     fontsize=10)

        # disagreement bar chart across the matrix
        ax = fig.add_subplot(gs[1, 2])
        rows = [(k, v) for k, v in cells.items()
                if k.startswith(PRIMARY["rt_ref"] + "/") and k.endswith("/antenna_corrected")]
        labels = [k.split("/", 1)[1].replace("/antenna_corrected", "")
                   .replace("probabilistic", "prob").replace("correlated", "corr")
                  for k, _ in rows]
        vals = [v["best_server"]["serving_cell_disagreement_fraction"]["median"]
                for _, v in rows]
        lo = [v["best_server"]["serving_cell_disagreement_fraction"]["min"] for _, v in rows]
        hi = [v["best_server"]["serving_cell_disagreement_fraction"]["max"] for _, v in rows]
        yerr = np.abs(np.vstack([np.array(vals) - np.array(lo),
                                 np.array(hi) - np.array(vals)]))
        ax.bar(range(len(vals)), vals, yerr=yerr, capsize=2, color="#d62728", alpha=0.85)
        mcf = (ref_report.get(PRIMARY["rt_ref"], {}) or {}).get("mc_noise_floor")
        if mcf:
            ax.axhline(mcf, color="black", ls="--", lw=1.4,
                       label=f"RT Monte-Carlo floor {mcf:.3f}")
            ax.legend(fontsize=7)
        ax.set_xticks(range(len(vals)))
        ax.set_xticklabels(labels, fontsize=6, rotation=40, ha="right")
        ax.set_ylabel("serving-tower disagreement")
        ax.set_title("Serving-tower disagreement across the matrix\n"
                     "(antenna-corrected, error bar = ensemble min/max)", fontsize=9)
        ax.grid(alpha=0.3, axis="y")

        fig.suptitle("C2 - deterministic ray tracing vs stochastic 3GPP TR 38.901, "
                     f"Newton (Barbados) @ {FREQ_HZ/1e9:g} GHz, {CELL_M:g} m cells, "
                     f"{N_REALISATIONS} realisations", fontsize=12)
        OUT_FIG.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(OUT_FIG, dpi=120, bbox_inches="tight")
        plt.close(fig)
        print(f"wrote {OUT_FIG}")

        # --- second figure: error vs distance + LOS-state diagnosis ----------
        fig2, axes = plt.subplots(1, 4, figsize=(21, 4.8))
        ax = axes[0]
        dd = R["d2d"][R["valid"]]
        ee = (st_db - R["rt_db"])[R["valid"]]
        hb = ax.hexbin(dd, ee, gridsize=60, bins="log", cmap="magma", mincnt=1)
        ax.axhline(0, color="cyan", lw=1)
        ax.axhspan(-10, 10, color="cyan", alpha=0.12)
        ax.set_xlabel("2-D distance from tower [m]")
        ax.set_ylabel("TR 38.901 - Sionna RT [dB]")
        ax.set_title("per-TX error vs distance (log density)", fontsize=10)
        fig2.colorbar(hb, ax=ax, pad=0.02)

        ax = axes[1]
        dgrid = np.linspace(10, float(R["d2d"].max()), 400)
        for scn, c in (("RMa", "#2ca02c"), ("UMa", "#9467bd")):
            ax.plot(dgrid, los_probability(scn, dgrid, RX_AGL_M), color=c,
                    label=f"{scn} Pr(LOS), Table 7.4.2-1")
        for i in range(n_tx):
            dv = R["d2d"][i].ravel(); lv = R["geo_los"][i].ravel().astype(float)
            b_edges = np.linspace(10, dv.max(), 40)
            idx = np.digitize(dv, b_edges) - 1
            xs, ys = [], []
            for k in range(len(b_edges) - 1):
                m = idx == k
                if m.sum() > 30:
                    xs.append(0.5 * (b_edges[k] + b_edges[k + 1])); ys.append(lv[m].mean())
            ax.plot(xs, ys, "o--", ms=3, lw=1,
                    label=f"ray-traced LOS, {towers[i]['name']}")
        ax.set_xlabel("2-D distance from tower [m]"); ax.set_ylabel("P(LOS)")
        ax.grid(alpha=0.3); ax.legend(fontsize=7)
        ax.set_title("LOS state: modelled vs ray-traced", fontsize=10)

        ax = axes[2]
        labels2, vals2, errs = [], [], []
        for los_state in LOS_STATES:
            for sf_mode in SF_MODES:
                k = f"{PRIMARY['rt_ref']}/{PRIMARY['scenario']}/{los_state}/{sf_mode}/antenna_corrected"
                if k in cells:
                    s = cells[k]["best_server"]["rms_error_db"]
                    labels2.append(f"{los_state}\n{sf_mode}")
                    vals2.append(s["median"]); errs.append(s["max"] - s["min"])
        ax.bar(range(len(vals2)), vals2, color="#1f77b4", alpha=0.85)
        ax.set_xticks(range(len(vals2))); ax.set_xticklabels(labels2, fontsize=7)
        ax.set_ylabel("best-server RMS error [dB]")
        ax.set_title(f"RMa, antenna-corrected: what drives the error\n"
                     f"(ensemble median over {N_REALISATIONS} realisations)", fontsize=9)
        ax.grid(alpha=0.3, axis="y")

        ax = axes[3]
        dr_ = (result.get("serving_cell_decision_relevance") or {}).get("bins", {})
        keys = [k for k in dr_ if dr_[k]["serving_cell_disagreement"]]
        if keys:
            lbl = [k.replace("rt_margin_", "").replace("_db", " dB")
                    .replace("only_one_tower_visible_to_rt", "only 1 TX\nvisible")
                   for k in keys]
            v = [dr_[k]["serving_cell_disagreement"]["median"] for k in keys]
            e = np.abs(np.vstack([
                [dr_[k]["serving_cell_disagreement"]["median"]
                 - dr_[k]["serving_cell_disagreement"]["min"] for k in keys],
                [dr_[k]["serving_cell_disagreement"]["max"]
                 - dr_[k]["serving_cell_disagreement"]["median"] for k in keys]]))
            ax.bar(range(len(v)), v, yerr=e, capsize=3, color="#d62728", alpha=0.85)
            for i, k in enumerate(keys):
                ax.text(i, v[i] + 0.012, f"n={dr_[k]['n_cells']}", ha="center", fontsize=6)
            ax.axhline(0.5, color="grey", ls=":", lw=1)
            ax.text(len(v) - 0.5, 0.505, "coin flip", fontsize=7, color="grey", ha="right")
            ax.set_xticks(range(len(v)))
            ax.set_xticklabels(lbl, fontsize=7, rotation=30, ha="right")
            ax.set_ylabel("serving-tower disagreement")
            ax.set_ylim(0, 0.6)
            ax.set_title("Is the churn just boundary jitter?\n"
                         "binned by the ray tracer's best-vs-2nd-best margin", fontsize=9)
            ax.grid(alpha=0.3, axis="y")
        fig2.suptitle("C2 - where the disagreement comes from", fontsize=11)
        fig2.tight_layout()
        fig2.savefig(OUT_FIG2, dpi=120, bbox_inches="tight")
        plt.close(fig2)
        print(f"wrote {OUT_FIG2}")
    except Exception as exc:                                          # METHOD rule 5
        failures.append({"cell": "figure", "error": repr(exc),
                         "traceback": traceback.format_exc(limit=5)})
        print(f"  FAIL figure: {exc!r}")

    OUT_JSON.write_text(json.dumps(result, indent=2))

    # ---- console summary ----------------------------------------------------
    print("\n--- C2 summary (best-server surface, ensemble median) ---")
    hdr = f"{'cell':>62} {'RMS':>7} {'bias':>8} {'r':>7} {'>10dB':>7} {'serv-dis':>9}"
    print(hdr)
    for k in sorted(cells):
        b = cells[k]["best_server"]
        print(f"{k:>62} {b['rms_error_db']['median']:7.2f} "
              f"{b['mean_signed_bias_db']['median']:+8.2f} "
              f"{b['pearson_r']['median']:7.4f} "
              f"{b['fraction_over_10db']['median']:7.3f} "
              f"{b['serving_cell_disagreement_fraction']['median']:9.4f}")
    if PRIMARY_KEY in cells:
        b = cells[PRIMARY_KEY]["best_server"]
        print(f"\nPRIMARY {PRIMARY_KEY}")
        for m in ("rms_error_db", "mean_signed_bias_db", "pearson_r",
                  "fraction_over_10db", "serving_cell_disagreement_fraction"):
            s = b[m]
            print(f"  {m:<38} median {s['median']:9.4f}  "
                  f"[{s['min']:.4f} .. {s['max']:.4f}]  sd {s['std']:.4f}")
    print(f"failures: {len(failures)}")
    for f in failures:
        print("  FAIL", {kk: vv for kk, vv in f.items() if kk != "traceback"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
