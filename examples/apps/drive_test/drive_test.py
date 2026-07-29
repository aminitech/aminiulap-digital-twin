#!/usr/bin/env python3
"""
Drive-test replay -- animate a receiver moving through the twin, with live
best-server tracking and handover events.

    python examples/apps/drive_test/drive_test.py
    python examples/apps/drive_test/drive_test.py --freq-ghz 1.8 --frames 90 --out drive.gif

Writes a GIF and a CSV of the per-sample link budget. This is the analytical
counterpart of the pilot's ray-traced `docs/renders/moving_rx.gif`, and the same
harness you would use to validate handover thresholds -- swap the model for
`ulap-scope animate` when you need real multipath.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve()
EXAMPLES = next(p for p in HERE.parents if (p / "ulap_demo").is_dir())
sys.path[:0] = [str(EXAMPLES), str(EXAMPLES.parent / "ulap-scope")]

from ulap_demo import PropagationModel, load_scene  # noqa: E402
from ulap_demo.plotting import (  # noqa: E402
    MARBLE_WHITE, TOWER_COLORS, overlay_scene, use_ulap_style)

# A drive across the scene from the Newton side to the Rising Sun side -- the
# same route the ray-traced animation uses.
DEFAULT_ROUTE = [(-650, -880), (-300, -650), (0, -450), (300, -330),
                 (600, -250), (950, -160)]


def resample_route(waypoints, n_frames: int):
    """Linear interpolation along a polyline, evenly spaced in path length."""
    wp = np.asarray(waypoints, dtype=float)
    seg = np.hypot(*np.diff(wp, axis=0).T)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    t = np.linspace(0, s[-1], n_frames)
    return np.column_stack([np.interp(t, s, wp[:, 0]), np.interp(t, s, wp[:, 1])]), t


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--freq-ghz", type=float, default=3.5)
    ap.add_argument("--tx-power-dbm", type=float, default=33.0)
    ap.add_argument("--rx-height-m", type=float, default=1.5)
    ap.add_argument("--frames", type=int, default=60)
    ap.add_argument("--fps", type=int, default=10)
    ap.add_argument("--cell-m", type=float, default=15.0, help="backdrop map resolution")
    ap.add_argument("--speed-kmh", type=float, default=40.0,
                    help="assumed drive speed, used only to label time")
    ap.add_argument("--out", default="drive_test.gif")
    ap.add_argument("--csv", default=None, help="default: <out> with a .csv suffix")
    ap.add_argument("--no-terrain", action="store_true")
    args = ap.parse_args(argv)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation, PillowWriter

    use_ulap_style()
    scene = load_scene()
    model = PropagationModel(freq_hz=args.freq_ghz * 1e9, tx_power_dbm=args.tx_power_dbm,
                             rx_height_m=args.rx_height_m,
                             use_terrain=not args.no_terrain)
    towers = scene.towers_in_scene()
    print(f"scene   : {scene.name}, {len(scene.buildings)} buildings")
    print(f"model   : {model.describe()}")

    print("solving backdrop coverage ...")
    cov = model.coverage(scene, towers=towers, cell_m=args.cell_m)

    route, dist_along = resample_route(DEFAULT_ROUTE, args.frames)
    print(f"route   : {len(route)} samples over {dist_along[-1]:.0f} m")

    # Per-sample link budget to every tower (one vectorised call per tower).
    rx = np.stack([model.eirp_dbm + model.rx_gain_dbi
                   + model.path_gain_db(scene, t, route[:, 0], route[:, 1])
                   for t in towers])
    serving = np.argmax(rx, axis=0)
    best = np.max(rx, axis=0)
    lin = 10 ** (rx / 10.0)
    noise_mw = 10 ** (model.noise_dbm / 10.0)
    sinr = 10 * np.log10(np.max(lin, axis=0)
                         / (np.maximum(lin.sum(axis=0) - np.max(lin, axis=0), 0) + noise_mw))

    handovers = np.flatnonzero(np.diff(serving)) + 1
    print(f"handovers: {len(handovers)} at "
          f"{', '.join(f'{dist_along[i]:.0f} m' for i in handovers) or '—'}")

    # ---- CSV -------------------------------------------------------------
    csv_path = Path(args.csv) if args.csv else Path(args.out).with_suffix(".csv")
    speed_ms = args.speed_kmh / 3.6
    with open(csv_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["sample", "time_s", "distance_m", "x_m", "y_m", "serving_tower",
                    "best_rsrp_dbm", "sinr_db"]
                   + [f"rsrp_{t.slug}_dbm" for t in towers])
        for i in range(len(route)):
            w.writerow([i, f"{dist_along[i] / speed_ms:.2f}", f"{dist_along[i]:.1f}",
                        f"{route[i, 0]:.1f}", f"{route[i, 1]:.1f}",
                        towers[serving[i]].name, f"{best[i]:.2f}", f"{sinr[i]:.2f}"]
                       + [f"{rx[j, i]:.2f}" for j in range(len(towers))])
    print("wrote", csv_path)

    # ---- animation -------------------------------------------------------
    fig, (axm, axl) = plt.subplots(1, 2, figsize=(15, 6.6),
                                   gridspec_kw={"width_ratios": [1.15, 1]})
    top = float(np.percentile(cov.best_rsrp_dbm, 99.5))
    low = float(np.percentile(cov.best_rsrp_dbm, 1.0))
    axm.imshow(cov.best_rsrp_dbm, origin="lower", extent=cov.extent, cmap="viridis",
               vmin=low, vmax=top, interpolation="nearest", zorder=1)
    overlay_scene(axm, scene, building_alpha=0.22)
    axm.plot(route[:, 0], route[:, 1], color=MARBLE_WHITE, lw=1.0, alpha=0.35, zorder=4)
    axm.set_title(f"Drive test @ {args.freq_ghz:g} GHz")
    trail, = axm.plot([], [], lw=2.4, zorder=8)
    dot = axm.scatter([], [], s=110, c=MARBLE_WHITE, edgecolors="black",
                      linewidths=0.8, zorder=9)

    for j, t in enumerate(towers):
        axl.plot(dist_along, rx[j], lw=1.4, alpha=0.85,
                 color=TOWER_COLORS[j % len(TOWER_COLORS)], label=t.name)
    axl.plot(dist_along, best, lw=2.4, color=MARBLE_WHITE, alpha=0.9, label="best server")
    for i in handovers:
        axl.axvline(dist_along[i], color="#FF7A7A", ls="--", lw=1.1, alpha=0.8)
    axl.set_xlabel("distance along route [m]")
    axl.set_ylabel("RSRP [dBm]")
    axl.set_title("Live link budget — dashed = handover")
    axl.grid(alpha=0.25)
    axl.legend(fontsize=8.5, loc="lower right")
    cursor = axl.axvline(dist_along[0], color=MARBLE_WHITE, lw=1.2)
    readout = axl.text(0.02, 0.97, "", transform=axl.transAxes, fontsize=9,
                       family="monospace", color=MARBLE_WHITE, va="top",
                       bbox=dict(facecolor="#141414", edgecolor="#3A3A3A", pad=6))

    def update(i):
        c = TOWER_COLORS[serving[i] % len(TOWER_COLORS)]
        trail.set_data(route[:i + 1, 0], route[:i + 1, 1])
        trail.set_color(c)
        dot.set_offsets(route[i])
        cursor.set_xdata([dist_along[i], dist_along[i]])
        readout.set_text(f"t = {dist_along[i] / speed_ms:5.1f} s   "
                         f"d = {dist_along[i]:6.0f} m\n"
                         f"serving : {towers[serving[i]].name}\n"
                         f"RSRP    : {best[i]:7.1f} dBm\n"
                         f"SINR    : {sinr[i]:7.1f} dB")
        return trail, dot, cursor, readout

    fig.tight_layout()
    anim = FuncAnimation(fig, update, frames=len(route), interval=1000 / args.fps,
                         blit=False)
    print(f"rendering {len(route)} frames -> {args.out} ...")
    anim.save(args.out, writer=PillowWriter(fps=args.fps))
    print("wrote", args.out)

    print(f"\nsummary: RSRP {best.min():.1f} .. {best.max():.1f} dBm, "
          f"SINR median {np.median(sinr):.1f} dB, {len(handovers)} handover(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
