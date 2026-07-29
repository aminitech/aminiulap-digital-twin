"""
ulap_demo.plotting -- one consistent look for every demo figure.

Dark background, Ulap sunglow accent, buildings as hairlines, towers as
triangles: the same visual language as ``docs/renders/``, so a figure you make
here sits next to a ray-traced one without a jarring switch.
"""
from __future__ import annotations

import numpy as np

# Ulap brand palette (see brandkit/)
SPACE_BLACK = "#121212"
EERIE = "#1A1A1A"
MARBLE_WHITE = "#FFFFFF"
SUNGLOW = "#FFC83C"
MUTED = "#8A8A8A"

TOWER_COLORS = ["#FFC83C", "#4FC3F7", "#FF7A7A", "#8BE28B", "#C08BFF"]


def use_ulap_style():
    """Apply the dark Ulap matplotlib style. Call once per notebook."""
    import matplotlib as mpl

    mpl.rcParams.update({
        "figure.facecolor": SPACE_BLACK,
        "axes.facecolor": EERIE,
        "savefig.facecolor": SPACE_BLACK,
        "text.color": MARBLE_WHITE,
        "axes.labelcolor": MARBLE_WHITE,
        "axes.edgecolor": "#3A3A3A",
        "axes.titlecolor": MARBLE_WHITE,
        "axes.titleweight": "semibold",
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "grid.color": "#2E2E2E",
        "grid.alpha": 0.6,
        "legend.facecolor": "#1E1E1E",
        "legend.edgecolor": "#3A3A3A",
        "figure.dpi": 110,
        "font.size": 10,
    })


def overlay_scene(ax, scene, buildings: bool = True, towers: bool = True,
                  building_alpha: float = 0.30, label_towers: bool = True,
                  clip_to_scene: bool = True):
    """Draw building footprints and tower markers on an existing map axis.

    ``clip_to_scene`` keeps the view on the study box: the tower registry
    includes sites well outside it, and letting matplotlib autoscale to those
    shrinks the map to a postage stamp."""
    if buildings:
        for ring in scene.building_rings():
            ax.plot(ring[:, 0], ring[:, 1], color=MARBLE_WHITE, lw=0.25,
                    alpha=building_alpha, zorder=3)
    if towers:
        for i, t in enumerate(scene.towers):
            c = TOWER_COLORS[i % len(TOWER_COLORS)] if t.in_scene else MUTED
            ax.scatter([t.x], [t.y], marker="^", s=90, c=c, edgecolors=SPACE_BLACK,
                       linewidths=0.8, zorder=6)
            if label_towers:
                ax.annotate(f"{t.name} · {t.h:.0f} m", (t.x, t.y), color=c,
                            fontsize=8.5, weight="bold", xytext=(7, 6),
                            textcoords="offset points", zorder=7)
    if clip_to_scene:
        minx, maxx, miny, maxy = scene.bounds
        ax.set_xlim(minx, maxx)
        ax.set_ylim(miny, maxy)
    ax.set_aspect("equal")
    ax.set_xlabel("x [m from scene origin]")
    ax.set_ylabel("y [m]")
    return ax


def plot_map(ax, values, extent, scene=None, cmap="viridis", vmin=None, vmax=None,
             title=None, cbar_label=None, **overlay_kw):
    """Show a scalar grid as a map, with the scene overlaid and a colour bar."""
    import matplotlib.pyplot as plt

    im = ax.imshow(values, origin="lower", extent=extent, cmap=cmap,
                   vmin=vmin, vmax=vmax, interpolation="nearest", zorder=1)
    if scene is not None:
        overlay_scene(ax, scene, **overlay_kw)
    if title:
        ax.set_title(title)
    cb = plt.colorbar(im, ax=ax, fraction=0.046, pad=0.02)
    if cbar_label:
        cb.set_label(cbar_label)
    cb.ax.yaxis.set_tick_params(color=MUTED)
    return im, cb


def plot_coverage(ax, cov, scene=None, dynamic_range_db: float = 90.0, **kw):
    """Best-server RSRP map.

    The colour range is the 0.5–99.5 percentile span, clamped to at most
    ``dynamic_range_db`` below the peak. A fixed range washes out a
    well-covered scene; a pure percentile range exaggerates a poorly covered
    one. This does both."""
    top = float(np.nanpercentile(cov.best_rsrp_dbm, 99.5))
    low = float(np.nanpercentile(cov.best_rsrp_dbm, 0.5))
    return plot_map(ax, cov.best_rsrp_dbm, cov.extent, scene=scene, cmap="viridis",
                    vmin=max(top - dynamic_range_db, low), vmax=top,
                    title=kw.pop("title", "Best-server RSRP"),
                    cbar_label="RSRP [dBm]", **kw)


def plot_sinr(ax, cov, scene=None, vmin: float = -10.0, vmax: float = 30.0, **kw):
    return plot_map(ax, cov.sinr_db, cov.extent, scene=scene, cmap="RdYlGn",
                    vmin=vmin, vmax=vmax, title=kw.pop("title", "SINR"),
                    cbar_label="SINR [dB]", **kw)


def plot_best_server(ax, cov, scene=None, title="Best server (handover map)", **kw):
    """Which tower wins each cell -- the handover boundary made visible."""
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap
    from matplotlib.patches import Patch

    n = len(cov.tower_names)
    colors = [TOWER_COLORS[i % len(TOWER_COLORS)] for i in range(n)]
    im = ax.imshow(cov.best_server, origin="lower", extent=cov.extent,
                   cmap=ListedColormap(colors), vmin=-0.5, vmax=n - 0.5,
                   interpolation="nearest", zorder=1)
    if scene is not None:
        overlay_scene(ax, scene, label_towers=False, **kw)
    ax.set_title(title)
    ax.legend(handles=[Patch(color=colors[i], label=cov.tower_names[i])
                       for i in range(n)], loc="upper left", fontsize=8.5,
              framealpha=0.75)
    return im


def plot_terrain(ax, scene, cmap="terrain", title="Terrain (LiDAR DTM)", **kw):
    z = scene.terrain_z_grid
    return plot_map(ax, z, scene.extent, scene=scene, cmap=cmap, title=title,
                    cbar_label="elevation [m]", **kw)


def plot_profile(ax, distances, ground, top, ray=None, title=None):
    """Terrain/building profile under a link, with the ray drawn over it."""
    ax.fill_between(distances, 0, ground, color="#4A4A4A", zorder=1,
                    label="terrain")
    ax.fill_between(distances, ground, top, color="#6E6E6E", zorder=2,
                    step="mid", label="buildings")
    if ray is not None:
        ax.plot(distances, ray, color=SUNGLOW, lw=1.6, zorder=4, label="line of sight")
    ax.set_xlabel("distance from transmitter [m]")
    ax.set_ylabel("height [m]")
    ax.set_ylim(bottom=float(np.min(ground)) - 5)
    if title:
        ax.set_title(title)
    ax.legend(fontsize=8.5, loc="best")
    ax.grid(alpha=0.2)
    return ax
