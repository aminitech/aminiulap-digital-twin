#!/usr/bin/env python3
"""
sionna_coverage.py -- load the exported Barbados/Newton scene in Sionna RT 2.0.1
and compute a radio coverage map from the real cell towers.

Run in the sionna conda env:
    /opt/anaconda3/envs/sionna/bin/python sionna_coverage.py

Runs on CPU (Mitsuba LLVM backend) -- no CUDA needed, just slower.

Defect F9 (fixed here)
----------------------
``coverage_pathgain_db_terrain.png`` and
``coverage_pathgain_db_terrain_groundfollow.png`` are placed side by side in the
paper with a caption inviting comparison, but each stage used to compute its own
``vmax = p99(own data)``, so the same hue meant different dB in the two figures.
Both now resolve their colour limits through ``resolve_pathgain_scale()``
against a shared scale recorded in ``sionna_out/pathgain_scale.json``, and each
figure states the scale it is on. The 80 dB dynamic-range convention is
unchanged; only the anchor is shared. The first figure in the group sets it and
the rest adopt it, so a single pipeline pass is enough. Override with
``ULAP_PG_VMIN`` / ``ULAP_PG_VMAX``.

Defects F10 / F11 (fixed here, 2026-07-30)
------------------------------------------
F9 harmonised the *colour* of the two compared figures. It did not harmonise the
*grid*: this stage shipped 5 m cells and ``sionna_terrain_ground.py`` shipped
8 m, so the paper placed two maps of different spatial resolution side by side.
Both stages now read one cell size, ``ULAP_RM_CELL_M`` (default **8 m**), and one
sample count, ``ULAP_RM_SAMPLES_PER_TX`` (default **1e8**, raised from 1e7).

Why 8 m rather than 5 m -- measured on this scene, K=57-plane ground-following
stack, GB10 (``cuda_ad_mono_polarized``):

    cells   samples/tx   plane map blank   gf map blank   gf stack solve
    8 m     1e7             6.99 %           10.99 %          1.02 s
    8 m     1e8             0.13 %            1.16 %          7.20 s
    5 m     1e7            18.92 %           22.12 %          7.25 s
    5 m     1e8             1.36 %            3.54 %         13.66 s

At 5 m the estimator fills 2.56x more cells from the same rays, so the finer grid
costs ~3x the blank-cell artefact and ~1.9x the GPU solve. The full argument, and
the building-footprint and DTM-posting numbers behind it, are in the F11 note in
``sionna_terrain_ground.py`` and in
``docs/audits/2026-07-30-sampling-and-resolution.md``.

**What this stage LOST:** ``coverage_pathgain_db.png`` and
``coverage_pathgain_db_terrain.png`` were 5 m maps and are now 8 m. That is a
real reduction in published spatial resolution and is recorded as the price of
making the two compared figures like-for-like.

**What it GAINED, and nobody had measured:** at the old 5 m / 1e7 defaults the
terrain plane map -- the figure the paper compares *against* -- was itself
**18.92 % unsampled**. At 8 m / 1e8 it is 0.13 %. The stage now prints its own
no-coverage fraction so this can never go unnoticed again.
"""
import os, sys, time
os.environ.setdefault("DRJIT_NO_RTLD_DEEPBIND", "1")

# ── Backend contract ─────────────────────────────────────────────────────────────
# Sionna selects the CUDA variant FIRST when none is set (sionna/rt/__init__.py:
#   mi.set_variant("cuda_ad_mono_polarized", "llvm_ad_mono_polarized")
# ), so on any machine with a visible GPU a nominally-CPU run silently executes on
# the GPU. Its guard is `if mi.variant() is None` — meaning a variant pinned BEFORE
# sionna imports is respected. So: pin it here from MI_DEFAULT_VARIANT, loudly. An
# unavailable variant raises instead of falling back; a post-import mismatch aborts
# rather than letting the wrong backend masquerade as the one requested.
_WANT_VARIANT = os.environ.get("MI_DEFAULT_VARIANT")
if _WANT_VARIANT:
    import mitsuba as _mi_pin
    try:
        _mi_pin.set_variant(_WANT_VARIANT)
    except (ImportError, AttributeError, RuntimeError) as _e:
        raise SystemExit(
            f"requested backend {_WANT_VARIANT!r} is not available on this host: {_e}\n"
            "refusing to fall back silently -- fix the environment "
            "(e.g. DRJIT_LIBLLVM_PATH for the LLVM backend) or unset MI_DEFAULT_VARIANT.")

import numpy as np
import mitsuba as mi
import sionna.rt as rt

if _WANT_VARIANT:
    import mitsuba as _mi_chk
    if _mi_chk.variant() != _WANT_VARIANT:
        raise SystemExit(f"backend mismatch: requested {_WANT_VARIANT!r} but the solver "
                         f"selected {_mi_chk.variant()!r}; refusing to report results for the wrong backend")
