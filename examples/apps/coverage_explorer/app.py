"""
Ulap Coverage Explorer -- an interactive RF planning sandbox for the pilot twin.

    pip install streamlit matplotlib numpy
    streamlit run examples/apps/coverage_explorer/app.py

Move a tower, change band, switch terrain off, and watch coverage and SINR
recompute in well under a second. The maps come from the analytical model in
`ulap_demo.propagation`, not from Sionna RT -- see the banner in the app.
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import streamlit as st

# --- make ulap_demo / ulap_scope importable from a bare checkout -------------
HERE = Path(__file__).resolve()
EXAMPLES = next(p for p in HERE.parents if (p / "ulap_demo").is_dir())
sys.path[:0] = [str(EXAMPLES), str(EXAMPLES.parent / "ulap-scope")]

from ulap_demo import PropagationModel, load_scene  # noqa: E402
from ulap_demo.plotting import (  # noqa: E402
    SUNGLOW, plot_best_server, plot_coverage, plot_map, plot_sinr, use_ulap_style)
from ulap_demo.scene import Tower  # noqa: E402

st.set_page_config(page_title="Ulap Coverage Explorer", page_icon="📡", layout="wide")
use_ulap_style()


@st.cache_resource
def get_scene():
    return load_scene()


scene = get_scene()
BASE_TOWERS = scene.towers_in_scene()


@st.cache_data(show_spinner=False)
def compute(params: tuple, towers: tuple, cell_m: float):
    """Cached coverage solve. Both arguments are plain tuples so Streamlit can
    hash them; the scene itself is a cached resource."""
    (freq_ghz, tx_dbm, tx_gain, bw_mhz, nf_db, rx_h,
     use_terrain, use_buildings, refl) = params
    model = PropagationModel(
        freq_hz=freq_ghz * 1e9, tx_power_dbm=tx_dbm, tx_gain_dbi=tx_gain,
        bandwidth_hz=bw_mhz * 1e6, noise_figure_db=nf_db, rx_height_m=rx_h,
        use_terrain=use_terrain, use_buildings=use_buildings, ground_reflection=refl)
    tw = [Tower(name=n, x=x, y=y, h=h, ground_z=gz) for n, x, y, h, gz in towers]
    return model, model.coverage(scene, towers=tw, cell_m=cell_m)


# ---------------------------------------------------------------- sidebar
st.sidebar.title("📡 Ulap Coverage Explorer")
st.sidebar.caption(f"{scene.name} · {len(scene.buildings)} buildings · "
                   f"{scene.terrain['zmax'] - scene.terrain['zmin']:.0f} m of relief")

st.sidebar.subheader("Radio")
freq_ghz = st.sidebar.select_slider(
    "Band [GHz]", options=[0.7, 1.8, 3.5, 6.0, 10.0, 28.0, 60.0], value=3.5)
tx_dbm = st.sidebar.slider("TX power [dBm]", 10.0, 50.0, 33.0, 1.0,
                           help="33 dBm = 2 W, the pilot study's per-site power")
tx_gain = st.sidebar.slider("Antenna gain [dBi]", 0.0, 24.0, 8.0, 0.5)
bw_mhz = st.sidebar.select_slider("Bandwidth [MHz]", options=[5, 10, 20, 50, 100, 200, 400],
                                  value=100)
nf_db = st.sidebar.slider("Receiver noise figure [dB]", 2.0, 12.0, 7.0, 0.5)
rx_h = st.sidebar.slider("Receiver height [m]", 1.0, 30.0, 1.5, 0.5,
                         help="1.5 m is handset height — the level planning decisions "
                              "should be read at")

st.sidebar.subheader("Physics")
use_terrain = st.sidebar.checkbox("Terrain", True)
use_buildings = st.sidebar.checkbox("Buildings", True)
refl = st.sidebar.radio("Ground reflection", ["average", "coherent", "none"], index=0,
                        help="'coherent' shows the true two-ray fringes; a coarse grid "
                             "will alias them")
cell_m = st.sidebar.select_slider("Grid resolution [m]", options=[5, 10, 20, 40], value=10)

st.sidebar.subheader("Thresholds")
rsrp_thr = st.sidebar.slider("Coverage threshold [dBm]", -130, -60, -95, 1)
sinr_thr = st.sidebar.slider("SINR threshold [dB]", -10, 30, 0, 1)

# ---- towers ----
st.sidebar.subheader("Sites")
towers: list[tuple] = []
for t in BASE_TOWERS:
    on = st.sidebar.checkbox(f"{t.name} ({t.structure})", True, key=f"on_{t.slug}")
    if on:
        h = st.sidebar.slider(f"↳ {t.name} height [m]", 5.0, 80.0, float(t.h), 1.0,
                              key=f"h_{t.slug}")
        towers.append((t.name, t.x, t.y, h, t.ground_z))

if st.sidebar.checkbox("Add a candidate site", False):
    cx = st.sidebar.slider("↳ x [m]", -1000, 1000, 250, 10)
    cy = st.sidebar.slider("↳ y [m]", -1000, 1000, 350, 10)
    ch = st.sidebar.slider("↳ height [m]", 5.0, 80.0, 25.0, 1.0)
    towers.append(("Candidate", float(cx), float(cy), float(ch),
                   float(scene.terrain_z(float(cx), float(cy)))))

if not towers:
    st.error("Enable at least one site in the sidebar.")
    st.stop()

params = (freq_ghz, tx_dbm, tx_gain, bw_mhz, nf_db, rx_h,
          use_terrain, use_buildings, refl)
model, cov = compute(params, tuple(towers), float(cell_m))

# ---------------------------------------------------------------- header
st.title("Coverage & SINR — analytical twin")
st.caption(
    "⚠️ Fast analytical model (free space + two-ray + knife-edge diffraction). "
    "**Not** a ray tracer: no multi-bounce, no material-specific reflection, no delay "
    "spread. Use it to explore and size; run `ulap-scope coverage` for the real thing.")

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Median RSRP", f"{np.median(cov.best_rsrp_dbm):.1f} dBm")
c2.metric("5th pct RSRP", f"{np.percentile(cov.best_rsrp_dbm, 5):.1f} dBm",
          help="the cell edge — the number that sizes your network")
c3.metric(f"Area ≥ {rsrp_thr} dBm", f"{100 * cov.fraction_above(rsrp_thr):.1f} %")
c4.metric(f"Area SINR ≥ {sinr_thr} dB", f"{100 * cov.fraction_sinr_above(sinr_thr):.1f} %")
c5.metric("Noise floor", f"{model.noise_dbm:.1f} dBm")

tab_cov, tab_sinr, tab_srv, tab_stats, tab_about = st.tabs(
    ["Coverage", "SINR", "Best server", "Statistics", "About"])

with tab_cov:
    left, right = st.columns([3, 2])
    with left:
        fig, ax = plt.subplots(figsize=(7.5, 7))
        plot_coverage(ax, cov, scene=scene,
                      title=f"Best-server RSRP @ {freq_ghz:g} GHz")
        st.pyplot(fig)
    with right:
        fig, ax = plt.subplots(figsize=(6, 6.4))
        served = np.where(cov.best_rsrp_dbm >= rsrp_thr, 1.0, 0.0)
        plot_map(ax, served, cov.extent, scene=scene, cmap="cividis", vmin=0, vmax=1,
                 title=f"Served at ≥ {rsrp_thr} dBm", cbar_label="served",
                 label_towers=False)
        st.pyplot(fig)
        st.write(f"**{cov.served_area_km2(rsrp_thr):.2f} km²** of "
                 f"{cov.cell_area_km2 * cov.best_rsrp_dbm.size:.2f} km² served.")

with tab_sinr:
    fig, ax = plt.subplots(figsize=(8, 7))
    plot_sinr(ax, cov, scene=scene,
              title=f"SINR — {len(towers)} site(s), {bw_mhz} MHz")
    st.pyplot(fig)
    st.info(
        "Red seams are cell edges, not coverage holes. Adding a site usually raises RSRP "
        "and *lowers* median SINR — the fix for an interference-limited edge is tilt, "
        "power and reuse.")

with tab_srv:
    fig, ax = plt.subplots(figsize=(8, 7))
    plot_best_server(ax, cov, scene=scene)
    st.pyplot(fig)
    st.write("**Best-server share of area**")
    st.table({name: [f"{100 * frac:.1f} %"] for name, frac in cov.server_share().items()})

with tab_stats:
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.6))
    vals = np.sort(cov.best_rsrp_dbm.ravel())
    axes[0].plot(vals, 100 * np.arange(1, vals.size + 1) / vals.size, color=SUNGLOW, lw=2)
    axes[0].axvline(rsrp_thr, color="w", ls=":", lw=1)
    axes[0].set_xlabel("best-server RSRP [dBm]")
    axes[0].set_ylabel("% of area below")
    axes[0].set_title("Coverage CDF")
    axes[0].grid(alpha=0.25)

    s = np.sort(cov.sinr_db.ravel())
    axes[1].plot(s, 100 * np.arange(1, s.size + 1) / s.size, color="#4FC3F7", lw=2)
    axes[1].axvline(sinr_thr, color="w", ls=":", lw=1)
    axes[1].set_xlabel("SINR [dB]")
    axes[1].set_ylabel("% of area below")
    axes[1].set_title("SINR CDF")
    axes[1].grid(alpha=0.25)
    st.pyplot(fig)

    st.text(cov.summary(rsrp_threshold_dbm=rsrp_thr, sinr_threshold_db=sinr_thr))
    st.download_button(
        "⬇ Download best-server RSRP as CSV",
        data="\n".join(",".join(f"{v:.2f}" for v in row) for row in cov.best_rsrp_dbm),
        file_name=f"rsrp_{freq_ghz:g}GHz_{cell_m}m.csv", mime="text/csv")

with tab_about:
    st.markdown(f"""
### What this is

The **Newton / Rising Sun pilot scene** from the Ulap digital twin — 576 building
footprints at LiDAR heights over a 70×70 terrain grid — with an analytical propagation
model fast enough to be interactive.

```
{model.describe()}
```

### What it is not

A ray tracer. There is no multi-bounce specular chain, no material-dependent reflection
or transmission, no diffuse scattering, and no delay domain at all. On a clear rural
radial this model matches Sionna RT's path-loss exponent to within 0.05 (see
`examples/notebooks/02_link_budget.ipynb`); in dense multipath it will not.

### Getting the real numbers

```bash
cd ulap-scope
pip install -e .
ulap-scope init          # define your own study
ulap-scope all           # clip → build → export → ray-trace
```

The ray-traced results for this scene live in `docs/renders/`.
""")
