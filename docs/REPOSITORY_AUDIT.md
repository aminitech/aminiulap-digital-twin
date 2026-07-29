# Repository Audit

Assessment of `amini-ulap-digital-twin` against the criteria used in
[REFERENCE_REPOSITORY_STUDY.md](REFERENCE_REPOSITORY_STUDY.md).

**Method.** Read-only inspection of the tracked tree at `6f68419`
(2026-07-29). Every finding cites a file and, where useful, a line. **Confirmed
facts are separated from recommendations**: this document states what is true;
[IMPROVEMENT_PLAN.md](IMPROVEMENT_PLAN.md) says what to do about it.

**Context.** This repository is the reference implementation for paper #2,
*Sovereign Cognitive Digital Twins* (`research-paper/README.md`), which is under
internal review and not yet on arXiv. So the audit is pre-submission, which is
the right time for it.

---

## Summary

The repository is **stronger than its reference peers on provenance, governance
and honesty**, and **weaker on the mechanics that let a stranger reproduce a
number**. That is an unusual and quite fortunate shape: the hard-to-retrofit
parts (licensing discipline, data statement, spec-first process, an open-data
on-ramp) are done. The gaps are mostly additive.

One finding is genuinely critical and is stated first.

---

## 🔴 Critical finding: ray-traced results are not reproducible

**Confirmed fact.** Across the five Sionna RT stages there are **eight solver
invocations; exactly one passes a seed.**

| File | Line | Call | Seeded |
|---|---|---|---|
| `ulap_scope/stages/sionna_coverage.py` | 88 | `PathSolver()(…, seed=41)` | ✅ |
| `ulap_scope/stages/sionna_coverage.py` | 73 | `RadioMapSolver()` | ❌ |
| `ulap_scope/stages/sionna_analysis.py` | 42 | `RadioMapSolver()` | ❌ |
| `ulap_scope/stages/sionna_analysis.py` | 136 | `PathSolver()` | ❌ |
| `ulap_scope/stages/sionna_animate_rx.py` | 45 | `PathSolver()` | ❌ |
| `ulap_scope/stages/sionna_animate_rx.py` | 60 | `RadioMapSolver()` | ❌ |
| `ulap_scope/stages/sionna_mmwave_sinr.py` | 63 | `RadioMapSolver()` | ❌ |
| `ulap_scope/stages/sionna_terrain_ground.py` | 54 | `RadioMapSolver()` | ❌ |

These are **Monte-Carlo solvers** — `config.py:45` sets
`samples_per_tx = 10**6`. Every published figure in `docs/renders/` (coverage,
SINR, mmWave, frequency sweep, drive test) therefore comes from an unseeded
stochastic process.

**What this does and does not mean.** With 10⁶ samples per transmitter the
run-to-run variance is likely small — but *we have not measured it*, and no
tolerance is documented anywhere. A reviewer asking "if I run this, do I get your
figure?" currently has no answer, and neither do we. That is the gap, not an
assertion that the numbers are wrong.

Reference practice: SB3's `test_deterministic.py` asserts **exact** equality at a
fixed seed. We cannot promise exact equality for a ray tracer without seeding
every solver, and we should not claim reproducibility we have not tested — see
the implementation principle *"Do not claim full reproducibility unless it has
been independently tested."*

**Rating: Weak.** This is the one item that could undermine review.

---

## 1. Paper-to-code alignment — **Strong**

**Confirmed facts.**

- `research-paper/README.md` is a paper index with a **"Which code backs which
  paper" table** mapping paper #2 to `ulap-scope/`, `blender/` and
  `docs/renders/`. Very few projects do this explicitly.
- `CITATION.cff` (CFF 1.2.0) carries authors, affiliation, abstract, keywords,
  Apache-2.0, version 0.1.0, and a **commented-out reference block with a
  `arXiv:TODO` placeholder** plus an instruction to mirror the update in
  `research-paper/README.md` when the ID exists. That is exactly the right
  discipline for an unannounced paper — the placeholder is visible and
  actionable rather than silently absent.
- Paper #1 (SIDSense, arXiv:2602.13542) is listed with full BibTeX and marked
  **"Not in this repository"**, which prevents a reader from assuming this code
  backs it.
