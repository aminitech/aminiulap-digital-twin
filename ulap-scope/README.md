# Ulap Scope

Barbados / **Newton Burial Site** RF digital twin — a reproducible pipeline that turns
the national geoportal shapefiles + satellite imagery into a georeferenced 3D scene in
Blender, exports it to Mitsuba, and ray-traces radio propagation in **NVIDIA Sionna RT**
(coverage, SINR, mmWave, drive-test). Part of the **Ulap One** project.

```
shapefiles ──clip──▶ study_area ──preprocess──▶ manifest+terrain ──build──▶ Blender scene
                                     │  basemap (ESRI tiles) ┘                 │ export
                                     ▼                                          ▼
                              Sionna RT  ◀── coverage / SINR / mmWave / animate ── Mitsuba XML
```

Everything runs **on CPU** (Mitsuba LLVM backend) — no CUDA required.

## Layout

```
ulap-scope/
  ulap_scope/
    config.py        # all paths/CRS/params, env-overridable (portable)
    geo.py           # pure, tested core: coords, terrain interp, footprint & manifest validation
    pipeline.py      # runs each stage out-of-process in the right interpreter
    cli.py           # `ulap-scope <stage>` / `ulap-scope init`
    study.py         # portable study spec: bbox/UTM math, study.toml I/O (stdlib)
    wizard.py        # `ulap-scope init` interactive wizard (towers ♥ laptop)
    stages/          # vendored stage scripts (data paths driven by $ULAP_WORK_DIR)
  tests/             # pytest harness (fast unit + `-m rt` integration)
  requirements/      # per-env deps: prep.txt, rt.txt, blender.txt
  pyproject.toml  Makefile  README.md
```

## Three environments

The pipeline spans three Python interpreters (no single env can host all deps):

| Env | Interpreter (dev machine) | Installs | Stages |
|-----|---------------------------|----------|--------|
| **prep** | `/opt/anaconda3/bin/python` | `requirements/prep.txt` + GDAL CLI on PATH | clip, preprocess, basemap |
| **Blender** | `…/Blender.app/Contents/Resources/4.4/python/bin/python3.11` | `requirements/blender.txt` + osgeo GDAL bindings + mitsuba-blender add-on | build, export |
| **RT** | `/opt/anaconda3/envs/sionna/bin/python` | `requirements/rt.txt` | coverage, analysis, mmwave, terrain-ground, animate |

Point the pipeline at them with env vars. All are optional: `ULAP_BLENDER_BIN`
defaults to `blender` on `PATH`, the interpreters default to the current Python,
and the GDAL CLIs are resolved from `PATH` unless `ULAP_GDAL_BIN` is set. Set them
only when the tools live somewhere non-standard (example shows one dev machine):

```bash
export ULAP_PROJECT_ROOT=/path/to/ulap-digital-twin   # holds bbd-geo-portal/ and blender/
export ULAP_BLENDER_BIN=/Applications/Blender.app/Contents/MacOS/Blender
export ULAP_PREP_PY=/opt/anaconda3/bin/python
export ULAP_RT_PY=/opt/anaconda3/envs/sionna/bin/python
export ULAP_GDAL_BIN=/opt/homebrew/bin                 # dir with gdal_translate/gdalwarp/gdalinfo
```

## Define a new study (reusable twins)

The pipeline is not Barbados-specific: `ulap-scope init` walks you through a new
study — location, bounding box, projection, signals, geospatial layers — and
writes a versioned `study.toml`:

```bash
ulap-scope init                 # interactive wizard (Enter accepts defaults)
ulap-scope init --defaults      # non-interactive: the Newton, Barbados pilot
ulap-scope init -o my-study.toml
```

Recommendations (marked ♥) encode the pilot's lessons: the wizard *computes*
the metric UTM EPSG for your longitude (link budgets in Web Mercator are
distorted — it warns if you pick EPSG:3857), suggests 3.5 GHz as the primary
band, flags mmWave as LoS-only, and offers open-data fallbacks for any layer
you don't have (OSM footprints, Copernicus GLO-30 DEM, ESRI imagery, ESA
WorldCover). Spec: `../openspec/specs/study-cli/spec.md`. Pointing the stage
scripts at a `study.toml` is the follow-up change `apply-study-config`.

## Reproduce

```bash
pip install -e .            # installs the `ulap-scope` CLI (light: numpy only)
ulap-scope info            # show resolved config/paths
ulap-scope all             # clip → preprocess → basemap → build/export/coverage (flat+terrain) → analysis, sinr, ...
# or individual stages:
ulap-scope build --mode terrain
ulap-scope mmwave-sinr
make coverage MODE=terrain
```

Outputs land in `$ULAP_WORK_DIR/sionna_out/` (coverage maps, SINR, sweep, `moving_rx.gif`, …).

## Tests

```bash
make test        # fast unit suite  (geo math, config, manifest integrity) — prep python
make test-rt     # integration smoke (loads exported scene, checks ITU materials + radio map) — sionna python
```

The fast suite needs only numpy/scipy and runs anywhere; the `rt`-marked tests auto-skip
unless run in the Sionna env with a scene already exported.

**CI** — `.github/workflows/ci.yml` runs the fast suite on push/PR across Python 3.10–3.12
(`pip install -e .[test]` → `pytest`). It does **not** run the `rt` tests (those need
Blender + Sionna). In the Ulap One monorepo the workflow uses `working-directory: ulap-scope`;
if `ulap-scope` is the repo root, set it to `.`.

## Pinned environments

Reproduce the two conda environments exactly:

```bash
conda env create -f environment-prep.yml   # clip / preprocess / basemap  (geopandas + gdal)
conda env create -f environment-rt.yml     # Sionna RT  (sionna-rt 2.0.1, mitsuba 3.8.0, drjit 1.3.1)
```

Blender's bundled Python is set up separately (`requirements/blender.txt`): `mitsuba==3.5.0`
(exact, for the mitsuba-blender add-on), the osgeo GDAL bindings, and `setuptools>=77`.

## Study area

Newton, Barbados — `-59.5339, 13.0881`. Scene CRS **EPSG:21292** (Barbados 1938 National
Grid, true metres), origin `(32735.32, 64854.74)`. 576 buildings in the 2 km box; towers
**Newton** (30 m) and **Rising Sun** (24 m).
