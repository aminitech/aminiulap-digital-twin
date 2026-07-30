# Validation — how to check that any of this is true

This repository backs a paper. Papers make claims; claims decay. This document is the
front door to the machinery that checks them, and it is written so a stranger can run it.

Nothing here asks you to trust a number. Every layer below is a command you can execute and
a result you can compare.

---

## The five layers, and what each one can and cannot tell you

| Layer | Question it answers | Command | What it does **not** prove |
|---|---|---|---|
| **Tests** | Does the code do what its authors intended? | `pytest` in `ulap-scope/` and `examples/` | Nothing about physics, or about the paper |
| **Claims gate** | Does the paper still match the code? | `python claims/verify_claims.py --rerun` | Only the numbers listed; prose is unchecked |
| **Comparison** | Is the physics better than a cheap alternative? | `python comparison/c1_…py`, `c2_…`, `c3_…` | Nothing about reality — none of it is field-calibrated |
| **Benchmarks** | What does it cost, and on what hardware? | `bash benchmarks/run.sh` | Nothing about correctness |
| **Visual** | Do the figures regenerate identically? | `bash visual/run.sh` | Only same-host determinism |

Run them in that order. Each one is cheap and each one fails differently.

---

## 1. Tests — 116 of them

```sh
python3 -m venv venv && ./venv/bin/pip install -e ulap-scope pytest numpy scipy matplotlib pillow
(cd ulap-scope && ../venv/bin/python -m pytest -q)     # 48 passed
(cd examples  && ../venv/bin/python -m pytest -q)      # 69 passed
```

Two of these are **regression guards** rather than ordinary tests, and they matter more than
their count suggests: one reads the raw bytes of every tracked file looking for developer
paths (a text scan misses the case where a path is embedded in PNG metadata), and one pins
the allowed file set under `blender/`. A guard that does not run is not a guard, so both run
in CI on changes to `blender/`, `docs/`, `.gitignore` and `DATA.md` as well as `examples/`.

The ray-tracing smoke test is marked `rt` and skips unless a Sionna environment and a built
scene are present:

```sh
(cd ulap-scope && ULAP_PROJECT_ROOT=$PWD/.. ../venv/bin/python -m pytest -m rt -q)   # 3 passed
```

---

## 2. The claims gate — the paper against the code

This is the layer that does not exist in most research repositories, and it is the one that
caught the most.

```sh
./venv/bin/pip install -r claims/requirements.txt
./venv/bin/python claims/verify_claims.py            # check against existing artefacts
./venv/bin/python claims/verify_claims.py --rerun    # re-execute the producers first
```

`claims/claims.yaml` binds each quantitative claim in the paper to the script and artefact
that produce it, with its own tolerance and the sections it appears in. The verifier
extracts the value, compares within tolerance, **and** checks the claimed string is still
present in the paper — so a number quietly edited out also fails. Exit code is 0 only when
every checkable claim matches, so it can gate CI.

Claims that cannot be verified from the public release are recorded as **unverifiable, with
the reason**, rather than omitted. An unprovable claim should be visibly unprovable; a
register that silently lists only the convenient claims is worse than no register.

**Why it exists.** One afternoon of re-running found four defects, three of them in the
abstract: frequency-sweep medians that did not reproduce, a ridge-shadowing claim that was
largely a receiver-placement artefact, two compared figures on independent colour scales, and
a publish branch missing the entire reproduction path. Not one was findable by reading the
paper against itself. All four were findable by executing something.

Building the register then caught two more — the paper saying `28.9` where the artefact said
`28.968`, and the same figure quoted against two different noise floors in two sections.

---

## 3. Comparison — is the physics worth it?

Three pre-registered studies. The rules are fixed in `benchmarks/METHOD.md` **before** any
measurement, so results cannot be chosen after the fact.

```sh
export ULAP_WORK_DIR=/path/to/work-dir MPLBACKEND=Agg
./venv-rt/bin/python comparison/c1_rt_vs_analytical.py    # vs a closed-form model
./venv-rt/bin/python comparison/c2_rt_vs_stochastic.py    # vs 3GPP TR 38.901
./venv-rt/bin/python comparison/c3_ablation.py            # flat / terrain / ground-following
```

The findings run against this project's own interest, which is the point:

- **C1**: a free-space plus two-ray model tracks the ray tracer to **0.11 dB RMS** on the
  Newton transect. Reported with the reason attached — that radial resolves a median of two
  paths and path gain is an incoherent power sum, so the solve *is* the two-ray model there.
  It bounds where determinism is **not** required.
- **C2**: deterministic and stochastic methods pick a **different serving mast in 29.4 % of
  cells**, 135× the ray tracer's own noise floor, and sit 28 dB apart at the cell edge. They
  measurably *differ*. "Improve" is **not** established, because nothing here is calibrated
  against field measurement.
