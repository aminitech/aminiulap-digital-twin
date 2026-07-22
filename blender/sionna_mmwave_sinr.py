#!/usr/bin/env python3
"""
sionna_mmwave_sinr.py
  (1) mmWave coverage with CONCRETE-ONLY materials (ITU concrete is defined
      1-100 GHz, so 28/60 GHz are physical; the ground's itu_medium_dry_ground
      is only valid <=10 GHz, hence we retag every surface to itu_concrete).
  (2) best-server SINR / interference map at 3.5 GHz with the multi-tower network.

    /opt/anaconda3/envs/sionna/bin/python sionna_mmwave_sinr.py
"""
import os, json
os.environ.setdefault("DRJIT_NO_RTLD_DEEPBIND", "1")
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import sionna.rt as rt
from sionna.rt import load_scene, PlanarArray, Transmitter, RadioMapSolver

HERE   = os.path.dirname(os.path.abspath(__file__))
SCENE  = os.path.join(HERE, "mitsuba_scene", "scene.xml")
OUTDIR = os.path.join(HERE, "sionna_out"); os.makedirs(OUTDIR, exist_ok=True)
mani   = json.load(open(os.path.join(HERE, "scene_build", "scene_manifest.json")))
towers = json.load(open(os.path.join(HERE, "scene_build", "towers_near.json")))
buildings_xy = [np.array(b["ring"]) for b in mani["buildings"]]
IN  = [t for t in towers if t["in_scene"]]
ALL = towers

def make_concrete_xml():
    """Write a concrete-only variant of scene.xml (ground retagged to itu_concrete,
    the itu_medium_dry_ground BSDF removed) so mmWave frequencies are valid for
    every surface. ITU concrete is defined 1-100 GHz; medium_dry_ground only <=10."""
    import xml.etree.ElementTree as ET
    out = os.path.join(os.path.dirname(SCENE), "scene_concrete.xml")
    tree = ET.parse(SCENE); root = tree.getroot()
    for bsdf in list(root.findall("bsdf")):
        if bsdf.get("id") == "mat-itu_medium_dry_ground":
            root.remove(bsdf)
    for ref in root.iter("ref"):
        if ref.get("id") == "mat-itu_medium_dry_ground":
            ref.set("id", "mat-itu_concrete")
    tree.write(out)
    return out

CONCRETE_XML = make_concrete_xml()

def base_scene(freq, tower_set, concrete_only=False, tx_power_dbm=None):
    sc = load_scene(CONCRETE_XML if concrete_only else SCENE)
    sc.frequency = freq
    sc.tx_array = PlanarArray(num_rows=1, num_cols=1, pattern="tr38901", polarization="V")
    sc.rx_array = PlanarArray(num_rows=1, num_cols=1, pattern="dipole",  polarization="V")
    for t in tower_set:
        tx = Transmitter(t["name"].lower().replace(" ", "_"),
                         [float(t["x"]), float(t["y"]), float(t["h"])])
        if tx_power_dbm is not None:
            tx.power_dbm = tx_power_dbm
        sc.add(tx)
    return sc

def solve(sc, cell=8.0, spp=10**6, depth=5):
    bb = sc.mi_scene.bbox()
    cx=float((bb.min[0]+bb.max[0])/2); cy=float((bb.min[1]+bb.max[1])/2)
    sx=float(bb.max[0]-bb.min[0]); sy=float(bb.max[1]-bb.min[1])
    return RadioMapSolver()(scene=sc, max_depth=depth, cell_size=(cell,cell),
                            samples_per_tx=spp, center=[cx,cy,1.5],
                            size=[sx,sy], orientation=[0.,0.,0.])

def ext(rm):
    cc=np.array(rm.cell_centers); return [cc[...,0].min(),cc[...,0].max(),cc[...,1].min(),cc[...,1].max()]