- An "In preparation" table explicitly says *"Do not cite until an arXiv
  identifier exists."*

**Gaps.**

- **No figure-to-command mapping.** `docs/renders/` holds twelve figures used in
  the README, but nothing states which stage, config and study produced each one.
  This is the MMDetection model-zoo row applied to our case, and it is the single
  highest-value addition for reviewers.
- **Stale reference:** `research-paper/README.md` points at `blender/` as
  paper-backing code, but as of `7d28fb0` `blender/` is a working directory with
  only three tracked files. The table needs updating.
- The released code is a **later library version** than the figures were produced
  with, and this is not stated. The figures predate today's refactor.

---

## 2. First-time user experience — **Strong** (recently, and deliberately)

**Confirmed facts.** `examples/` provides a genuine on-ramp, verified today on a
simulated fresh clone in clean Python 3.11 and 3.12 virtualenvs:

- **Steps to first meaningful output: 3** — `cd examples`,
  `pip install -r requirements.txt`, open a notebook. Dependencies are numpy +
  matplotlib (+ streamlit for one app).
- **CPU-only**, no GPU anywhere in the demo path.
- Expected outputs are shown: notebooks print their own numbers, and
  `README.md` lines 35–96 show twelve result figures on the first screen.
- Three runnable apps and four notebooks; all execute with zero errors.
- Common installation problems are documented in
  `examples/apps/coverage_explorer/README.md` (missing streamlit, port in use,
  slow grid) and `examples/data/README.md` (Overpass rate limiting, with an
  offline `--osm-json` path).

This compares well with SAM's "excellent" rating and beats MMDetection's
config-first onboarding.

**Gaps.**

- The **full pipeline** remains a three-interpreter install (`ulap-scope/README.md`
  documents prep / Blender / RT environments). This is inherent to the domain —
  no single environment hosts GDAL, `bpy` and Sionna — but the README does not
  set expectations about how long that takes or what hardware it needs.
- **No pretrained-equivalent artifact.** SAM ships checkpoints; our analogue is a
  *built scene* (`scene_manifest.json` + Mitsuba XML). We ship an open-data scene
  for the demos but no exported Mitsuba scene, so a user cannot skip the Blender
  stage to try the RT stages.

---

## 3. Reproducibility — **Partial**, dragged down by the seed finding

| Item | Status | Evidence |
|---|---|---|
| Random seeds | ❌ **Weak** | 1 of 8 solver calls seeded |
| Dataset versions | ✅ Strong | `DATA.md` lists 18 layers with source and sensitivity |
| Dataset preparation | ✅ Strong | `ulap-scope clip/preprocess`; `scripts/check_data.sh` |
| Train/val/test splits | N/A | Not a learning pipeline |
| Dependency versions | ✅ Strong | `sionna-rt==2.0.1`, `mitsuba==3.5.0` pinned; `environment-prep.yml`, `environment-rt.yml` |
| Hardware requirements | ❌ **Absent** | No CPU/RAM/disk figure anywhere |
| Training/run duration | ❌ **Absent** | No runtime for any stage |
| Memory requirements | ❌ **Absent** | MMDetection publishes Mem (GB) per row |
| Hyperparameters | ✅ Strong | `config.py` centralises freq, power, bandwidth, `cell_size_m`, `max_depth`, `samples_per_tx` |
| Evaluation commands | ✅ Strong | `ulap-scope <stage>`, `make` targets |
| Expected metrics + tolerance | ⚠️ **Partial** | Only in `examples/tests` (`n = 1.73 ± 0.02`); nothing for the RT figures |
| Pretrained checkpoints | ⚠️ Partial | No exported scene published |
| Raw result files | ⚠️ Partial | `link_metrics.csv` shipped; the radio-map arrays are not |

**Notable strength.** `examples/tests/test_ulap_demo.py` contains
`test_ray_traced_exponent_is_sub_free_space`, which asserts the shipped RT data
fits `n = 1.73 ± 0.02` with RMS residual < 0.3 dB — **a scientific regression
test in the SB3 sense**, guarding a paper claim. The pattern exists; it is just
not applied to the RT stages themselves.

