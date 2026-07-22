#!/usr/bin/env python3
"""
sionna_coverage.py -- load the exported Barbados/Newton scene in Sionna RT 2.0.1
and compute a radio coverage map from the real cell towers.

Run in the sionna conda env:
    /opt/anaconda3/envs/sionna/bin/python sionna_coverage.py

Runs on CPU (Mitsuba LLVM backend) -- no CUDA needed, just slower.
"""
import os, sys, time
os.environ.setdefault("DRJIT_NO_RTLD_DEEPBIND", "1")

import numpy as np
import mitsuba as mi
import sionna.rt as rt
from sionna.rt import (load_scene, PlanarArray, Transmitter, Receiver,
                       Camera, RadioMapSolver, PathSolver)

HERE   = os.path.dirname(os.path.abspath(__file__))
# argv: [mode] [scene.xml]   mode = "flat" (default) | "terrain"
MODE   = sys.argv[1] if len(sys.argv) > 1 else "flat"
TERRAIN = (MODE == "terrain")
SCENE  = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
    HERE, "mitsuba_scene_terrain" if TERRAIN else "mitsuba_scene", "scene.xml")
OUTDIR = os.path.join(HERE, "sionna_out")
os.makedirs(OUTDIR, exist_ok=True)
SUF = "_terrain" if TERRAIN else ""

# building footprints + terrain for overlay / tower heights
import json
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
rm_kwargs = dict(scene=scene, max_depth=5, cell_size=(5.0, 5.0), samples_per_tx=10**7)
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

# scene extent from cell centres
cc = np.array(rm.cell_centers)                     # [H, W, 3]
xmin, xmax = cc[...,0].min(), cc[...,0].max()
ymin, ymax = cc[...,1].min(), cc[...,1].max()

vmax = np.nanpercentile(pg_db, 99)
vmin = vmax - 80.0                                 # 80 dB dynamic range
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
ax.set_title(f"Newton, Barbados — 3.5 GHz best-server path gain (Sionna RT, {_gtxt})", fontsize=12)
ax.set_xlabel("x [m] (EPSG:21292 local)"); ax.set_ylabel("y [m]")
ax.set_aspect("equal")
cb = fig.colorbar(im, ax=ax, shrink=0.8, pad=0.02); cb.set_label("Path gain [dB]")
out_png3 = os.path.join(OUTDIR, f"coverage_pathgain_db{SUF}.png")
fig.savefig(out_png3, dpi=130, bbox_inches="tight")
print("wrote", out_png3)
print("DONE")