def overlay(ax, tower_set):
    for b in buildings_xy: ax.plot(b[:,0],b[:,1],color="white",lw=0.25,alpha=0.3)
    for t in tower_set:
        ax.scatter([t["x"]],[t["y"]],c="red",s=70,marker="^",edgecolors="white",zorder=5)
        ax.annotate(t["name"],(t["x"],t["y"]),color="white",fontsize=10,weight="bold",
                    xytext=(6,6),textcoords="offset points")

# ---------------------------------------------------- 1. mmWave concrete-only
print("== mmWave concrete-only coverage ==")
fig, axes = plt.subplots(1, 2, figsize=(22, 11))
for ax, f in zip(axes, [28e9, 60e9]):
    sc = base_scene(f, IN, concrete_only=True); rm = solve(sc)
    db = 10*np.log10(np.array(rm.path_gain).max(axis=0)); db[~np.isfinite(db)] = np.nan
    vmax=np.nanpercentile(db,99)
    im=ax.imshow(db,origin="lower",extent=ext(rm),cmap="inferno",vmin=vmax-90,vmax=vmax,
                 interpolation="nearest")
    overlay(ax, IN); ax.set_aspect("equal")
    ax.set_title(f"{f/1e9:.0f} GHz mmWave (concrete-only)  median {np.nanmedian(db):.0f} dB")
    ax.set_xlabel("x [m]"); ax.set_ylabel("y [m]")
    fig.colorbar(im, ax=ax, shrink=0.7, label="Path gain [dB]")
    print(f"   {f/1e9:.0f} GHz  median={np.nanmedian(db):.1f} dB  best={np.nanmax(db):.1f} dB")
fig.suptitle("Newton, Barbados — mmWave coverage, concrete-only materials (Sionna RT)", fontsize=14)
p1=os.path.join(OUTDIR,"mmwave_concrete_coverage.png"); fig.savefig(p1,dpi=115,bbox_inches="tight")
print("wrote", p1)

# ---------------------------------------------------- 2. SINR / interference
print("== best-server SINR @ 3.5 GHz (multi-tower, interference-limited) ==")
sc = base_scene(3.5e9, ALL, tx_power_dbm=33.0)      # 33 dBm ~ 2 W per sector
sc.bandwidth = 100e6                                 # 100 MHz -> thermal noise floor
rm = solve(sc, spp=10**6)
sinr = np.array(rm.sinr)                              # [num_tx,H,W], linear
sinr_best = sinr.max(axis=0)
with np.errstate(divide="ignore"): sinr_db = 10*np.log10(sinr_best)
sinr_db[~np.isfinite(sinr_db)] = np.nan
noise_dbm = 10*np.log10(float(np.array(sc.thermal_noise_power).ravel()[0])) + 30
print(f"   tx_power=33 dBm  BW=100 MHz  noise={noise_dbm:.1f} dBm  "
      f"SINR median={np.nanmedian(sinr_db):.1f} dB  max={np.nanmax(sinr_db):.1f} dB")

fig, ax = plt.subplots(figsize=(13,12))
im=ax.imshow(sinr_db,origin="lower",extent=ext(rm),cmap="RdYlGn",vmin=-5,vmax=30,
             interpolation="nearest")
overlay(ax, ALL); ax.set_aspect("equal")
ax.set_title("Newton, Barbados — best-server SINR @ 3.5 GHz (2W/sector, 100 MHz, interference-limited)",fontsize=12)
ax.set_xlabel("x [m] (EPSG:21292 local)"); ax.set_ylabel("y [m]")
cb=fig.colorbar(im,ax=ax,shrink=0.8,pad=0.02); cb.set_label("SINR [dB]")
# coverage stats
served = np.isfinite(sinr_db)
for thr in (0, 10, 20):
    frac = 100*np.mean(sinr_db[served] >= thr)
    print(f"   cells with SINR >= {thr:2d} dB: {frac:.1f}%")
p2=os.path.join(OUTDIR,"sinr_map.png"); fig.savefig(p2,dpi=130,bbox_inches="tight")
print("wrote", p2)
print("DONE")
