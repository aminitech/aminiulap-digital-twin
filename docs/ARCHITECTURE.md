# Architecture

How a pile of shapefiles becomes a ray-traced 6G propagation study.

## The pipeline at a glance

```mermaid
%%{init: {'theme':'base','themeVariables':{'darkMode':true,'background':'#121212','primaryColor':'#202020','primaryTextColor':'#FFFFFF','primaryBorderColor':'#3A3A3A','lineColor':'#8A8A8A','textColor':'#FFFFFF','mainBkg':'#202020','nodeBorder':'#3A3A3A','clusterBkg':'#1A1A1A','clusterBorder':'#2E2E2E','edgeLabelBackground':'#1A1A1A','fontSize':'14px'}}}%%
flowchart TB
  subgraph INPUTS["GEOSPATIAL INPUTS"]
    SHP["Building footprints + LiDAR AVG_HEIGHT<br/>bbd-geo-portal shapefiles, or OSM"]
    DEM["Terrain / DEM<br/>national LiDAR, or Copernicus GLO-30"]
    SAT["Satellite basemap tiles<br/>ESRI World Imagery"]
    TWR["Tower registry<br/>location, height, sectors"]
  end

  subgraph STUDY["STUDY DEFINITION"]
    WIZ["ulap-scope init — interactive wizard<br/>location · bbox · CRS · bands · layers"]
    TOML["study.toml (versioned)"]
    WIZ --> TOML
  end

  subgraph PREP["STAGE 1 — PREP ENV (geopandas + GDAL)"]
    CLIP["clip — cut all layers to the study bbox"]
    PRE["preprocess — scene manifest, terrain grid,<br/>footprint validation, local origin"]
    BASE["basemap — tile mosaic, georeferenced"]
  end

  subgraph BLD["STAGE 2 — BLENDER ENV (BlenderGIS + mitsuba-blender)"]
    BUILD["build — extrude footprints to LiDAR height,<br/>drape on terrain, texture with basemap"]
    EXP["export — Mitsuba XML with itu_ materials"]
  end

  subgraph RT["STAGE 3 — SIONNA RT ENV (mitsuba LLVM, CPU)"]
    COV["coverage — path-gain radio maps<br/>flat / terrain / ground-following 1.5 m"]
    SINR["mmwave-sinr — multi-tower SINR,<br/>best-server, 28/60 GHz"]
    LINK["analysis — radial link metrics,<br/>delay spread, frequency sweep"]
    ANIM["animate — moving-RX drive-test replay"]
  end

  OUT[("sionna_out/ — PNG maps · CSV · GIF · renders")]

  TOML --> CLIP
  SHP & DEM & TWR --> CLIP --> PRE --> BUILD
  SAT --> BASE --> BUILD
  BUILD --> EXP --> COV & SINR & LINK & ANIM --> OUT
  OUT --> UI["ulap-twin-ui (three.js)"]
  OUT --> PAPER["research-paper (S-CDT / ISAC)"]

  classDef hero fill:#202020,stroke:#FFC83C,stroke-width:2.5px,color:#FFC83C
  class OUT hero
```

## Why three Python environments?

No single interpreter can host GDAL/geopandas, Blender's `bpy`, **and**
Sionna RT/DrJit simultaneously — their binary deps conflict. So
`ulap_scope.pipeline` runs each stage **out-of-process** in the right
interpreter, passing state through files (`scene_manifest.json`,
`towers_near.json`, Mitsuba XML) under `$ULAP_WORK_DIR`:

| Env | Runs | Key deps |
|---|---|---|
| **prep** | clip, preprocess, basemap | geopandas, GDAL, pyproj, pillow |
| **Blender** | build, export | bpy 4.4, BlenderGIS, mitsuba-blender, mitsuba 3.5 |
| **RT** | coverage, analysis, mmwave, terrain-ground, animate | sionna-rt 2.0.1, mitsuba 3.8, drjit |

Everything is CPU-only (Mitsuba LLVM backend) — no CUDA required, so studies run
on a laptop. ((♥)) → 💻

## Key design decisions

- **File-based contracts between stages.** Each stage reads/writes plain files;
  any stage can be re-run in isolation, and the manifest is validated by the
  fast test suite (`tests/test_manifest.py`) without any GIS deps installed.
- **Config over code.** All physics/geometry parameters (CRS, origin, bbox,
  bands, TX power, solver depth/samples) live in `ulap_scope/config.py`,
  env-overridable; `ulap-scope init` generalizes this into a per-study
  `study.toml` so the pipeline is reusable beyond Barbados.
- **Projection honesty.** Scenes assembled in Web Mercator stretch distances
  (~2.6% at 13°N) — link budgets inherit that error. The wizard therefore
  *computes* and recommends the metric UTM zone for the study longitude and
  warns whenever a non-metric CRS is chosen.
- **Fidelity tiers.** Every coverage product exists as flat / terrain-drape /
  ground-following@1.5 m. Planning decisions use ground-following; flat is for
  relative comparisons only (e.g. the frequency sweep).
- **Vendored add-ons.** BlenderGIS and mitsuba-blender are vendored for
  reproducibility (pinned revisions), never patched in-tree.

## Where this sits in the S-CDT stack

This repo is the **propagation-study engine** of the wider Sovereign Cognitive
Digital Twin architecture (sensing layer → geo-cubes → node network → sovereign
data lake → cognitive twin) described in the [research paper](../research-paper/).
Everything in this repository is the `Simulation and ML Surrogates` box in
layer 5, plus the RF half of layer 4.

![S-CDT reference architecture: six layers from network-as-a-sensor through to interaction and orchestration, over a zero-trust integrity gate. Solid nodes are built; dashed nodes are specified but not implemented.](scdt-architecture.png)

**Read the borders.** Solid nodes are built and running in Ulap SCOPE today.
Dashed, dimmed nodes are specified in the paper and **not implemented** — the
ISAC feed, the ledger anchoring, the cryptographic admission gate, the
belief-state synchronization engine and the AI-RAN control loop are all still
design. This matches Table I of the paper; if the two ever disagree, the paper
wins.

The figure is generated from [`diagrams/scdt-architecture.mmd`](diagrams/) —
edit the Mermaid source and run `diagrams/render.sh`, never the PNG. A light
variant for print and light-background slides sits next to it at
`scdt-architecture-light.png`.

The RT outputs are the seed of the ISAC/network-as-sensor roadmap: per-path
channel impulse responses (delay, angle, Doppler) logged from the twin become
the sensing observables of the deployed network — the calibrated
`H_background` that the (not yet built) EKF loop would difference against.
