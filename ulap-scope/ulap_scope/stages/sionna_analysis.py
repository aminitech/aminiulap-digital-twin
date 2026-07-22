#!/usr/bin/env python3
"""
sionna_analysis.py -- advanced RT analysis on the flat Newton scene:
  (1) frequency sweep of best-server coverage,
  (2) multi-tower best-server + serving-cell (handover) map,
  (3) per-link path gain + RMS delay spread along a transect.

Run in the sionna env:
    /opt/anaconda3/envs/sionna/bin/python sionna_analysis.py
"""
import os, json, time
os.environ.setdefault("DRJIT_NO_RTLD_DEEPBIND", "1")
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import sionna.rt as rt
from sionna.rt import (load_scene, PlanarArray, Transmitter, Receiver,
                       PathSolver, RadioMapSolver)

HERE = os.environ.get("ULAP_WORK_DIR") or os.path.dirname(os.path.abspath(__file__))
SCENE  = os.path.join(HERE, "mitsuba_scene", "scene.xml")
OUTDIR = os.path.join(HERE, "sionna_out"); os.makedirs(OUTDIR, exist_ok=True)
mani   = json.load(open(os.path.join(HERE, "scene_build", "scene_manifest.json")))
towers = json.load(open(os.path.join(HERE, "scene_build", "towers_near.json")))
buildings_xy = [np.array(b["ring"]) for b in mani["buildings"]]
IN = [t for t in towers if t["in_scene"]]          # 2 in-scene towers
ALL = towers                                        # + external cells

def fresh(freq_hz, tower_set):
    sc = load_scene(SCENE); sc.frequency = freq_hz
    sc.tx_array = PlanarArray(num_rows=1, num_cols=1, pattern="tr38901", polarization="V")
    sc.rx_array = PlanarArray(num_rows=1, num_cols=1, pattern="dipole",  polarization="V")
    for t in tower_set:
        sc.add(Transmitter(name=t["name"].lower().replace(" ", "_"),
                            position=[float(t["x"]), float(t["y"]), float(t["h"])]))
    return sc

def solve_map(sc, cell=8.0, spp=10**6, depth=5):
    bb = sc.mi_scene.bbox()
    cx = float((bb.min[0]+bb.max[0])/2); cy = float((bb.min[1]+bb.max[1])/2)
    sx = float(bb.max[0]-bb.min[0]);     sy = float(bb.max[1]-bb.min[1])
    rm = RadioMapSolver()(scene=sc, max_depth=depth, cell_size=(cell, cell),
                          samples_per_tx=spp, center=[cx, cy, 1.5],
                          size=[sx, sy], orientation=[0., 0., 0.])
    return rm

def extent_of(rm):
    cc = np.array(rm.cell_centers)
    return [cc[...,0].min(), cc[...,0].max(), cc[...,1].min(), cc[...,1].max()]

def overlay(ax):
    for b in buildings_xy:
        ax.plot(b[:,0], b[:,1], color="white", lw=0.25, alpha=0.30)
    for t in ALL:
        ins = t["in_scene"]
        ax.scatter([t["x"]],[t["y"]], c="red" if ins else "orange", s=70,
                   marker="^", edgecolors="white", zorder=5)
        ax.annotate(t["name"], (t["x"],t["y"]), color="white", fontsize=9,
                    xytext=(6,6), textcoords="offset points", weight="bold")

# ------------------------------------------------------------------ 1. sweep
# ITU material validity: medium_dry_ground is defined 1-10 GHz (concrete 1-100).
# Stay inside the ground material's range so both materials are physical.
FREQS = [1.8e9, 3.5e9, 6.0e9, 10.0e9]
print("== frequency sweep ==")
fig, axes = plt.subplots(2, 2, figsize=(15, 14))
vmax_g, vmin_g = None, None
maps = []
for f in FREQS:
    sc = fresh(f, IN); rm = solve_map(sc)
    pg = np.array(rm.path_gain).max(axis=0)
    with np.errstate(divide="ignore"): db = 10*np.log10(pg)
    db[~np.isfinite(db)] = np.nan
    maps.append((f, db, extent_of(rm)))
    v = np.nanpercentile(db, 99)
    vmax_g = v if vmax_g is None else max(vmax_g, v)
vmax_g = float(vmax_g); vmin_g = vmax_g - 90
for ax, (f, db, ext) in zip(axes.ravel(), maps):
    im = ax.imshow(db, origin="lower", extent=ext, cmap="viridis",
                   vmin=vmin_g, vmax=vmax_g, interpolation="nearest")
    overlay(ax); ax.set_aspect("equal")
    frac = np.mean(db > (vmax_g-90+40))    # % cells above ~ -50 dB rel
    ax.set_title(f"{f/1e9:.1f} GHz   (median {np.nanmedian(db):.0f} dB)", fontsize=12)
    ax.set_xlabel("x [m]"); ax.set_ylabel("y [m]")
fig.suptitle("Newton, Barbados — best-server path gain vs frequency (Sionna RT, flat)", fontsize=14)
cb = fig.colorbar(im, ax=axes, shrink=0.6, pad=0.02); cb.set_label("Path gain [dB]")
p1 = os.path.join(OUTDIR, "sweep_frequency.png"); fig.savefig(p1, dpi=115, bbox_inches="tight")
print("wrote", p1)
for f, db, _ in maps:
    print(f"   {f/1e9:.1f} GHz  median={np.nanmedian(db):.1f} dB  best={np.nanmax(db):.1f} dB")

