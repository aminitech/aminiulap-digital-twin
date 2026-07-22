# study-pipeline Specification

## Purpose

Turn geospatial inputs for a bounded study area into a georeferenced 3D scene
and ray-traced propagation products, reproducibly, across three isolated
Python environments.

## Requirements

### Requirement: Staged, file-contracted pipeline

The system SHALL execute the pipeline as discrete stages (clip, preprocess,
basemap, build, export, coverage, analysis, mmwave-sinr, terrain-ground,
animate) that communicate only through files under the working directory, so
that any stage can be re-run in isolation.

#### Scenario: Re-run a single stage

- **WHEN** a user runs `ulap-scope coverage --mode terrain` with an existing
  exported scene
- **THEN** the stage runs in the RT interpreter without re-running upstream
  stages, and writes its products to `sionna_out/`

### Requirement: Environment isolation

The system SHALL run each stage in its designated interpreter (prep, Blender,
RT), resolved from configuration with environment-variable overrides, and SHALL
NOT import heavy GIS/RT dependencies into the package's own import surface.

#### Scenario: Portable install

- **WHEN** the package is installed with `pip install -e .` on a machine with
  only numpy
- **THEN** `ulap-scope info` and the fast test suite work without
  Blender/Sionna/GDAL present

### Requirement: Configuration over code

The system SHALL source every physics and geometry parameter (CRS, origin,
bounding box, frequency bands, TX power, bandwidth, radio-map cell size, solver
max depth and samples) from configuration, and SHALL record the parameters
alongside outputs so figures are reproducible.

#### Scenario: Reproducing a published figure

- **WHEN** a contributor checks out the repo and applies the recorded
  configuration for a figure
- **THEN** re-running the corresponding stage reproduces the figure within
  sampling noise

### Requirement: Fidelity tiers

The system SHALL support flat-ground, terrain-draped, and ground-following
(receiver at 1.5 m AGL) variants of coverage products, and documentation SHALL
designate ground-following/terrain maps as the planning reference.

#### Scenario: Terrain build

- **WHEN** a user runs build/export/coverage with `--mode terrain`
- **THEN** the scene drapes buildings on the DEM and coverage products include
  the terrain and ground-following maps

### Requirement: Validated scene manifest

The system SHALL validate building footprints (ring validity, closing-point
handling) and the scene manifest (origin, CRS, terrain grid integrity) in the
fast test suite.

#### Scenario: Corrupt manifest

- **WHEN** the manifest's terrain grid is inconsistent with its declared
  dimensions
- **THEN** the fast test suite fails with a descriptive assertion