from sionna.rt import (load_scene, PlanarArray, Transmitter, Receiver,
                       Camera, RadioMapSolver, PathSolver)

HERE = os.environ.get("ULAP_WORK_DIR") or os.path.dirname(os.path.abspath(__file__))
# argv: [mode] [scene.xml]   mode = "flat" (default) | "terrain"
MODE   = sys.argv[1] if len(sys.argv) > 1 else "flat"
TERRAIN = (MODE == "terrain")
SCENE  = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
    HERE, "mitsuba_scene_terrain" if TERRAIN else "mitsuba_scene", "scene.xml")
OUTDIR = os.path.join(HERE, "sionna_out")
os.makedirs(OUTDIR, exist_ok=True)
SUF = "_terrain" if TERRAIN else ""

# ---- F11 / F10: grid and sample count shared with sionna_terrain_ground.py ---
# The paper prints coverage_pathgain_db_terrain.png beside
# coverage_pathgain_db_terrain_groundfollow.png. Both stages read these two
# variables, so the two figures cannot drift onto different grids or different
# estimator noise levels again. Rationale and the measurements behind the
# defaults are in this module's docstring.
CELL_M = float(os.environ.get("ULAP_RM_CELL_M", 8.0))
SAMPLES_PER_TX = int(float(os.environ.get("ULAP_RM_SAMPLES_PER_TX", 10**8)))

# building footprints + terrain for overlay / tower heights
import json

# ---- F9: one colour scale shared across the figures the paper compares ------
# NOTE: this helper is duplicated verbatim in sionna_terrain_ground.py. The two
# stages run in separate processes from separate files and ulap_scope.stages
# carries no shared runtime module, so the scale contract lives in the JSON
# sidecar, not in an import. Keep the two copies identical.
SCALE_FILE = os.path.join(OUTDIR, "pathgain_scale.json")


def resolve_pathgain_scale(pg_db, group, figure, dyn_range=80.0, quantum=5.0):
    """Colour limits shared by every figure tagged with the same ``group``.

    The FIRST figure in a group sets the scale: its anchor is the 99th percentile
    of its own finite path gain rounded UP to a ``quantum`` dB grid, and
    ``vmin = vmax - dyn_range`` keeps the existing 80 dB dynamic-range convention
    untouched. The value is stored per group in
    ``sionna_out/pathgain_scale.json``; every later figure in the group ADOPTS it
    unchanged, so one pipeline pass produces hue-comparable figures with no
    re-render. Where a later map's own p99 exceeds the shared vmax, the top of
    that map saturates -- the saturated fraction is measured, printed, and
    written into the colorbar label rather than hidden. Delete the JSON to
    rescale a group. Explicit override: ``ULAP_PG_VMAX`` / ``ULAP_PG_VMIN`` (dB).

    Returns ``(vmin, vmax, colorbar_label)``.
    """
    import numpy as _np
    env_vmax = os.environ.get("ULAP_PG_VMAX")
    env_vmin = os.environ.get("ULAP_PG_VMIN")
    finite = pg_db[_np.isfinite(pg_db)]
    own_p99 = float(_np.percentile(finite, 99)) if finite.size else 0.0
    anchor = float(_np.ceil(own_p99 / quantum) * quantum)

    try:
        with open(SCALE_FILE) as fh:
            state = json.load(fh)
    except Exception:
        state = {}
    g = state.get(group) or {}
    if g.get("vmax") is None:
        vmax = anchor
        src = f"shared '{group}' scale, set by this figure"
    else:
        # FIRST WRITER WINS. Adopting the stored value -- even when it is below
        # this map's own p99 -- is what makes the figures hue-comparable in a
        # single pipeline pass. The cost is saturation at the top, which is
        # measured and printed on the figure rather than hidden.
        vmax = float(g["vmax"])
        src = f"shared '{group}' scale, set by {g.get('set_by', 'an earlier figure')}"

    overridden = False
    if env_vmax is not None:
        vmax = float(env_vmax); src = "ULAP_PG_VMAX override"; overridden = True
    vmin = vmax - dyn_range
    if env_vmin is not None:
        vmin = float(env_vmin); src += " + ULAP_PG_VMIN override"; overridden = True

    sat = float(_np.mean(finite > vmax)) if finite.size else 0.0
    floor = float(_np.mean(finite < vmin)) if finite.size else 0.0
    if not overridden:
        state[group] = {"vmax": vmax, "vmin": vmin, "dyn_range_db": dyn_range,
                        "quantum_db": quantum,
                        "set_by": g.get("set_by", figure),
                        "figures": {**(g.get("figures") or {}),
                                    figure: {"own_p99_db": round(own_p99, 2),
                                             "vmax_used_db": vmax,
                                             "saturated_fraction": round(sat, 5)}}}
        try:
            with open(SCALE_FILE, "w") as fh:
                json.dump(state, fh, indent=2)
        except Exception as exc:                       # non-fatal: figure still renders
            print(f"WARN: could not write {SCALE_FILE}: {exc!r}")
    print(f"colour scale: vmin={vmin:.1f} vmax={vmax:.1f} dB  ({src}; own p99 "
          f"{own_p99:.1f} dB; {100*sat:.2f} % of cells saturate at the top, "
          f"{100*floor:.2f} % clip at the bottom)")
    if own_p99 > vmax + 1e-9:
        print(f"NOTE: this map's p99 ({own_p99:.1f} dB) is above the shared vmax "
              f"({vmax:.1f} dB). Comparability was kept in preference to headroom. "
              f"To rescale the whole group, delete {SCALE_FILE} and re-render every "
              f"figure in it, or set ULAP_PG_VMAX explicitly for all of them.")
    lab = (f"path gain [dB] — shared scale {vmin:.0f} to {vmax:.0f} dB "
           f"({dyn_range:.0f} dB range, group '{group}')")
    if sat >= 0.005:
        lab += f"; top {100*sat:.1f} % saturated"
    return vmin, vmax, lab


