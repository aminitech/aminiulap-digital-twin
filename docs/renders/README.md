# Figure provenance

Every figure shown in the root [`README.md`](../../README.md) and referenced by
the paper, with the command that produces it and the solver parameters in
effect.

**How this was compiled.** Each row was read out of the stage script that writes
the filename — not from memory or from the figures themselves. Anything that
could not be established from code is marked `unverified` rather than guessed.

> ⚠️ **These figures are not currently bit-reproducible.** Seven of the eight
> ray-tracing solver invocations run unseeded Monte Carlo (see
> [REPOSITORY_AUDIT.md](../REPOSITORY_AUDIT.md#-critical-finding-ray-traced-results-are-not-reproducible)).
> Re-running a stage produces a statistically similar but not identical map, and
> the run-to-run variance has **not been measured**. Treat the rows below as "the
> command that produced this figure", not yet as "the command that reproduces
> this figure".

All ray-traced figures were produced from the **Barbados Geoportal** study
(Newton / Rising Sun, EPSG:21292). That data is not redistributable — see
[DATA.md](../../DATA.md). To generate the equivalent figures for a study area you
can share, build a scene with `examples/data/fetch_open_scene.py` first.

---

## Ray-traced figures

| Figure | Stage command | Source script | Cell | `max_depth` | `samples_per_tx` | Frequency | Notes |
|---|---|---|---|---|---|---|---|
| `coverage_map_terrain.png` | `ulap-scope coverage --mode terrain` | `stages/sionna_coverage.py:94` | 5.0 m | 5 | 10⁷ | 3.5 GHz | Radio map over the terrain-draped scene |
| `coverage_pathgain_db_terrain.png` | `ulap-scope coverage --mode terrain` | `stages/sionna_coverage.py:142` | 5.0 m | 5 | 10⁷ | 3.5 GHz | Path gain, terrain drape |
| `scene_render_terrain.png` | `ulap-scope coverage --mode terrain` | `stages/sionna_coverage.py:100` | — | — | — | — | Mitsuba scene render, not a radio map |
| `coverage_pathgain_db_terrain_groundfollow.png` | `ulap-scope terrain-ground` | `stages/sionna_terrain_ground.py:84` | 8.0 m | 5 | 10⁶ | 3.5 GHz | **Ground-following at 1.5 m AGL** (`RXH = 1.5`, `K = 9` sampling planes). The map planning decisions should be read from. |
| `sweep_frequency.png` | `ulap-scope analysis` | `stages/sionna_analysis.py:87` | 8.0 m | 5 | 10⁶ | 1.8 / 3.5 / 6.0 / 10.0 GHz | Four-panel sweep; upper bound set by the `itu_medium_dry_ground` 1–10 GHz validity window |
| `multitower_bestserver_handover.png` | `ulap-scope analysis` | `stages/sionna_analysis.py:120` | 8.0 m | 5 | 10⁶ | 3.5 GHz | Best-server association across all towers |
| `link_metrics.png` | `ulap-scope analysis` | `stages/sionna_analysis.py:171` | — | 6 | — | 3.5 GHz | `PathSolver`, TX = Rising Sun, receivers at `np.arange(50, 1400, 100)` m toward scene centre, RX height 1.5 m. Raw values in `link_metrics.csv`. |
| `mmwave_concrete_coverage.png` | `ulap-scope mmwave-sinr` | `stages/sionna_mmwave_sinr.py:92` | 8.0 m | 5 | 10⁶ | 28 / 60 GHz | Concrete-only scene variant — the ground BSDF is removed so mmWave stays inside material validity |
| `sinr_map.png` | `ulap-scope mmwave-sinr` | `stages/sionna_mmwave_sinr.py:120` | 8.0 m | 5 | 10⁶ | 3.5 GHz | 33 dBm/sector, 100 MHz bandwidth (`sionna_mmwave_sinr.py:97–98`) |
| `moving_rx.gif` | `ulap-scope animate` | `stages/sionna_animate_rx.py:94` | 10.0 m | 5 (map) / 6 (paths) | 10⁶ | 3.5 GHz | Drive-test replay over a coverage backdrop |

## Rendered figures (not ray-traced)

| Figure | Command | Source script | Notes |
|---|---|---|---|
| `blender_perspective.png` | `blender --background <scene>.blend --python blender/render_perspective.py` | `blender/render_perspective.py:15` | Blender render of the built scene. PNG metadata was stripped on 2026-07-29 (it carried an absolute path); pixels unchanged. |
| `persp_paths.png` | `blender/render_sionna_perspective.py` | `render_sionna_perspective.py` | Perspective view with ray paths |
| `persp_radiomap.png` | `blender/render_sionna_perspective.py` | `render_sionna_perspective.py` | Perspective view with the radio map draped |

---

## ⚠️ Solver parameters are hard-coded per stage, not read from config

`docs/ARCHITECTURE.md` states the principle *"Config over code. All
physics/geometry parameters (CRS, origin, bbox, …)"* are centralised in
`ulap_scope/config.py`. For **solver** parameters this is currently not the case:

| Parameter | `config.py` | Actually used |
|---|---|---|
| `samples_per_tx` | `10**6` (line 45) | `10**7` in `sionna_coverage.py:74`; `10**6` elsewhere |
| `cell_size_m` | `5.0` (line 43) | `5.0` coverage · `8.0` analysis, mmwave, terrain-ground · `10.0` animate |
| `max_depth` | `5` (line 44) | `5`, except `6` for `PathSolver` in analysis and animate |

The values in the table above are the ones **actually used**, read from the stage
scripts. Changing `config.py` will not change these figures. Reconciling this is
item 2.4 in [IMPROVEMENT_PLAN.md](../IMPROVEMENT_PLAN.md); it is recorded here so
the discrepancy is visible to anyone attempting reproduction.

---

## Reproducing these

1. Obtain the Barbados Geoportal layers (see [DATA.md](../../DATA.md)) and set
   `ULAP_DATA_DIR`.
2. Set up the three environments — `ulap-scope/README.md`.
3. `ulap-scope clip && ulap-scope preprocess && ulap-scope basemap`
4. `ulap-scope build --mode terrain && ulap-scope export --mode terrain`
5. Run the stage from the table above.

Outputs land in `blender/sionna_out/` (untracked — a working directory). The
copies in `docs/renders/` are curated for the README.

**No runtime or memory figures are published yet** — measuring them is item 1.4
in the improvement plan. Nothing here should be read as a claim about how long
reproduction takes.
