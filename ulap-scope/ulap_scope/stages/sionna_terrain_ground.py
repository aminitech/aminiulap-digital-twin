#!/usr/bin/env python3
"""
sionna_terrain_ground.py -- GROUND-FOLLOWING coverage map for the terrain scene.

Sionna's RadioMapSolver only measures on a flat horizontal plane. Over 55 m of
relief a single plane is either underground (in the hills) or far above ground
(in the valleys). This computes a stack of horizontal planes spanning the relief
and, for each map cell, samples the plane nearest to (local terrain + 1.5 m),
assembling a coverage map at a constant height *above ground*.

    /opt/anaconda3/envs/sionna/bin/python sionna_terrain_ground.py

Defect F8 (fixed here)
----------------------
The original stack was ``K = 9`` planes and each cell took the *nearest* plane.
Over 55.5 m of relief that is 6.94 m spacing and a +-3.47 m worst-case height
error, and because "nearest" rounds down as often as up it placed the receiver
**below local ground in 28.9 % of cells**. Those cells are occluded by the
terrain itself and read zero path gain -- they are indistinguishable from
genuine shadow in the shipped figure. Two changes:

1. **Selection rule.** Each cell now takes the LOWEST plane *at or above*
   ``terrain + RXH``. The height error becomes one-sided, in ``[0, spacing)``,
   and the receiver can never be underground.
2. **Plane count from a stated tolerance, not a magic number.** ``K`` is derived
   from ``MAX_HEIGHT_ERR_M`` (default 1.0 m), which is the worst-case receiver
   height error the stack is allowed to introduce:

       K = ceil(relief / MAX_HEIGHT_ERR_M) + 1

   1.0 m is argued as follows: (a) it keeps every cell inside a 1.5-2.5 m AGL
   band, i.e. still a human-height receiver; (b) it is at or below the terrain
   relief already present *inside one radio-map cell* (0.19 m median / 0.42 m
   p90 / 2.2 m max for the Newton DTM at 8 m cells), below which a finer stack
   is measuring the DTM's bilinear interpolant rather than the radio.

   Cost is linear in K: K RadioMapSolver solves and a ``[K, H, W]`` float32
   stack. For Newton (relief 55.5 m -> K = 57, grid 305 x 301) that is 57 solves
   and ~21 MB of stack. See ``comparison/F8-F9-FIX.md`` for measured numbers.

   Override with ``ULAP_GF_MAX_HEIGHT_ERR_M`` (tolerance, m) or
   ``ULAP_GF_PLANES`` (explicit K, wins over the tolerance).

Defect F9 (fixed here)
----------------------
This figure and ``coverage_pathgain_db_terrain.png`` are placed side by side in
the paper with a caption inviting comparison, but each used to compute its own
``vmax = p99(own data)``, so identical hues meant different dB. Both now resolve
their colour limits through ``resolve_pathgain_scale()`` against a shared scale
recorded in ``sionna_out/pathgain_scale.json``, and the figure states the scale
it is on. Override with ``ULAP_PG_VMIN`` / ``ULAP_PG_VMAX``.

Defect F10 -- the sampling default (raised here, 2026-07-30)
------------------------------------------------------------
``RadioMapSolver`` is a Monte-Carlo estimator. A cell that collects no ray hit
reads zero path gain and is plotted identically to a cell that is genuinely
dark. This stage used to ship ``samples_per_tx = 1e6``, at which **47 % of the
map was unsampled rather than shadowed**. The default is now ``1e8``.

Measured on this scene (GB10, ``cuda_ad_mono_polarized``; CPU column is
``llvm_ad_mono_polarized``, 20 cores, same host), 8 m cells, K = 57 planes:

    samples/tx   map blank   stack solve (GPU)   stack solve (CPU)
    1e6          47.00 %        0.41 s               15 s
    1e7          10.99 %        1.02 s               35 s
    1e8 (new)     1.16 %        7.20 s              262 s
    1e9           0.24 %       69.06 s             2383 s

1e8 is chosen as **the largest sample count that keeps the CPU/LLVM backend --
the backend the sovereignty claim rests on -- under 10 minutes per stage run**.
1e9 converges the map but costs 40 minutes per run on that backend and would put
the published Raspberry Pi 4 pipeline (310 s total) into the hours.

**This is a cost-bounded compromise, not a converged setting, and it is stated as
one.** At 1e8 the map is still 1.16 % blank against a converged dark fraction of
0.24 %, so roughly four fifths of the blank area remains sample starvation. A
dark cell still may NOT be read as shadow at the default. For any claim about
shadow *area*, run ``ULAP_GF_SAMPLES_PER_TX=1e9``.

Overrides, in precedence order: ``ULAP_GF_SAMPLES_PER_TX`` (this stage only),
then ``ULAP_RM_SAMPLES_PER_TX`` (shared with ``sionna_coverage.py``).

Defect F11 -- spatial resolution harmonised (fixed here, 2026-07-30)
--------------------------------------------------------------------
The paper prints this map next to ``coverage_pathgain_db_terrain.png`` and
invites comparison, but the two were on different grids -- 5 m cells there, 8 m
here. Colour was harmonised (F9); resolution was not. Both stages now read one
cell size from ``ULAP_RM_CELL_M``, default **8 m**, so they cannot drift again.

8 m was chosen over 5 m on measurement, not taste:

* it resolves the geometry that casts the shadow -- the median footprint of the
  576 buildings is 12.88 m across its narrow dimension, and 90.8 % of footprints
  are wider than one 8 m cell (5 m would raise that to 96.2 %, a 5.4 pp gain);
* the estimator can carry it. At the 1e8 default, 8 m leaves 1.16 % of cells
  unsampled and 5 m leaves 3.54 % -- a 3x worse artefact for 5.4 pp of building
  detail. Matching 8 m's artefact level at 5 m needs ~2.5e8 samples/tx, i.e.
  ~2.5x the cost on both backends;
* the terrain the map is *about* is a 30.6 x 29.8 m DTM posting. At 8 m the map
  is already 3.8x finer than its own elevation data; 5 m claims spatial detail in
  terrain-driven shadow that the source does not contain.

The cost is real and is recorded: ``coverage_pathgain_db_terrain.png`` and
``coverage_pathgain_db.png`` lose resolution, 5 m -> 8 m.
"""
import os, json
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
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import sionna.rt as rt

