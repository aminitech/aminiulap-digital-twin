# Ulap Digital Twin — 6G Propagation Studies

Reproducible **radio-frequency digital twins** for 6G deployment planning. National
geoportal shapefiles + satellite imagery + LiDAR building heights go in; ray-traced
coverage, SINR, mmWave and drive-test studies come out — via **BlenderGIS → Mitsuba →
NVIDIA Sionna RT**, all on CPU. Part of the **Ulap One** project (Amini).

```
     ((♥))                                                  ((♥))
       |            ~  ♥  ~          ~  ♥  ~                  |
      /|\        ♥              ~♥~              ♥           /|\
     / | \          ~   ~                       ~   ~       / | \
    /  |  \                                                /  |  \
   /___|___\             _________________                /___|___\
     NEWTON             | .-------------. |              RISING SUN
      30 m              | |  ulap  ♥ ♥  | |                 24 m
                        | '-------------' |
                        '-----------------'
                         /:::::::::::::::\
                        '-----------------'
```

The pilot study twins the **Newton / Rising Sun** area of south-central Barbados
(2 km box, 576 LiDAR-height buildings, two towers) and ray-traces 1.8–60 GHz.
The full write-up lives in the
[Notion study](https://app.notion.com/p/amini-updates/Digital-Twin-Propagation-Study-for-6G-Deployment-Barbados-Performing-Arts-Centre-3a5fd2e0589a8039b229e564397f3c93)
and the [research paper](research-paper/).

---

## Results preview

The twin, built from government footprints draped over the 55–110 m DEM with a
satellite basemap:

| Scene on terrain | Oblique perspective |
|---|---|
| ![Scene render on terrain](docs/renders/scene_render_terrain.png) | ![Blender perspective](docs/renders/blender_perspective.png) |

**Coverage at 3.5 GHz.** Fidelity matters: the terrain-drape map adds hill
shadowing, and the ground-following 1.5 m (handset-height) map — the one planning
decisions should use — is markedly more fragmented:

| Terrain drape | Ground-following @ 1.5 m AGL |
|---|---|
| ![Coverage, terrain](docs/renders/coverage_pathgain_db_terrain.png) | ![Coverage, ground-following](docs/renders/coverage_pathgain_db_terrain_groundfollow.png) |

**Multi-tower behaviour.** The four-tower SINR map is interference-limited at the
cell edges (a tilt/power/reuse problem, not a coverage-hole problem); best-server
association is dominated by the two in-box towers:

| SINR (4 towers, 2 W, 100 MHz) | Best server / handover |
|---|---|
| ![SINR map](docs/renders/sinr_map.png) | ![Best server handover](docs/renders/multitower_bestserver_handover.png) |

**Frequency behaviour.** The 1.8 / 3.5 / 6 / 10 GHz sweep tracks free-space λ²
physics to within ~1 dB — no anomalous excess loss — making **3.5 GHz the
coverage/capacity sweet spot**. mmWave (28/60 GHz, concrete-only) is LoS-only with
large holes: reserve it for fixed-wireless or hotspots.

| Sub-6 sweep | mmWave 28/60 GHz |
|---|---|
| ![Frequency sweep](docs/renders/sweep_frequency.png) | ![mmWave coverage](docs/renders/mmwave_concrete_coverage.png) |

**Link physics.** The Rising Sun radial fits a log-distance model with
**n = 1.73** and a 0.15 dB RMS residual — a textbook LoS, ground-reflection-dominated
rural link — with isolated delay-spread spikes (up to 361 ns) where a third ray
appears:

| Link metrics vs distance | Ray geometry check | Radio map in 3D |
|---|---|---|
| ![Link metrics](docs/renders/link_metrics.png) | ![Perspective paths](docs/renders/persp_paths.png) | ![Perspective radiomap](docs/renders/persp_radiomap.png) |

**Drive-test replay.** A moving receiver with live best-server tracking and link
budget — the harness for validating handover thresholds:

![Moving RX drive test](docs/renders/moving_rx.gif)

> ⚠️ Before treating numbers as bankable, read the caveats in the
> [study](https://app.notion.com/p/amini-updates/Digital-Twin-Propagation-Study-for-6G-Deployment-Barbados-Performing-Arts-Centre-3a5fd2e0589a8039b229e564397f3c93):
> projection distortion (rebuild in a metric UTM CRS), optimistic `itu_` materials
> (no foliage/rain), flat-top building extrusions, and no field calibration yet.

---

## Architecture

```mermaid
flowchart LR
  subgraph DATA["📦 Geospatial inputs"]
    SHP["bbd-geo-portal/\nshapefiles + LiDAR heights"]
    SAT["ESRI satellite tiles"]
    DEM["DEM / terrain grid"]
  end

  subgraph PREP["🐍 prep env (geopandas + GDAL)"]
    CLIP["clip\nstudy-area cut"]
    PRE["preprocess\nmanifest + terrain"]
    BASE["basemap\nmosaic + georef"]
  end

  subgraph BLD["🎨 Blender env (BlenderGIS + mitsuba-blender)"]
    BUILD["build\nextrude + drape scene"]
    EXP["export\nMitsuba XML + itu_ materials"]
  end

  subgraph RT["📡 Sionna RT env (mitsuba + drjit)"]
    COV["coverage / SINR"]
    SWEEP["frequency sweep + mmWave"]
    LINK["link metrics + CIR"]
    ANIM["drive-test animation"]
  end

  OUT["🗺 sionna_out/\nmaps · CSV · GIF · renders"]
  UI["ulap-twin-ui\nthree.js viewer"]
  PAPER["research-paper\nS-CDT / ISAC"]

  SHP --> CLIP --> PRE --> BUILD
  SAT --> BASE --> BUILD
  DEM --> PRE
  BUILD --> EXP --> COV & SWEEP & LINK & ANIM --> OUT
  OUT --> UI
  OUT --> PAPER

  WIZ["💻 ulap-scope init\ninteractive study wizard"] -. study.toml .-> CLIP
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the component walk-through and
[docs/scdt-architecture.png](docs/scdt-architecture.png) for how this pipeline slots
into the wider **Sovereign Climate Digital Twin (S-CDT)** stack from the paper.

## Repository layout

| Path | What it is |
|---|---|
| [`ulap-scope/`](ulap-scope/) | **The pipeline.** Installable Python package + `ulap-scope` CLI: config, geo core, stage runner, interactive study wizard, pytest harness |
| [`bbd-geo-portal/`](bbd-geo-portal/) | Barbados geoportal source data (shapefiles, study-area clips) |
| [`blender/`](blender/) | Working dir: Blender scenes, Mitsuba exports, `sionna_out/` results |
| [`BlenderGIS/`](BlenderGIS/) | Vendored add-on: georeferenced imports/basemaps in Blender |
| [`mitsuba-blender/`](mitsuba-blender/) | Vendored add-on: Blender → Mitsuba XML export |
| [`ulap-twin-ui/`](ulap-twin-ui/) | three.js web viewer for the twin |
| [`research-paper/`](research-paper/) | S-CDT / 6G-ISAC paper (LaTeX) + architecture diagrams |
| [`brandkit/`](brandkit/) | Ulap design system + assets |
| [`docs/`](docs/) | Architecture notes + curated renders used above |
| [`openspec/`](openspec/) | OpenSpec specs & change proposals for the pipeline and CLI |

## Quickstart

```bash
cd ulap-scope
pip install -e .        # light install: numpy only
ulap-scope init         # 💻♥📡 interactive wizard — define a NEW study anywhere
ulap-scope info         # show resolved config/paths
ulap-scope all          # clip → preprocess → basemap → build → export → RT stages
```

`ulap-scope init` asks for the study location, bounding box, projection (with a
computed UTM recommendation), the signals to model, and the geospatial layers you
have — recommending open sources (OSM footprints, Copernicus GLO-30 DEM, ESRI
imagery) for anything you don't — then writes a versioned `study.toml`:

```
      ((♥))          ((♥))
       /|\   ~ ♥ ~    /|\        Ulap Study Wizard
      /_|_\  ~ ♥ ~   /_|_\       tell us about your study area
              ____
             |ulap|  ♥ ♥
             '----'

  Study name [newton-bbd]:
  Longitude of study centre [-59.533908]:
  ...
  ♥ recommended projection: EPSG:32621 (UTM zone 21N) — true metres for link budgets
  ♥ no DEM? we recommend Copernicus GLO-30 (30 m, global, free)
```

Heavy stages need their own interpreters (no single env can host GDAL, bpy *and*
Sionna). See [`ulap-scope/README.md`](ulap-scope/README.md) for the three pinned
environments and per-machine env-var overrides.

## Tests

```bash
cd ulap-scope
make test       # fast unit suite: geo math, config, manifest, wizard, study spec
make test-rt    # integration smoke in the Sionna env (loads exported scene)
```

CI runs the fast suite on Python 3.10–3.12. The wizard/study tests are pure
stdlib and run anywhere.

## Specs

The intended behaviour of the pipeline and CLI is captured as
[OpenSpec](openspec/) requirements — start at
[`openspec/project.md`](openspec/project.md). New capabilities land as change
proposals under `openspec/changes/` before implementation.

## Contributing

Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) and our
[Code of Conduct](CODE_OF_CONDUCT.md).

## License

MIT for the `ulap-scope` package. Vendored add-ons
([BlenderGIS](BlenderGIS/LICENSE), [mitsuba-blender](mitsuba-blender/LICENSE))
keep their upstream licenses. Geoportal data is subject to its source terms.

---

*Built with ♥ in the Caribbean, for resilient sovereign networks.*
