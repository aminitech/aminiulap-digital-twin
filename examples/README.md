# Examples — run the twin on your laptop in 60 seconds

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
```

The full pipeline (BlenderGIS → Mitsuba → Sionna RT) needs three Python
environments and a serious install. **These demos need numpy and matplotlib.**

```bash
cd examples
pip install -r requirements.txt
jupyter lab notebooks/            # ← start here
```

No install step is required — the notebooks and apps find `ulap_demo` and
`ulap_scope` from a bare checkout, and they ship with a working scene.

## Which scene do I get?

`load_scene()` takes the first of:

1. an explicit path you pass it,
2. `$ULAP_SCENE`,
3. the bundled sample, built entirely from **open data**.

So every reader gets the same scene by default, whatever their checkout contains,
and every notebook prints which scene it loaded and where each layer came from.

To run the demos against your own study instead:

```bash
export ULAP_SCENE=/path/to/blender/scene_build/scene_manifest.json
```

That is deliberately opt-in rather than auto-detected: a clone may contain a
pipeline manifest built from licence-restricted layers (see [DATA.md](../DATA.md)),
and picking it up silently would both change results between checkouts and run
data the reader never chose.

The bundled sample covers the pilot's study area using **OpenStreetMap** footprints
(ODbL) and **AWS Terrain Tiles** elevation — 585 buildings, 57 m of relief. The
licence-restricted Barbados Geoportal layers behind `docs/renders/` are *not* in
this repository and never will be while their disclosure review is open; see
[DATA.md](../DATA.md) and [data/README.md](data/README.md). Build a scene for your
own area in one command:

```bash
python data/fetch_open_scene.py --lon 36.8219 --lat -1.2921 --name nairobi-cbd
```

---

## What's honest here, and what isn't

| | |
|---|---|
| **Measured** | `data/newton_link_metrics.csv` — genuine Sionna RT output: path gain, RMS delay spread and path counts at 14 receiver positions, from `ulap-scope analysis`. |
| **Open, but not measured** | The bundled scene. OSM has excellent footprint geometry and almost no heights, so heights come from a per-type default table; terrain is ~30 m posting, not LiDAR. Every building records its own `h_source`, and `scene.sources()` prints the lot. |
| **Approximate** | The propagation engine in [`ulap_demo/propagation.py`](ulap_demo/propagation.py): free space + two-ray ground reflection + dominant-obstacle knife-edge diffraction. ~250 lines, microseconds per link. |
| **Not modelled at all** | Multi-bounce specular chains, material-specific reflection/transmission, diffuse scattering, **and the entire delay domain** — no delay spread, no CIR, no Doppler, no MIMO rank. |

How good is the approximation? On the pilot's rural line-of-sight radial it
recovers the ray tracer's path-loss exponent to **within 0.05** (1.78 vs 1.73) and,
after removing one calibration constant, tracks it with a **0.26 dB RMS residual**.
It is also completely blind to the 361 ns delay-spread spike the ray tracer found
at 450 m. Both facts are the point of notebook 02.

> Use these demos to build intuition, explore candidate plans and size a problem.
> Quote [`docs/renders/`](../docs/renders/) — the ray-traced results — for anything
> that matters, and read the study's caveats before treating even those as bankable.

---

## Notebooks

| | What you'll learn | Needs |
|---|---|---|
| **[01 · Define a study](notebooks/01_define_a_study.ipynb)** | The `study.toml` contract: bounding boxes, why picking a non-metric CRS silently corrupts every link budget, computing the right UTM zone, band plans and open-data fallbacks. Twin somewhere new by editing two numbers. | stdlib only |
| **[02 · Link budget](notebooks/02_link_budget.ipynb)** | Real Sionna RT output vs. an analytical model. Fit the log-distance exponent, discover *why* it comes out below free space, and find precisely where the cheap model stops being enough. | numpy, matplotlib |
| **[03 · Scene & terrain](notebooks/03_scene_and_terrain.ipynb)** | What the twin is made of, and what open data costs you. Validate a manifest, rasterise the footprints, check Fresnel clearance on a backhaul hop and on a shadowed handset, and watch a receiver at 1.5 m see barely half of what one at 30 m sees. | numpy, matplotlib |
| **[04 · Coverage & SINR](notebooks/04_coverage_and_sinr.ipynb)** | Whole-area maps in ~100 ms: RSRP, best-server/handover, SINR. Sweep five bands, ablate terrain and buildings to measure what each costs, then add a third tower and watch SINR get *worse*. | numpy, matplotlib |

---

## Apps

### 📡 Coverage Explorer — the notebook with sliders

```bash
streamlit run apps/coverage_explorer/app.py
```

Change band, power, antenna height, receiver height, or drop a candidate site
anywhere in the scene, and watch coverage, SINR, best-server association and the
CDFs recompute instantly. [More →](apps/coverage_explorer/README.md)

### 🚗 Drive test — handover replay

```bash
python apps/drive_test/drive_test.py                   # writes drive_test.gif + .csv
python apps/drive_test/drive_test.py --freq-ghz 1.8 --frames 90
```

Animates a receiver driving through the scene with live best-server tracking, and
writes a per-sample link-budget CSV — the harness for validating handover
thresholds. [More →](apps/drive_test/README.md)

### 🌐 Twin viewer — the 3-D scene in your browser

```bash
python apps/twin_viewer/serve.py
```

Serves the vendored three.js viewer (`ulap-twin-ui/`). **Standard library only** —
no pip install at all. [More →](apps/twin_viewer/README.md)

---

## Layout

```
examples/
  ulap_demo/          shared demo code — import it, read it, replace it
    scene.py            scene resolution & loading; terrain sampling; footprint rasteriser
    propagation.py      the analytical radio model + coverage/SINR solver
    plotting.py         one consistent dark map style for every figure
  data/               open sample data + the scene builder — see data/README.md
    fetch_open_scene.py   build a scene anywhere from OSM + open elevation
    towers.template.json  placeholder site list you edit
  notebooks/          01–04, in order
  apps/               three runnable local apps
  tests/              pytest suite that pins the claims the notebooks make