if _WANT_VARIANT:
    import mitsuba as _mi_chk
    if _mi_chk.variant() != _WANT_VARIANT:
        raise SystemExit(f"backend mismatch: requested {_WANT_VARIANT!r} but the solver "
                         f"selected {_mi_chk.variant()!r}; refusing to report results for the wrong backend")
from sionna.rt import load_scene, PlanarArray, Transmitter, RadioMapSolver

HERE = os.environ.get("ULAP_WORK_DIR") or os.path.dirname(os.path.abspath(__file__))
SCENE  = os.path.join(HERE, "mitsuba_scene_terrain", "scene.xml")
OUTDIR = os.path.join(HERE, "sionna_out"); os.makedirs(OUTDIR, exist_ok=True)
mani   = json.load(open(os.path.join(HERE, "scene_build", "scene_manifest.json")))
towers = [t for t in json.load(open(os.path.join(HERE, "scene_build", "towers_near.json")))
          if t["in_scene"]]
buildings_xy = [np.array(b["ring"]) for b in mani["buildings"]]
T = mani["terrain"]
RXH = 1.5                                     # target receiver height above ground [m]

# ---- F8: plane stack sized from a stated tolerance --------------------------
RELIEF = float(T["zmax"] - T["zmin"])
MAX_HEIGHT_ERR_M = float(os.environ.get("ULAP_GF_MAX_HEIGHT_ERR_M", 1.0))
if os.environ.get("ULAP_GF_PLANES"):
    K = max(2, int(os.environ["ULAP_GF_PLANES"]))
    K_SOURCE = "ULAP_GF_PLANES override"
else:
    K = max(2, int(np.ceil(RELIEF / MAX_HEIGHT_ERR_M)) + 1)
    K_SOURCE = f"ceil(relief {RELIEF:.2f} m / tolerance {MAX_HEIGHT_ERR_M:g} m) + 1"

# ---- F11: one cell size, shared with sionna_coverage.py ---------------------
# The paper prints this map beside coverage_pathgain_db_terrain.png. Both stages
# read this same variable so the two figures cannot end up on different grids
# again. See the F11 note in the module docstring for why 8 m and what 5 m costs.
CELL_M = float(os.environ.get("ULAP_RM_CELL_M", 8.0))

# ---- F10: sampling default ---------------------------------------------------
# RadioMapSolver is a Monte-Carlo estimator: a cell that collects no ray hits
# reads zero path gain and is plotted identically to a cell that is genuinely
# dark. A receiver 1.5 m above ground sees the towers at a far more grazing angle
# than one on a plane 22 m up, so it starves first. Measured on the Newton scene
# (comparison/results/f8.json), the no-coverage fraction of THIS map falls
# 47.0 % -> 11.0 % -> 1.16 % -> 0.24 % as samples_per_tx goes 1e6 -> 1e9.
# The default was raised 1e6 -> 1e8 on 2026-07-30: it is the largest count that
# keeps the CPU/LLVM backend under 10 min per run (262 s vs 2383 s at 1e9).
# It is NOT converged -- 1.16 % blank against 0.24 % genuine -- so a dark cell is
# still not evidence of shadow. Use ULAP_GF_SAMPLES_PER_TX=1e9 for that claim.
SAMPLES_PER_TX = int(float(os.environ.get(
    "ULAP_GF_SAMPLES_PER_TX",                          # this stage, wins
    os.environ.get("ULAP_RM_SAMPLES_PER_TX", 10**8))))  # shared with coverage
