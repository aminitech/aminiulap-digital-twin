#!/usr/bin/env python3
"""
render_sionna_perspective.py -- render the Barbados scene the way NVIDIA's
sionna-rt-gui does: an ANGLED perspective camera over the 3D buildings, with
  (a) persp_paths.png     -- the propagation rays from the tower, and
  (b) persp_radiomap.png  -- the radio map draped over the 3D buildings (viridis).

The stock sionna_coverage.py renders from a straight-overhead camera
(position=[cx,cy,2600], look_at=[cx,cy,0]) -> a flat top-down map. The GUI look
needs (1) an angled camera pose + fov, and (2) passing paths=/radio_map= to the
renderer. show_devices=True draws the yellow "Transmitter" marker.

Run in the sionna env (GPU box, or this Mac's CPU -- slower):
    /opt/anaconda3/envs/sionna/bin/python render_sionna_perspective.py [flat|terrain]

Quality is env-driven so you can iterate fast, then crank it for the final:
    ULAP_RES=1600x900 ULAP_SAMPLES=256 ULAP_SPP=10000000 ULAP_DEPTH=6 \
    /opt/anaconda3/envs/sionna/bin/python render_sionna_perspective.py
"""
import os, sys, json, time, math
os.environ.setdefault("DRJIT_NO_RTLD_DEEPBIND", "1")
import numpy as np
import sionna.rt as rt
from sionna.rt import (load_scene, PlanarArray, Transmitter, Receiver,
                       Camera, RadioMapSolver, PathSolver)

HERE = os.path.dirname(os.path.abspath(__file__))
MODE = sys.argv[1] if len(sys.argv) > 1 else "flat"
TERRAIN = (MODE == "terrain")
SCENE = os.path.join(HERE, "mitsuba_scene_terrain" if TERRAIN else "mitsuba_scene", "scene.xml")
OUT = os.path.join(HERE, "sionna_out"); os.makedirs(OUT, exist_ok=True)
SUF = "_terrain" if TERRAIN else ""
mani = json.load(open(os.path.join(HERE, "scene_build", "scene_manifest.json")))

# ---- env-driven quality knobs (fast defaults; override for the final render) ----
def _env(k, d): return os.environ.get(k, d)
RES = _env("ULAP_RES", "1000x560")
RES_W, RES_H = (int(v) for v in RES.lower().split("x"))
SAMPLES = int(_env("ULAP_SAMPLES", "64"))     # ray-tracing AA samples for the picture
SPP     = int(_env("ULAP_SPP", "1000000"))    # radio-map samples per TX
DEPTH   = int(_env("ULAP_DEPTH", "5"))        # max interaction depth
DIFFUSE = _env("ULAP_DIFFUSE", "1") == "1"
HERO_NAME = _env("ULAP_HERO", "Rising Sun")
print(f"[cfg] res={RES_W}x{RES_H} samples={SAMPLES} spp={SPP} depth={DEPTH} "
      f"diffuse={DIFFUSE} hero='{HERO_NAME}' mode={MODE}")

# ---- scene + arrays ----
scene = load_scene(SCENE)
scene.frequency = 3.5e9
scene.tx_array = PlanarArray(num_rows=1, num_cols=1, pattern="tr38901", polarization="V")
scene.rx_array = PlanarArray(num_rows=1, num_cols=1, pattern="dipole",  polarization="V")

# marker sizes: Sionna auto-sizes device spheres from the scene bbox (~75 m here,
# far too big). Shrink them and colour the TX yellow like the sionna-rt-gui.
TX_R, RX_R = 11.0, 5.0

# ---- transmitters = real towers; remember the hero (framing + receiver seeding) ----
hero = None
for a in mani["antennas"]:
    z = (a.get("ground_z", 0.0) + a["h"]) if TERRAIN else a["h"]
    tx = Transmitter(name=a["name"].lower().replace(" ", "_"),
                     position=[float(a["x"]), float(a["y"]), float(z)])
    tx.display_radius = TX_R; tx.color = (1.0, 0.78, 0.20)
    scene.add(tx)
    if a["name"] == HERO_NAME:
        hero = (float(a["x"]), float(a["y"]), float(z))
