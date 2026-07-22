#!/usr/bin/env python3
"""
sionna_terrain_ground.py -- GROUND-FOLLOWING coverage map for the terrain scene.

Sionna's RadioMapSolver only measures on a flat horizontal plane. Over 55 m of
relief a single plane is either underground (in the hills) or far above ground
(in the valleys). This computes a stack of horizontal planes spanning the relief
and, for each map cell, samples the plane nearest to (local terrain + 1.5 m),
assembling a coverage map at a constant height *above ground*.

    /opt/anaconda3/envs/sionna/bin/python sionna_terrain_ground.py
"""
import os, json
os.environ.setdefault("DRJIT_NO_RTLD_DEEPBIND", "1")
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import sionna.rt as rt
from sionna.rt import load_scene, PlanarArray, Transmitter, RadioMapSolver

HERE = os.environ.get("ULAP_WORK_DIR") or os.path.dirname(os.path.abspath(__file__))
SCENE  = os.path.join(HERE, "mitsuba_scene_terrain", "scene.xml")
OUTDIR = os.path.join(HERE, "sionna_out"); os.makedirs(OUTDIR, exist_ok=True)
mani   = json.load(open(os.path.join(HERE, "scene_build", "scene_manifest.json")))
towers = [t for t in json.load(open(os.path.join(HERE, "scene_build", "towers_near.json")))
          if t["in_scene"]]
buildings_xy = [np.array(b["ring"]) for b in mani["buildings"]]
T = mani["terrain"]; RXH = 1.5; K = 9

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
print(f"{K} planes z = {plane_z[0]:.1f} .. {plane_z[-1]:.1f} m")
stack = []; cc = None
solver = RadioMapSolver()
for z in plane_z:
    rm = solver(scene=scene, max_depth=5, cell_size=(8.,8.), samples_per_tx=10**6,
                center=[cx,cy,float(z)], size=[sx,sy], orientation=[0.,0.,0.])
    stack.append(np.array(rm.path_gain).max(axis=0))     # best-server, [H,W]
    if cc is None: cc = np.array(rm.cell_centers)         # [H,W,3]
stack = np.stack(stack, axis=0)                           # [K,H,W]

# per-cell: choose plane nearest to (terrain + RXH)
X = cc[...,0]; Y = cc[...,1]
target = terr(X, Y) + RXH                                 # [H,W]
kbest = np.argmin(np.abs(plane_z[:,None,None] - target[None]), axis=0)  # [H,W]
H, W = target.shape
gf = np.take_along_axis(stack, kbest[None], axis=0)[0]    # [H,W] ground-following
with np.errstate(divide="ignore"): gf_db = 10*np.log10(gf)
gf_db[~np.isfinite(gf_db)] = np.nan

ext = [X.min(), X.max(), Y.min(), Y.max()]
fig, ax = plt.subplots(figsize=(13,12))
vmax=np.nanpercentile(gf_db,99); vmin=vmax-80
im=ax.imshow(gf_db, origin="lower", extent=ext, cmap="viridis", vmin=vmin, vmax=vmax,
             interpolation="nearest")
for b in buildings_xy: ax.plot(b[:,0],b[:,1],color="white",lw=0.25,alpha=0.3)
for t in towers:
    ax.scatter([t["x"]],[t["y"]],c="red",s=80,marker="^",edgecolors="white",zorder=5)
    ax.annotate(t["name"],(t["x"],t["y"]),color="white",fontsize=11,weight="bold",
                xytext=(8,8),textcoords="offset points")
ax.set_title("Newton, Barbados — 3.5 GHz best-server path gain, GROUND-FOLLOWING (1.5 m AGL, terrain)",fontsize=12)
ax.set_xlabel("x [m] (EPSG:21292 local)"); ax.set_ylabel("y [m]"); ax.set_aspect("equal")
cb=fig.colorbar(im,ax=ax,shrink=0.8,pad=0.02); cb.set_label("Path gain [dB]")
out=os.path.join(OUTDIR,"coverage_pathgain_db_terrain_groundfollow.png")
fig.savefig(out,dpi=130,bbox_inches="tight"); print("wrote",out)
print("DONE")