# The dark fraction this map converges to at 1e9 on this scene. Printed next to
# the measured no-coverage so the gap between them is never invisible.
CONVERGED_DARK_FRACTION = 0.0024


# ---- F9: one colour scale shared across the figures the paper compares ------
# NOTE: this helper is duplicated verbatim in sionna_coverage.py. The two stages
# run in separate processes from separate files and ulap_scope.stages carries no
# shared runtime module, so the scale contract lives in the JSON sidecar, not in
# an import. Keep the two copies identical.
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


def terr(x, y):
    nx, ny = T["nx"], T["ny"]
    fx = (x-T["minx"])/(T["maxx"]-T["minx"])*(nx-1)
    fy = (y-T["miny"])/(T["maxy"]-T["miny"])*(ny-1)
    fx = np.clip(fx,0,nx-1); fy = np.clip(fy,0,ny-1)
    ix=fx.astype(int); iy=fy.astype(int); ix1=np.minimum(ix+1,nx-1); iy1=np.minimum(iy+1,ny-1)
    tx=fx-ix; ty=fy-iy; z=np.array(T["z"]).reshape(ny,nx)
    return (z[iy,ix]*(1-tx)*(1-ty)+z[iy,ix1]*tx*(1-ty)+z[iy1,ix]*(1-tx)*ty+z[iy1,ix1]*tx*ty)

# scene + towers (z = ground elevation + tower height)
scene = load_scene(SCENE); scene.frequency = 3.5e9
scene.tx_array = PlanarArray(num_rows=1,num_cols=1,pattern="tr38901",polarization="V")
scene.rx_array = PlanarArray(num_rows=1,num_cols=1,pattern="dipole", polarization="V")
for t in towers:
    scene.add(Transmitter(t["name"].lower().replace(" ","_"),
              [float(t["x"]),float(t["y"]),float(t["ground_z"]+t["h"])]))
bb = scene.mi_scene.bbox()
cx=float((bb.min[0]+bb.max[0])/2); cy=float((bb.min[1]+bb.max[1])/2)
sx=float(bb.max[0]-bb.min[0]); sy=float(bb.max[1]-bb.min[1])

# stack of horizontal planes across the relief
plane_z = np.linspace(T["zmin"]+RXH, T["zmax"]+RXH, K)
spacing = float(plane_z[1]-plane_z[0])
print(f"K={K} planes ({K_SOURCE}), z = {plane_z[0]:.1f} .. {plane_z[-1]:.1f} m, "
      f"spacing {spacing:.3f} m -> worst-case receiver height error {spacing:.3f} m "
      f"(one-sided, always ABOVE ground)")
print(f"grid: {CELL_M:g} m cells (env ULAP_RM_CELL_M; shared with sionna_coverage.py), "
      f"samples_per_tx={SAMPLES_PER_TX:.0e} (env ULAP_GF_SAMPLES_PER_TX)")
stack = []; cc = None
solver = RadioMapSolver()
for z in plane_z:
    rm = solver(scene=scene, max_depth=5, cell_size=(CELL_M, CELL_M),
                samples_per_tx=SAMPLES_PER_TX,
                center=[cx,cy,float(z)], size=[sx,sy], orientation=[0.,0.,0.])
    stack.append(np.array(rm.path_gain).max(axis=0).astype(np.float32))  # best-server [H,W]
    if cc is None: cc = np.array(rm.cell_centers)         # [H,W,3]
stack = np.stack(stack, axis=0)                           # [K,H,W]
print(f"stack {stack.shape} {stack.dtype}, {stack.nbytes/1e6:.1f} MB")