_mani = json.load(open(os.path.join(HERE, "scene_build", "scene_manifest.json")))
scene_buildings_xy = [np.array(b["ring"]) for b in _mani["buildings"]]
_terr = _mani["terrain"]
terrain_center_z = _terr["zmax"]          # rx/probe height ref (above all ground)

print("mitsuba variant:", mi.variant())

# ---- 1. scene ----
scene = load_scene(SCENE)
scene.frequency = 3.5e9           # 5G mid-band
bb = scene.mi_scene.bbox()
print("scene bbox:", [round(v,1) for v in bb.min], "->", [round(v,1) for v in bb.max])

# ---- 2. antenna arrays ----
scene.tx_array = PlanarArray(num_rows=1, num_cols=1,
                             vertical_spacing=0.5, horizontal_spacing=0.5,
                             pattern="tr38901", polarization="V")
scene.rx_array = PlanarArray(num_rows=1, num_cols=1,
                             vertical_spacing=0.5, horizontal_spacing=0.5,
                             pattern="dipole", polarization="V")

# ---- 3. transmitters = the real towers ----
#   flat:    z = tower height above z=0
#   terrain: z = local ground elevation (AVG_DTM) + tower height
TOWERS = []
for a in _mani["antennas"]:
    name = a["name"].lower().replace(" ", "_")
    z = (a["ground_z"] + a["h"]) if TERRAIN else a["h"]
    TOWERS.append((name, [a["x"], a["y"], z]))
for name, pos in TOWERS:
    scene.add(Transmitter(name=name, position=[float(p) for p in pos]))
    print(f"TX {name} @ {[round(p,1) for p in pos]}")

# a probe receiver near the scene centre (above local ground)
rx_z = (terrain_center_z + 1.5) if TERRAIN else 1.5
scene.add(Receiver(name="rx0", position=[0.0, 0.0, rx_z]))

# ---- 4. radio / coverage map over the whole scene ----
# flat: measurement plane just above z=0. terrain: a horizontal cut above the
# highest ground (avoids sampling inside the hills); ~drone/rooftop altitude.
t0 = time.time()
rm_solver = RadioMapSolver()
print(f"grid: {CELL_M:g} m cells (env ULAP_RM_CELL_M; shared with "
      f"sionna_terrain_ground.py), samples_per_tx={SAMPLES_PER_TX:.0e} "
      f"(env ULAP_RM_SAMPLES_PER_TX)")
rm_kwargs = dict(scene=scene, max_depth=5, cell_size=(CELL_M, CELL_M),
                 samples_per_tx=SAMPLES_PER_TX)
if TERRAIN:
    cx = float((bb.min[0]+bb.max[0])/2); cy = float((bb.min[1]+bb.max[1])/2)
    sx = float(bb.max[0]-bb.min[0]);     sy = float(bb.max[1]-bb.min[1])
    rm_kwargs.update(center=[cx, cy, _terr["zmax"] + 5.0],
                     size=[sx, sy], orientation=[0.0, 0.0, 0.0])
rm = rm_solver(**rm_kwargs)
print(f"radio map solved in {time.time()-t0:.1f}s")

# ---- 5. propagation paths (LoS + reflections) for the probe link ----
t0 = time.time()
p_solver = PathSolver()
paths = p_solver(scene=scene, max_depth=5, los=True,
                 specular_reflection=True, diffuse_reflection=False,
                 refraction=True, synthetic_array=False, seed=41)
print(f"paths solved in {time.time()-t0:.1f}s")

