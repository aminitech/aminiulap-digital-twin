#!/usr/bin/env python3
"""
sionna_animate_rx.py -- animate a receiver driving through the scene, showing its
live best-server path gain and which tower serves it (handover), over a Sionna RT
coverage backdrop. Outputs sionna_out/moving_rx.gif.

    /opt/anaconda3/envs/sionna/bin/python sionna_animate_rx.py
"""
import os, json
os.environ.setdefault("DRJIT_NO_RTLD_DEEPBIND", "1")
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation, PillowWriter
import sionna.rt as rt
from sionna.rt import (load_scene, PlanarArray, Transmitter, Receiver,
                       PathSolver, RadioMapSolver)

HERE   = os.path.dirname(os.path.abspath(__file__))
SCENE  = os.path.join(HERE, "mitsuba_scene", "scene.xml")
OUTDIR = os.path.join(HERE, "sionna_out"); os.makedirs(OUTDIR, exist_ok=True)
mani   = json.load(open(os.path.join(HERE, "scene_build", "scene_manifest.json")))
towers = [t for t in json.load(open(os.path.join(HERE, "scene_build", "towers_near.json")))
          if t["in_scene"]]
buildings_xy = [np.array(b["ring"]) for b in mani["buildings"]]
NAMES = [t["name"] for t in towers]

# scene + towers
scene = load_scene(SCENE); scene.frequency = 3.5e9
scene.tx_array = PlanarArray(num_rows=1,num_cols=1,pattern="tr38901",polarization="V")
scene.rx_array = PlanarArray(num_rows=1,num_cols=1,pattern="dipole", polarization="V")
for t in towers:
    scene.add(Transmitter(t["name"].lower().replace(" ","_"),
              [float(t["x"]),float(t["y"]),float(t["h"])]))

# ---- receiver route: a smooth drive across the scene at 1.5 m ----
wp = np.array([[-650,-880],[-300,-650],[0,-450],[300,-330],[600,-250],[950,-160]], float)
tt = np.linspace(0, 1, len(wp)); ts = np.linspace(0, 1, 60)
rx_x = np.interp(ts, tt, wp[:,0]); rx_y = np.interp(ts, tt, wp[:,1])
route = np.column_stack([rx_x, rx_y])
for i,(x,y) in enumerate(route):
    scene.add(Receiver(f"rx{i}", [float(x), float(y), 1.5]))

# ---- one path solve for every RX position; per-(rx,tx) gain ----
paths = PathSolver()(scene=scene, max_depth=6, los=True, specular_reflection=True,
                     diffuse_reflection=True, refraction=True, synthetic_array=False)
a, tau = paths.cir()                              # a:[2,rx,rx_ant,tx,tx_ant,P,T]
a = np.asarray(a); ac = a[0] + 1j*a[1]
pw = np.abs(ac)**2                                # [rx,rx_ant,tx,tx_ant,P,T]
gain_rx_tx = pw.sum(axis=(1,3,4,5))               # [num_rx, num_tx] linear
with np.errstate(divide="ignore"): gain_db = 10*np.log10(gain_rx_tx)
gain_db[~np.isfinite(gain_db)] = -200
best_db  = gain_db.max(axis=1)
serving  = gain_db.argmax(axis=1)

# ---- background best-server coverage map ----
bb = scene.mi_scene.bbox()
cx=float((bb.min[0]+bb.max[0])/2); cy=float((bb.min[1]+bb.max[1])/2)
sx=float(bb.max[0]-bb.min[0]); sy=float(bb.max[1]-bb.min[1])
rm = RadioMapSolver()(scene=scene, max_depth=5, cell_size=(10.,10.), samples_per_tx=10**6,
                      center=[cx,cy,1.5], size=[sx,sy], orientation=[0.,0.,0.])
bg = 10*np.log10(np.array(rm.path_gain).max(axis=0)); bg[~np.isfinite(bg)] = np.nan
cc=np.array(rm.cell_centers); ext=[cc[...,0].min(),cc[...,0].max(),cc[...,1].min(),cc[...,1].max()]

# ---- animate ----
tabcol = plt.get_cmap("tab10")
fig, (axm, axg) = plt.subplots(1, 2, figsize=(20, 9), gridspec_kw={"width_ratios":[1.25,1]})
axm.imshow(bg, origin="lower", extent=ext, cmap="viridis",
           vmin=np.nanpercentile(bg,99)-80, vmax=np.nanpercentile(bg,99), interpolation="nearest")
for b in buildings_xy: axm.plot(b[:,0],b[:,1],color="white",lw=0.25,alpha=0.3)
for i,t in enumerate(towers):
    axm.scatter([t["x"]],[t["y"]],c=[tabcol(i)],s=120,marker="^",edgecolors="white",zorder=6)
    axm.annotate(t["name"],(t["x"],t["y"]),color="white",fontsize=11,weight="bold",
                 xytext=(8,8),textcoords="offset points")
axm.set_xlim(ext[0],ext[1]); axm.set_ylim(ext[2],ext[3]); axm.set_aspect("equal")
axm.set_title("Moving receiver — 3.5 GHz best-server (drive-test)"); axm.set_xlabel("x [m]"); axm.set_ylabel("y [m]")
trail, = axm.plot([],[],"-",color="white",lw=1.5,alpha=0.8)
dot    = axm.scatter([],[],s=140,edgecolors="black",zorder=7)

axg.set_xlim(0,len(route)-1); axg.set_ylim(np.floor(best_db.min()/5)*5, np.ceil(best_db.max()/5)*5)
axg.set_xlabel("route step"); axg.set_ylabel("best-server path gain [dB]"); axg.grid(alpha=0.3)
axg.set_title("Live link budget along the route")
line, = axg.plot([],[],"-o",ms=3,color="#1f77b4")
txt = axg.text(0.03,0.06,"",transform=axg.transAxes,fontsize=12,weight="bold")

def frame(i):
    trail.set_data(route[:i+1,0], route[:i+1,1])
    dot.set_offsets(route[i]); dot.set_color(tabcol(serving[i]))
    line.set_data(np.arange(i+1), best_db[:i+1])
    txt.set_text(f"step {i:2d}  {best_db[i]:6.1f} dB  serving: {NAMES[serving[i]]}")
    return trail, dot, line, txt

anim = FuncAnimation(fig, frame, frames=len(route), interval=120, blit=False)
out = os.path.join(OUTDIR, "moving_rx.gif")
anim.save(out, writer=PillowWriter(fps=8), dpi=90)
print("route steps:", len(route), " gain range %.1f..%.1f dB" % (best_db.min(), best_db.max()))
print("handovers:", int((np.diff(serving)!=0).sum()))
print("wrote", out)
print("DONE")