# per-cell: choose the LOWEST plane AT OR ABOVE (terrain + RXH)  [F8]
X = cc[...,0]; Y = cc[...,1]
ground = terr(X, Y)                                       # [H,W]
target = ground + RXH                                     # [H,W]
kbest = np.clip(np.searchsorted(plane_z, target, side="left"), 0, K-1)  # [H,W]
H, W = target.shape
sel_z = plane_z[kbest]
offset = sel_z - target                                   # >= 0 by construction
# Guard: the top plane sits at zmax + RXH, so the clip above can only bite where
# the bilinear terrain sample exceeds the manifest zmax by float noise. Any cell
# whose selected plane is still below local ground is FLAGGED (NaN), never
# reported as no-coverage.
below_ground = sel_z < ground
n_below = int(below_ground.sum())
print(f"receiver height above target ({RXH:.1f} m AGL): median {np.median(offset):.3f} m, "
      f"p90 {np.percentile(offset,90):.3f} m, max {offset.max():.3f} m")
print(f"cells with the selected plane below local ground: {n_below} "
      f"({100.0*n_below/offset.size:.4f} %)")
if n_below:
    print("WARNING: some cells could not be raised above local ground and are flagged, "
          "not counted as coverage")

gf = np.take_along_axis(stack, kbest[None], axis=0)[0]    # [H,W] ground-following
with np.errstate(divide="ignore"): gf_db = 10*np.log10(gf)
gf_db[~np.isfinite(gf_db)] = np.nan
gf_db[below_ground] = np.nan
nocov = float(np.mean(~np.isfinite(gf_db)))
print(f"no-coverage fraction: {nocov:.5f}  (samples_per_tx={SAMPLES_PER_TX:.0e}, "
      f"{CELL_M:g} m cells)")
# Always say how much of the blank area is estimator, not shadow. A threshold-only
# warning goes quiet the moment the default is raised, which is exactly when the
# residual artefact becomes easy to mistake for physics.
if nocov > 0.05:
    print(f"WARNING: {100*nocov:.1f} % of cells read zero path gain. At this receiver "
          f"height most of that is Monte-Carlo sample starvation, NOT shadow -- the "
          f"no-coverage fraction of this map falls roughly 10x per decade of "
          f"samples_per_tx (see comparison/results/f8.json). Do not read a dark cell "
          f"as terrain or building shadow without raising ULAP_GF_SAMPLES_PER_TX.")
elif nocov > CONVERGED_DARK_FRACTION * 1.5:
    _art = 1.0 - CONVERGED_DARK_FRACTION / nocov
    print(f"NOTE: this map converges to {100*CONVERGED_DARK_FRACTION:.2f} % dark at "
          f"samples_per_tx=1e9 on this scene, so about {100*_art:.0f} % of the "
          f"{100*nocov:.2f} % blank area above is still sample starvation, not shadow. "
          f"The 1e8 default is a cost bound (CPU/LLVM: 262 s vs 2383 s at 1e9), not "
          f"convergence. Run ULAP_GF_SAMPLES_PER_TX=1e9 before claiming a shadow area.")

ext = [X.min(), X.max(), Y.min(), Y.max()]
fig, ax = plt.subplots(figsize=(13,12))
vmin, vmax, cb_label = resolve_pathgain_scale(
    gf_db, group="terrain", figure="coverage_pathgain_db_terrain_groundfollow.png")
im=ax.imshow(gf_db, origin="lower", extent=ext, cmap="viridis", vmin=vmin, vmax=vmax,
             interpolation="nearest")
for b in buildings_xy: ax.plot(b[:,0],b[:,1],color="white",lw=0.25,alpha=0.3)
for t in towers:
    ax.scatter([t["x"]],[t["y"]],c="red",s=80,marker="^",edgecolors="white",zorder=5)
    ax.annotate(t["name"],(t["x"],t["y"]),color="white",fontsize=11,weight="bold",
                xytext=(8,8),textcoords="offset points")
ax.set_title("Newton, Barbados — 3.5 GHz best-server path gain, GROUND-FOLLOWING (terrain)\n"
             f"receiver {RXH:.1f}–{RXH+spacing:.1f} m AGL "
             f"(K={K} planes, {spacing:.2f} m spacing, never below ground) · "
             f"{CELL_M:g} m cells, {SAMPLES_PER_TX:.0e} samples/tx, "
             f"{100*nocov:.2f} % of cells unsampled\n"
             f"colour scale {vmin:.0f} to {vmax:.0f} dB and {CELL_M:g} m grid shared with "
             f"coverage_pathgain_db_terrain.png", fontsize=10)
ax.set_xlabel("x [m] (EPSG:21292 local)"); ax.set_ylabel("y [m]"); ax.set_aspect("equal")
cb=fig.colorbar(im,ax=ax,shrink=0.8,pad=0.02); cb.set_label(cb_label, fontsize=8)
out=os.path.join(OUTDIR,"coverage_pathgain_db_terrain_groundfollow.png")
fig.savefig(out,dpi=130,bbox_inches="tight"); print("wrote",out)
print("DONE")
