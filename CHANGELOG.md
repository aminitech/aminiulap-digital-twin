# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Because this repository accompanies a research paper, entries that could change
a **published number** are called out explicitly under *Scientific behaviour*.

## [Unreleased]

### Added

- `examples/` — a laptop-scale entry point requiring only numpy and matplotlib:
  four notebooks, three runnable apps (Streamlit coverage explorer, drive-test
  replay, three.js viewer server), a shared `ulap_demo` package, and 75 tests.
  No Blender, GDAL or Sionna needed.
- `examples/data/fetch_open_scene.py` — builds a scene manifest for **any
  location on earth** from OpenStreetMap footprints (ODbL) and AWS Terrain Tiles,
  with no API key. Includes a self-contained UTM forward projection validated
  against pyproj to sub-millimetre at six reference points.
- Repo-hygiene regression guards: `test_no_developer_paths_in_tracked_files`
  (reads raw bytes, so image metadata cannot smuggle a path back in),
  `test_blender_working_dir_is_not_tracked`, and
  `test_no_geoportal_derived_scene_is_committed`.
- `examples CI` workflow — Python 3.10/3.11/3.12 plus a job that executes every
  notebook end to end.
- Figure provenance table ([`docs/renders/README.md`](docs/renders/README.md)):
  every published figure mapped to the stage, command and solver parameters that
  produced it.
- Issue templates (bug report, reproduction problem, new study area) and a pull
  request template.
- Repository study, audit, publication checklist and improvement plan under
  `docs/`.

### Changed

- Demo scene resolution is now **opt-in**: `load_scene()` takes an explicit path,
  then `$ULAP_SCENE`, then the bundled open-data sample. Pipeline output at
  `blender/scene_build/` is no longer auto-detected, so results no longer depend
  on what a particular clone happens to contain.
- The bundled demo scene is built entirely from open data (585 OSM footprints,
  57 m of relief) rather than from geoportal-derived layers.

### Fixed

- `fetch_open_scene.py` failed with `CERTIFICATE_VERIFY_FAILED` on interpreters
  without a configured CA bundle, and misreported it as Overpass rate limiting.
  It now uses `certifi` when available and gives trust-store guidance otherwise.
- Tower template positions were pinned to the pilot's metre offsets, so any
  smaller `--half-width` placed every site outside the study box and coverage
  failed with an unhelpful error. Positions are now fractions of the half-width.
- `fresnel_nu` diverged at profile endpoints, turning a building beneath the
  receiver into an effectively infinite wall.
- Removed a Streamlit keyword argument deprecated past its removal date, and a
  matplotlib font weight that warns on a clean install.

### Removed

- `blender/` working-directory contents are no longer tracked. Everything there
  is regenerable (`ulap-scope preprocess / build / export / coverage`) **and**
  derived from geoportal layers under an open redistribution review — see
  [DATA.md](DATA.md). Files remain on disk; only tracking changed.
- Ten stale duplicate stage scripts under `blender/`, superseded by the portable
  copies in `ulap-scope/ulap_scope/stages/`. Two of them hard-coded a developer's
  home directory.

### Security

- No absolute developer path remains in the tracked tree. `docs/renders/blender_perspective.png`
  carried one in a PNG `tEXt` chunk written by Blender; it was re-saved with all
  metadata stripped and pixels verified byte-identical.
- `publish/squashed` rebuilt from the cleaned tree: 7 geoportal-derived artefacts
  and 8 path leaks → 0 of each.

### Scientific behaviour

- **No change.** Nothing in this release alters a solver, a material, a geometry
  or a published number. The `examples/` propagation model is a new, clearly
  labelled *analytical* model used only for demonstration — it is not part of the
  ray-traced pipeline and is documented as such everywhere it appears.

### Known issues

- **Ray-traced results are not bit-reproducible.** Seven of eight solver
  invocations are unseeded Monte Carlo and the run-to-run variance has not been
  measured. See [`docs/REPOSITORY_AUDIT.md`](docs/REPOSITORY_AUDIT.md).
- Solver parameters (`cell_size`, `samples_per_tx`, `max_depth`) are hard-coded
  per stage rather than read from `config.py`, despite the documented
  "config over code" principle.
- `study.toml` does not yet drive the pipeline; `apply-study-config` is proposed
  but unimplemented.
- `ulap-scope/pyproject.toml` declares `license = "MIT"` while `LICENSE`,
  `README.md` and `CITATION.cff` state Apache-2.0.
