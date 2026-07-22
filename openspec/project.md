# Project Context

## Purpose

Reproducible radio-frequency **digital twins for 6G propagation studies**.
Given a study location and open/government geospatial layers, produce a
georeferenced 3D scene and ray-traced propagation products (coverage, SINR,
mmWave, link metrics, drive-test replays) that planners can act on.
Pilot deployment: Newton / Rising Sun, Barbados (Ulap One, Amini).

## Tech Stack

- Python 3.10–3.12 (`ulap-scope` package; core deps: numpy only)
- Stage environments: geopandas/GDAL (prep) · Blender 4.4 + BlenderGIS +
  mitsuba-blender (scene build/export) · Sionna RT 2.0.1 + mitsuba 3.8/drjit (ray tracing, CPU/LLVM)
- pytest (fast unit suite + `-m rt` integration markers), GitHub Actions CI
- three.js viewer (`ulap-twin-ui`), LaTeX research paper

## Project Conventions

### Code Style

Small, dependency-light modules; docstring headers explaining the module's role;
dataclasses for config; pure functions in the tested core (`geo.py`, `study.py`).
No heavy GIS imports in the package's import surface — stages run out-of-process.

### Architecture Patterns

- Pipeline stages communicate via files (`scene_manifest.json`, Mitsuba XML)
  under `$ULAP_WORK_DIR`; every stage re-runnable in isolation.
- All physics/geometry parameters live in config or `study.toml` — never
  hard-coded in stage scripts.
- Vendored upstream add-ons (BlenderGIS, mitsuba-blender) are never patched
  in-tree.

### Testing Strategy

Fast suite must pass on any machine with `pip install -e .[test]` (no
Blender/Sionna/GDAL). Anything needing the RT env is marked `rt` and auto-skips.
New behaviour ships with unit tests of the pure logic.

### Git Workflow

Branch from `main`; spec-first for behaviour changes (proposal under
`openspec/changes/`); PRs keep the fast suite green on 3.10–3.12.

## Domain Context

RF propagation planning: path gain, SINR, best-server/handover, delay spread,
fidelity tiers (flat / terrain / ground-following 1.5 m AGL). Key hard-won
lessons encoded in the specs: metric CRS or your link budgets lie (~2.6% Web
Mercator stretch at 13°N); planning decisions use ground-following maps;
mmWave is LoS-only; `itu_` materials without foliage/rain are optimistic.

## Important Constraints

- CPU-only (Mitsuba LLVM backend) — must run on a laptop, no CUDA.
- Three mutually incompatible Python environments — stages must stay
  out-of-process.
- Geoportal data licensing varies by country; sources must be recorded in
  `study.toml`.

## External Dependencies

- ESRI World Imagery tiles (basemap), OSM/Overpass (fallback footprints),
  Copernicus GLO-30 / SRTM (fallback DEM), ESA WorldCover (optional land cover)
- NVIDIA Sionna RT, Mitsuba 3, Blender + add-ons