**No single reproduce-everything command.** `ulap-scope all` runs the pipeline
but requires restricted data and three environments; there is no
`reproduce_main_results` entry point and no documented expected output.

---

## 4. Experiment architecture — **Partial**

**Confirmed facts.** Configuration is centralised in
`ulap-scope/ulap_scope/config.py` (frozen dataclass, env-overridable) and
`study.toml` is a versioned, schema'd study definition (`ulap_scope/study.py`,
`SCHEMA_VERSION = 1`) with validation and TOML round-tripping. `docs/ARCHITECTURE.md`
states the principle explicitly: *"Config over code. All physics/geometry
parameters … "*.

**Gaps versus MMDetection.**

- **`study.toml` does not yet drive the pipeline.** `openspec/` declares
  `apply-study-config` as a *proposed, unimplemented* change, and
  `ulap-scope/README.md` confirms: *"Pointing the stage scripts at a `study.toml`
  is the follow-up change `apply-study-config`."* So today the wizard writes a
  study spec that the stages ignore, and the actual parameters come from
  `config.py` defaults. **A reader could reasonably assume `study.toml` is the
  scientific record when it currently is not.**
- **No config inheritance and no per-experiment config files.** There is one
  global config, so a baseline / proposed / ablation distinction cannot be
  expressed as data. The frequency sweep, mmWave run and terrain variants are
  differentiated by `--mode` flags and hard-coded lists inside stage scripts
  (e.g. `FREQS = [1.8e9, 3.5e9, 6.0e9, 10.0e9]` in `sionna_analysis.py`).

**Honest note:** MMDetection's registry/factory machinery is *not* what we need.
What we need is the small version: one directory of study/config files, one
launch verb, and the guarantee that a figure names its config.

---

## 5. Software architecture — **Strong**

**Confirmed facts.** Clean separation, and the boundary is enforced by testing:

| Component | Location |
|---|---|
| Config | `ulap_scope/config.py` |
| Study spec | `ulap_scope/study.py`, `wizard.py` |
| Geo/maths core | `ulap_scope/geo.py` — *dependency-light and unit-tested by design* |
| Stage runner | `ulap_scope/pipeline.py` (out-of-process, per-interpreter) |
| CLI | `ulap_scope/cli.py` |
| Stages | `ulap_scope/stages/*.py` (10 scripts) |
| Demo model | `examples/ulap_demo/{scene,propagation,plotting}.py` |

`geo.py`'s docstring states the design rule: *"kept free of Blender / Sionna /
GDAL so they import in any environment and are cheap to unit-test."* This is the
Lightning principle — science separated from infrastructure — arrived at
independently.

**Extension points, assessed honestly:**

- *New study area* — **excellent**, `ulap-scope init` or `fetch_open_scene.py`.
- *New propagation model* — **good** in `examples/`, `PropagationModel` is a
  dataclass with clear switches.
- *New RT analysis* — **weak**. Requires writing a new stage script and
  registering it in the `STAGES` dict in `cli.py`; stage scripts duplicate
  scene-loading and overlay boilerplate.
- *New metric* — **weak**. Metrics are computed inline inside stage scripts.

---

## 6. Testing and quality control — **Strong**

**Confirmed facts.**

- `ulap-scope`: **47 passed, 1 skipped**; `examples`: **75 passed**.
- Two CI workflows on Python **3.10 / 3.11 / 3.12**, plus a notebook-execution
  job that runs all four notebooks end to end.
- Test kinds present, mapped to the SB3 taxonomy:
  - *Runs* — `examples/tests` app smoke tests; `test_rt_smoke.py` (`-m rt`).
  - *Scientific behaviour* — `test_fspl_matches_closed_form`,
    `test_knife_edge_grazing_is_about_6_db`,
    `test_two_ray_average_is_the_incoherent_sum_below_breakpoint`,
    `test_model_reproduces_the_ray_traced_transect`.
  - *Guards a claim* — `test_ray_traced_exponent_is_sub_free_space`.
  - *Repository hygiene* — `test_no_developer_paths_in_tracked_files`,
    `test_no_geoportal_derived_scene_is_committed`,
    `test_blender_working_dir_is_not_tracked`.