- **C3**: terrain barely moves the area median (−0.2 dB) but changes serving-cell
  association in 21.9–26.3 % of cells against a 1.03 % noise floor. Association statistics,
  not medians, are the right reporting unit for coverage studies.

---

## 4. Benchmarks — what it costs

```sh
bash benchmarks/run.sh                 # auto-detects backends, 3 repeats
bash benchmarks/run.sh --backends cpu  # no GPU present
```

One command. It refuses to start when any of three silent-failure traps is armed, each of
which cost real time to discover:

- **Missing GNU `time`** makes the harness record CPU% and peak RSS as **zero rather than
  failing** — a benchmark that looks complete and contains no resource data.
- **Sionna tries the CUDA variants first**, so a run you believe is CPU-only executes on the
  GPU if one is visible. The variant is read back from every run; a mismatch is invalid, never
  relabelled.
- **Re-running on a machine with a committed result** would overwrite it. It writes
  `<host>-<arch>-local.json` instead and says so.

Measured across three machines spanning four orders of magnitude in cost:

| | full pipeline, CPU-only | peak RSS |
|---|---|---|
| NVIDIA GB10, aarch64, 20 cores | 26.5 s | 1.25 GB |
| NVIDIA H200 NVL, x86_64, 256 cores | 19.1 s | 1.25 GB |
| **Raspberry Pi 4, aarch64, 4 cores** | **310 s** | **0.81 GB** |

The Raspberry Pi produces a **byte-identical** `link_metrics.csv` to both server-class hosts
— MD5 `08afea6d…` on all three plus the archived copy. Because that file is written at two
decimal places this establishes agreement to **0.01 dB, not bit-identical floating point**.
The distinction is made everywhere in this repository and should not be upgraded.

---

## 5. Visual — do the figures regenerate?

```sh
bash visual/run.sh                # capture
bash visual/check-determinism.sh  # run N times, diff sha256 per file
```

Fixed viewport, fixed camera, fixed scene, external network blocked, animation clock frozen,
RNG seeded. Two of the shots are **failure states**, captured in the same run at the same
settings rather than omitted.

Determinism here was earned, not assumed. Diffing repeat runs exposed three sources of
non-determinism that reasoning alone missed, each reproducing roughly one run in four — so a
two-run check would have passed on a broken harness.

---

## Reproducibility, stated honestly

**What holds today.** The numeric result reproduces across two processor architectures, two
GPUs, the CPU backend, two solver versions, and a £60 single-board computer. That is a
stronger statement than most simulation papers can make.

**What does not.** Rendered PNGs are **not** byte-stable across hosts — they differ in
0.2–2.4 % of pixels, mean absolute difference below 0.04/255, concentrated at colormap
boundaries and glyph edges. Reproduction of the *numeric* result is verifiable by checksum;
reproduction of the *figures* is not, and is not claimed.

**The reproduction gap, and how far it is closed.** The exported Mitsuba scenes were removed
from the tracked tree during the pre-publication scrub, because they derive from
licence-restricted government data — 576 building footprints with LiDAR heights. That decision
stands and is correct.

To keep the ray-tracing path runnable, this repository now ships an **open-data Mitsuba scene**
at `examples/data/open_scene_mitsuba/`, built entirely from OpenStreetMap footprints (ODbL 1.0)
and AWS Terrain Tiles (public domain) by `ulap-scope/ulap_scope/stages/export_mitsuba_direct.py`
— a stdlib-only exporter that needs no Blender. 626 KiB, 585 buildings, and a test asserts it
regenerates byte-identically from the manifest, so the committed artefact cannot drift from the
code that makes it. See `docs/OPEN-DATA-SCENE.md`.

**What that does and does not buy you.** You can now clone this repository and run the ray
tracer end to end, with no licence-restricted data and no Blender. You **cannot** reproduce the
Barbados results from it, and no one should try: the buildings are different, every height is a
per-type default because not one OSM footprint in the study area carries a `height` or
`building:levels` tag, and the terrain is ~31 m posting rather than a LiDAR DTM. The open scene
proves the *pipeline* runs; the Barbados numbers remain reproducible only with the restricted
data, which is under Government of Barbados disclosure review.

---

## If you are reviewing this work

The fastest honest check is:

```sh
(cd examples && python -m pytest -q)          # does the open path work at all?
python claims/verify_claims.py                # does the paper match its artefacts?
cat docs/audits/*.md                          # what did the authors find against themselves?
```

The audits are the most informative thing here. They record defects found in this project's
own work, including several that weakened its own claims, with the measurements that
established them. A project that only publishes its successes has not told you how carefully
it looked.