# ---- 6a. render top-down with the radio map overlaid (3D view) ----
cx = float((bb.min[0]+bb.max[0])/2); cy = float((bb.min[1]+bb.max[1])/2)
cam = Camera(position=[cx, cy, 2600], look_at=[cx, cy, 0])
out_png = os.path.join(OUTDIR, f"coverage_map{SUF}.png")
scene.render_to_file(camera=cam, filename=out_png, radio_map=rm,
                     rm_metric="path_gain", resolution=(1400, 1000),
                     num_samples=64)
print("wrote", out_png)

out_png2 = os.path.join(OUTDIR, f"scene_render{SUF}.png")
scene.render_to_file(camera=cam, filename=out_png2, resolution=(1400, 1000),
                     num_samples=64)
print("wrote", out_png2)

# ---- 6b. clean best-server path-gain heatmap in dB (matplotlib) ----
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
import matplotlib.cm as cm

pg = np.array(rm.path_gain)                       # [num_tx, H, W], linear
pg_best = pg.max(axis=0)                           # best-server (max over towers)
with np.errstate(divide="ignore"):
    pg_db = 10.0*np.log10(pg_best)
pg_db[~np.isfinite(pg_db)] = np.nan

# The blank fraction of THIS map was never reported. At the superseded 5 m / 1e7
# defaults it was 18.92 % on the terrain plane -- and this is the figure the paper
# compares the ground-following map against. Print it every run.
nocov = float(np.mean(~np.isfinite(pg_db)))
print(f"no-coverage fraction: {nocov:.5f}  (samples_per_tx={SAMPLES_PER_TX:.0e}, "
      f"{CELL_M:g} m cells)")
if nocov > 0.02:
    print(f"WARNING: {100*nocov:.1f} % of cells read zero path gain. RadioMapSolver is a "
          f"Monte-Carlo estimator and an unsampled cell is plotted identically to a dark "
          f"one; this fraction falls ~10x per decade of samples_per_tx. Do not read a "
          f"dark cell as shadow without raising ULAP_RM_SAMPLES_PER_TX.")

# scene extent from cell centres
cc = np.array(rm.cell_centers)                     # [H, W, 3]
xmin, xmax = cc[...,0].min(), cc[...,0].max()
ymin, ymax = cc[...,1].min(), cc[...,1].max()

# F9: the terrain map shares its scale with the ground-following map, which the
# paper prints next to it. The flat map is its own group (nothing is printed
# beside it), but goes through the same code path so there is one convention.
_group = "terrain" if TERRAIN else "flat"
vmin, vmax, _cb_label = resolve_pathgain_scale(
    pg_db, group=_group, figure=f"coverage_pathgain_db{SUF}.png")
fig, ax = plt.subplots(figsize=(13, 12))
im = ax.imshow(pg_db, origin="lower", extent=[xmin, xmax, ymin, ymax],
               cmap="viridis", vmin=vmin, vmax=vmax, interpolation="nearest")
# building footprints
for b in scene_buildings_xy:
    ax.plot(b[:,0], b[:,1], color="white", lw=0.3, alpha=0.35)
# towers
for name, pos in TOWERS:
    ax.scatter([pos[0]], [pos[1]], c="red", s=80, marker="^",
               edgecolors="white", zorder=5)
    ax.annotate(name, (pos[0], pos[1]), color="white", fontsize=11,
                xytext=(8, 8), textcoords="offset points", weight="bold")
_gtxt = f"terrain drape ({_terr['zmin']:.0f}-{_terr['zmax']:.0f} m)" if TERRAIN else "flat ground"
_htxt = (f"single horizontal plane at z = {_terr['zmax'] + 5.0:.0f} m"
         if TERRAIN else "measurement plane at z = 1.5 m")
_stxt = (f"colour scale {vmin:.0f} to {vmax:.0f} dB and {CELL_M:g} m grid shared with "
         "coverage_pathgain_db_terrain_groundfollow.png" if TERRAIN
         else f"colour scale {vmin:.0f} to {vmax:.0f} dB")
ax.set_title(f"Newton, Barbados — 3.5 GHz best-server path gain (Sionna RT, {_gtxt})\n"
             f"{_htxt} · {CELL_M:g} m cells, {SAMPLES_PER_TX:.0e} samples/tx, "
             f"{100*nocov:.2f} % of cells unsampled\n{_stxt}", fontsize=10)
ax.set_xlabel("x [m] (EPSG:21292 local)"); ax.set_ylabel("y [m]")
ax.set_aspect("equal")
cb = fig.colorbar(im, ax=ax, shrink=0.8, pad=0.02); cb.set_label(_cb_label, fontsize=8)
out_png3 = os.path.join(OUTDIR, f"coverage_pathgain_db{SUF}.png")
fig.savefig(out_png3, dpi=130, bbox_inches="tight")
print("wrote", out_png3)
print("DONE")