if hero is None:
    a = mani["antennas"][0]
    hero = (float(a["x"]), float(a["y"]), float((a.get("ground_z",0.0)+a["h"]) if TERRAIN else a["h"]))
hx, hy, hz = hero
grnd = (mani["terrain"]["zmax"] if TERRAIN else 0.0)

# ---- receivers: a fan of ground RX around the hero so PathSolver returns a
#      rich bundle of rays (this is what makes the "paths" picture look full) ----
NRX, RAD = 14, 300.0
rx_names = []
for i in range(NRX):
    ang = 2*math.pi*i/NRX
    rx = Receiver(f"rx{i}", position=[float(hx + RAD*math.cos(ang)),
                                      float(hy + RAD*math.sin(ang)), float(grnd + 1.5)])
    rx.display_radius = RX_R; rx.color = (0.85, 0.90, 0.95)
    scene.add(rx); rx_names.append(f"rx{i}")

# ---- solve paths (timed like the GUI badge) ----
t0 = time.time()
paths = PathSolver()(scene=scene, max_depth=DEPTH, los=True,
                     specular_reflection=True, diffuse_reflection=DIFFUSE,
                     refraction=True, synthetic_array=False, seed=41)
t_paths = 1e3*(time.time()-t0); print(f"[paths]    solved in {t_paths:8.1f} ms")

# ---- solve radio map over the whole scene (timed) ----
bb = scene.mi_scene.bbox()
cx = float((bb.min[0]+bb.max[0])/2); cy = float((bb.min[1]+bb.max[1])/2)
sx = float(bb.max[0]-bb.min[0]);     sy = float(bb.max[1]-bb.min[1])
t0 = time.time()
rm = RadioMapSolver()(scene=scene, max_depth=DEPTH, cell_size=(5.0, 5.0),
                      samples_per_tx=SPP,
                      center=[cx, cy, (grnd + 5.0) if TERRAIN else 1.5],
                      size=[sx, sy], orientation=[0., 0., 0.])
t_rm = 1e3*(time.time()-t0); print(f"[radiomap] solved in {t_rm:8.1f} ms")

# fix the viridis dB window from the map itself (stable colours across runs)
pg = np.array(rm.path_gain); best = pg.max(axis=0)
with np.errstate(divide="ignore"): db = 10*np.log10(best)
db = db[np.isfinite(db)]
rm_vmax = float(np.percentile(db, 99))
rm_vmin = rm_vmax - 70.0
print(f"[radiomap] path-gain window {rm_vmin:.0f} .. {rm_vmax:.0f} dB")

# ---- ANGLED perspective camera: stand back SW of the hero, elevated, look at it ----
diag = math.hypot(sx, sy)
back = 0.30 * diag
cam = Camera(position=[hx - back*0.70, hy - back, grnd + 0.34*back],
             look_at=[hx + 60.0, hy + 20.0, grnd + 6.0])
FOV = float(_env("ULAP_FOV", "40"))

common = dict(camera=cam, resolution=(RES_W, RES_H), num_samples=SAMPLES,
              fov=FOV, lighting_scale=1.6, show_orientations=False)

# (a) ray paths over the 3D buildings  (TX + RX fan visible)
p_paths = os.path.join(OUT, f"persp_paths{SUF}.png")
scene.render_to_file(filename=p_paths, paths=paths, show_devices=True, **common)
print("wrote", p_paths)

# (b) radio map draped over the 3D buildings (viridis, fixed dB window).
#     drop the receivers first so only the yellow transmitter shows, like the GUI.
for n in rx_names:
    scene.remove(n)
p_rm = os.path.join(OUT, f"persp_radiomap{SUF}.png")
scene.render_to_file(filename=p_rm, radio_map=rm, rm_metric="path_gain",
                     rm_vmin=rm_vmin, rm_vmax=rm_vmax, show_devices=True, **common)
print("wrote", p_rm)

print(f"DONE  (paths {t_paths:.0f} ms · radio map {t_rm:.0f} ms)  "
      f"-- sionna-rt-gui-style perspective renders")