- `docs/security-triage.md` records a semgrep run with **accepted-not-fixed
  rationale per finding** — a level of security honesty none of the seven
  reference projects displayed.

**Gaps.** No linter or formatter in CI (SB3 uses black + mypy and badges both);
no type checking; no dependency scanning (`dependabot.yml` exists in
Transformers, not here); no coverage measurement.

---

## 7. Documentation — **Strong**

**Confirmed facts.** `README.md` is 313 lines with a clear hierarchy: purpose →
results preview (12 figures) → 60-second try-it → architecture (Mermaid) →
repository layout → quickstart → reproduction path → tests → specs →
contributing → citing → security → license. Supporting docs: `DATA.md`,
`docs/ARCHITECTURE.md`, `docs/security-triage.md`, `ulap-scope/README.md`,
`examples/README.md` + three app READMEs + `examples/data/README.md`,
`openspec/`.

**Gaps.**

- **No `CHANGELOG.md`** (PyG's is the model).
- No troubleshooting/FAQ page for the *pipeline* (the examples have one; the
  three-environment install does not).
- No docs website — correctly deferred; the README hierarchy is doing the job.
- **No `results/` directory** and no `expected_metrics.json`.

---

## 8. Community design — **Partial**

**Confirmed facts — and we are ahead of most references here.** Root files:
`README.md`, `LICENSE`, `NOTICE`, `CITATION.cff`, `CONTRIBUTING.md`,
`CODE_OF_CONDUCT.md`, `SECURITY.md`, `DATA.md`.

> Comparison: **SAM** ships 4 such files and has **no `.github/` directory at
> all**. **Detectron2** ships 2. Only **Transformers** clearly exceeds us.

`CONTRIBUTING.md` is unusually good on *scientific* contribution: it requires
spec-first change proposals, states *"Reproducibility is the product"*, tells
contributors to regenerate figures when results change, and asks PR bodies to
describe *"what changed in the physics/geometry … not just the code"*.

**Gaps.**

- **No issue templates.** All three deeply-studied projects have them; MMDetection's
  `reimplementation_questions.md` is directly applicable to us.
- **No PR template**, though `CONTRIBUTING.md` describes what a PR body should say.
- **No `good first issue` / `help wanted` labelling convention documented.**
- No contributor recognition, release cadence, or deprecation policy.
- `.github/` contains **only** `workflows/`.

---

## 9. Packaging and licensing — **Strong**

**Confirmed facts.**

- **Apache-2.0** (`LICENSE`, README lines 295+), chosen over MIT for the express
  patent grant — reasoning documented, which is rare.
- `NOTICE` present; vendored add-ons are **git submodules** with upstream
  licences (BlenderGIS GPL-3.0, mitsuba-blender BSD-3-Clause) rather than copied
  code — cleaner than vendoring.
- `pyproject.toml`: setuptools, `requires-python = ">=3.10"`, `license = "MIT"`.
- `DATA.md` gives per-layer provenance, licence and sensitivity for 18 layers,
  plus a live Government of Barbados disclosure review. **Better than any
  reference project's data statement.**
- `CITATION.cff` present and valid.

**🟠 Licence inconsistency — confirmed, needs a decision.**
`ulap-scope/pyproject.toml` declares `license = "MIT"`, while the repository
`LICENSE` is Apache-2.0 and `README.md` states *"Apache-2.0 for this repository,
including the `ulap-scope` package"*, as does `CITATION.cff`. **Three sources say
Apache-2.0; the package metadata says MIT.** Whatever is installed from
`ulap-scope/` therefore advertises the wrong licence. This is a legal matter, not
a typo to silently fix — flagged for approval.

**Other gaps.** Not published to any package registry (so `pip install
ulap-scope` does not work); no versioned releases or tags; no contributor licence
terms (Apache-2.0 §5 covers inbound contributions by default, but this is not
stated).

---

## 10. Communication and presentation — **Strong**

**Confirmed facts.** The README leads with a one-line purpose, an ASCII figure,
and twelve real result figures before any installation instruction. Limitations
are stated prominently and repeatedly — README lines 79–83 warn about projection
distortion, optimistic `itu_` materials, flat-top extrusions and *"no field
calibration yet"*; `examples/` repeats the analytical-vs-ray-traced caveat in
four places. **Understating claims is a consistent habit here**, which is the
right instinct for a research release.

**Gaps.** No badges (SB3 shows CI / docs / coverage / code-style); no explicit
"Limitations" or "Ethical considerations" section as a heading, though the
content exists scattered; no known-failure-cases list.

---

## Gap analysis

### 🔴 Critical before submission

| # | Gap | Evidence |
|---|---|---|
| C1 | **7 of 8 ray-tracing solver calls are unseeded**; published figures are unseeded Monte Carlo with no measured variance or tolerance | Table above |
| C2 | **No figure → command/config mapping.** Twelve figures in `docs/renders/` with no record of what produced them | `docs/renders/`, README lines 35–96 |
| C3 | **No expected results with tolerances** for any RT output | No `results/`; only `examples/tests` covers the CSV |
| C4 | **Licence inconsistency**: `pyproject.toml` says MIT, everything else says Apache-2.0 | `ulap-scope/pyproject.toml` vs `LICENSE`, `README.md`, `CITATION.cff` |
| C5 | **No runtime, memory or hardware figures** for any stage | Grep across all docs returns nothing |

### 🟠 Important before public release

| # | Gap | Evidence |
|---|---|---|
| I1 | No issue templates — especially an irreproducible-result template | `.github/` has only `workflows/` |
| I2 | No PR template | as above |
| I3 | No `CHANGELOG.md` | root listing |
| I4 | `study.toml` does not drive the pipeline, but reads as if it does | `openspec/changes/apply-study-config` unimplemented |
| I5 | `research-paper/README.md` cites `blender/` as paper-backing code; it is now a 3-file working dir | post-`7d28fb0` |
| I6 | No pipeline-level troubleshooting/FAQ for the 3-environment install | `ulap-scope/README.md` |
| I7 | No exported scene artifact, so RT stages can't be tried without Blender | — |

### 🟡 Valuable after release

| # | Item |
|---|---|
| V1 | `results/` with `expected_metrics.json` + `environment_information.txt` |
| V2 | Documentation website |
| V3 | Publish `ulap-scope` to PyPI; tag versioned releases |
| V4 | Linting/formatting/type-checking in CI; coverage badge |
| V5 | A `studies/` directory of community-contributed study areas (the Detectron2 `projects/` pattern) |
| V6 | GitHub Discussions; `good first issue` curation |

### ⛔ Avoid for now

| Practice | Why |
|---|---|
| Registry/factory architecture (MMDetection) | We have one pipeline and no model zoo; abstraction cost exceeds benefit |
| Model zoo with hosted checkpoints | Nothing to host — our artifact is a scene, not weights |
| Separate benchmark repository (SB3's RL Zoo) | Splits a small project across two repos |
| Hosted web demo (SAM) | Ongoing cost and maintenance for a team this size |
| i18n / bilingual READMEs (MMDetection) | Premature |
| Large CI matrix | Current 3-version matrix is proportionate |

---

## Positioning note

The brief observes that advanced work of this kind is rarely seen coming out of
the Global South. Three properties of this repository bear directly on that, and
are currently **understated**:

1. **It runs on a CPU.** `ulap-scope/README.md`: *"Everything runs on CPU
   (Mitsuba LLVM backend) — no CUDA required."* Every reference project assumes
   GPU access. This is the difference between a researcher with a laptop being
   able to use this or not, and it is buried in a sub-README rather than being a
   headline claim.
2. **It works anywhere, on open data.** `fetch_open_scene.py` builds a study
   scene for any coordinate on earth from OSM + open elevation, with no API key.
   That is the strongest adoption hook the project has — a researcher in Nairobi
   or Suva can twin *their* city in one command — and it is currently documented
   as a data-provenance detail rather than as the invitation it is.
3. **Data sovereignty is treated as a first-class engineering concern**, not a
   compliance afterthought. `DATA.md` is more rigorous than any reference
   project's data statement.

These are differentiators, not caveats, and the README should say so plainly
without overstating what the pipeline has been validated to do.