# ------------------------------------------------------------------ 2. multi-tower + handover
print("== multi-tower best-server + handover ==")
sc = fresh(3.5e9, ALL); rm = solve_map(sc, spp=10**6)
pg = np.array(rm.path_gain)                       # [num_tx,H,W]
best = pg.max(axis=0)
with np.errstate(divide="ignore"): best_db = 10*np.log10(best)
best_db[~np.isfinite(best_db)] = np.nan
serving = np.array(rm.tx_association("path_gain"))   # serving tx index per cell (method)
ext = extent_of(rm)
names = [t["name"] for t in ALL]

fig, (a1, a2) = plt.subplots(1, 2, figsize=(22, 11))
im1 = a1.imshow(best_db, origin="lower", extent=ext, cmap="viridis",
                vmin=np.nanpercentile(best_db,99)-90, vmax=np.nanpercentile(best_db,99),
                interpolation="nearest")
overlay(a1); a1.set_aspect("equal"); a1.set_title("Best-server path gain @ 3.5 GHz (4 towers)")
a1.set_xlabel("x [m]"); a1.set_ylabel("y [m]")
cb1 = fig.colorbar(im1, ax=a1, shrink=0.7); cb1.set_label("Path gain [dB]")

serv = serving.astype(float); serv[serving < 0] = np.nan
im2 = a2.imshow(serv, origin="lower", extent=ext, cmap="tab10", vmin=0, vmax=10,
                interpolation="nearest")
overlay(a2); a2.set_aspect("equal"); a2.set_title("Serving cell (best-server association / handover)")
a2.set_xlabel("x [m]"); a2.set_ylabel("y [m]")
from matplotlib.patches import Patch
cmap = plt.get_cmap("tab10")
a2.legend(handles=[Patch(color=cmap(i), label=names[i]) for i in range(len(names))],
          loc="upper left", fontsize=9, framealpha=0.6)
p2 = os.path.join(OUTDIR, "multitower_bestserver_handover.png")
fig.savefig(p2, dpi=115, bbox_inches="tight"); print("wrote", p2)

# ------------------------------------------------------------------ 3. per-link metrics (transect)
print("== path gain + delay spread transect (TX = Rising Sun) ==")
tx = [t for t in ALL if t["name"] == "Rising Sun"][0]
sc = load_scene(SCENE); sc.frequency = 3.5e9
sc.tx_array = PlanarArray(num_rows=1, num_cols=1, pattern="tr38901", polarization="V")
sc.rx_array = PlanarArray(num_rows=1, num_cols=1, pattern="dipole",  polarization="V")
sc.add(Transmitter("rising_sun", [float(tx["x"]), float(tx["y"]), float(tx["h"])]))
# receivers on a line from the tower toward scene centre, at 1.5 m
dirx, diry = -tx["x"], -tx["y"]; L = (dirx**2+diry**2)**0.5; ux, uy = dirx/L, diry/L
dists = np.arange(50, 1400, 100)
rxpos = [(tx["x"]+ux*d, tx["y"]+uy*d) for d in dists]
for i,(rx,ry) in enumerate(rxpos):
    sc.add(Receiver(f"rx{i}", [float(rx), float(ry), 1.5]))
paths = PathSolver()(scene=sc, max_depth=6, los=True, specular_reflection=True,
                     diffuse_reflection=True, refraction=True, synthetic_array=False)
a, tau = paths.cir()                              # a:[2,num_rx,1,1,1,P,1]  tau:[num_rx,1,P]
a = np.asarray(a); tau = np.asarray(tau)
ac = a[0] + 1j*a[1]                               # complex, [num_rx,1,1,1,P,1]
rows = []
for i, d in enumerate(dists):
    coeff = ac[i].reshape(-1, ac.shape[-2]) if ac.ndim>2 else ac[i]
    p = (np.abs(ac[i])**2).reshape(-1)            # per-path power (flatten ant dims)
    tt = np.asarray(tau[i]).reshape(-1)
    m = np.isfinite(tt) & (p > 0)
    p, tt = p[m], tt[m]
    if p.sum() <= 0:
        rows.append((d, np.nan, np.nan, 0)); continue
    gain_db = 10*np.log10(p.sum())
    tbar = np.sum(p*tt)/np.sum(p)
    ds = np.sqrt(np.sum(p*(tt-tbar)**2)/np.sum(p))
    rows.append((d, gain_db, ds*1e9, int(len(p))))    # ds in ns

csv = os.path.join(OUTDIR, "link_metrics.csv")
with open(csv, "w") as f:
    f.write("distance_m,path_gain_dB,delay_spread_ns,num_paths\n")
    for d,g,ds,n in rows: f.write(f"{d},{g:.2f},{ds:.2f},{n}\n")
print("wrote", csv)
for d,g,ds,n in rows: print(f"   d={d:>4} m  gain={g:6.1f} dB  DS={ds:6.1f} ns  paths={n}")

# figure
dd = [r[0] for r in rows]; gg=[r[1] for r in rows]; ss=[r[2] for r in rows]
fig, ax1 = plt.subplots(figsize=(11,6))
ax1.plot(dd, gg, "o-", color="#1f77b4", label="path gain")
ax1.set_xlabel("distance from Rising Sun tower [m]"); ax1.set_ylabel("path gain [dB]", color="#1f77b4")
ax2 = ax1.twinx(); ax2.plot(dd, ss, "s--", color="#d62728", label="delay spread")
ax2.set_ylabel("RMS delay spread [ns]", color="#d62728")
ax1.set_title("Rising Sun link @ 3.5 GHz — path gain & delay spread vs distance")
ax1.grid(alpha=0.3)
p3 = os.path.join(OUTDIR, "link_metrics.png"); fig.savefig(p3, dpi=120, bbox_inches="tight")
print("wrote", p3)
print("DONE")