```

## Use your own study

Everything here takes a path, so nothing is Barbados-specific:

```python
from ulap_demo import load_scene, PropagationModel

scene = load_scene("blender/scene_build/scene_manifest.json")   # your own study
print(scene.sources())                                          # where it came from
cov = PropagationModel(freq_hz=3.5e9).coverage(scene, cell_m=10.0)
print(cov.summary())
```

Three ways to get a scene, in increasing order of fidelity:

```bash
# 1. open data, one command, anywhere on earth
python data/fetch_open_scene.py --lon <your lon> --lat <your lat> --name <study>

# 2. the real pipeline on data you supply (see ../DATA.md)
cd ../ulap-scope && pip install -e .
ulap-scope init          # interactive wizard → study.toml
ulap-scope preprocess    # → blender/scene_build/scene_manifest.json

# 3. ray-trace it for real
ulap-scope coverage
```

## Tests

```bash
cd examples && python -m pytest -q
```

The suite covers the physics helpers against closed-form values **and pins the
headline claims** — if the model drifts far enough that notebook 02's "within
0.1 of the ray-traced exponent" stops being true, a test fails before a reader
finds out.

## Contributing an example

New notebooks and apps are very welcome — see
[CONTRIBUTING.md](../CONTRIBUTING.md). Two house rules specific to this folder:

1. **Commit notebooks with outputs stripped** (`jupyter nbconvert --clear-output
   --inplace`). There is a test for it.
2. **Never let prose outrun the model.** If a cell prints a number, the markdown
   around it has to agree with that number — and if the analytical model is doing
   something a ray tracer wouldn't, say so in the notebook.

---

*Built with ♥ in the Caribbean, for resilient sovereign networks.*
