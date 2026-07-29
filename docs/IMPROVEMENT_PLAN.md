# Improvement Plan

Prioritised, with the smallest high-impact set first. Each item states the
recommendation, why, which reference project supports it, files affected,
effort, risk, and how we know it is done.

**Approval gates.** Items marked 🔒 **change scientific behaviour, public API,
licensing or data handling** and are *not* implemented without explicit
approval, per the brief. Items marked ✅ are safe, additive, and behaviour-preserving.

Effort: **S** ≤ 1 h · **M** ≤ half a day · **L** > a day.

---

## Tier 1 — Critical before paper submission

### 1.1 🔒 Seed every ray-tracing solver, or measure and publish the tolerance

| | |
|---|---|
| **Recommendation** | Add a `seed` to `config.py` and thread it through all 8 solver invocations. If exact determinism proves impossible, run each stage N times, measure per-cell variance, and publish a tolerance instead. |
| **Reason** | 7 of 8 solver calls are unseeded Monte Carlo at `samples_per_tx = 10**6`. No reviewer can currently answer "will I get your figure?" — and neither can we. |
| **Reference** | SB3 [`tests/test_deterministic.py`](https://github.com/DLR-RM/stable-baselines3/blob/master/tests/test_deterministic.py) trains twice at `SEED=0` and asserts **exact** equality. |
| **Files** | `ulap_scope/config.py`, `stages/sionna_{coverage,analysis,animate_rx,mmwave_sinr,terrain_ground}.py` |
| **Effort** | M (threading) + L (if variance must be measured) |
| **Risk** | **High — changes published numbers.** Seeding makes runs deterministic but the seeded result will differ from the current unseeded figures, so `docs/renders/` must be regenerated and the paper figures re-checked. |
| **Acceptance** | Running any RT stage twice produces byte-identical output, verified by a test in the `-m rt` suite; **or** a documented tolerance with the measurement that produced it. |

> **Decision needed.** This is the single most important item and the one I will
> not start unilaterally: it invalidates and regenerates every published figure.

### 1.2 ✅ Figure provenance table

| | |
|---|---|
| **Recommendation** | `docs/renders/README.md`: one row per figure — figure, producing stage, `--mode`, key parameters, source scene, commit. |
| **Reason** | Twelve figures are shown on the README's first screen with no record of what produced them. This is the highest-value reviewer-facing artifact available to us. |
| **Reference** | MMDetection [`configs/faster_rcnn/README.md`](https://github.com/open-mmlab/mmdetection/blob/main/configs/faster_rcnn/README.md) — every number links to config, weights and log. |
| **Files** | new `docs/renders/README.md`; link from `README.md` and `research-paper/README.md` |
| **Effort** | S–M (the facts must be recovered from stage scripts, not invented) |
| **Risk** | Low — documentation only. **Any parameter I cannot confirm from code will be marked `unverified` rather than guessed.** |
| **Acceptance** | Every file in `docs/renders/` has a row; a reader can name the command for each figure. |

### 1.3 🔒 Resolve the licence inconsistency

| | |
|---|---|
| **Recommendation** | Change `ulap-scope/pyproject.toml:11` from `license = "MIT"` to `Apache-2.0`. |
| **Reason** | `LICENSE`, `README.md:297` and `CITATION.cff` all say Apache-2.0; the package metadata says MIT, so anything installed from `ulap-scope/` advertises the wrong licence. |
| **Reference** | SAM states code, model and dataset licences separately and consistently. |
| **Files** | `ulap-scope/pyproject.toml` |
| **Effort** | S |
| **Risk** | **Legal, not technical.** A one-word change, but it changes the terms under which the package is offered. Requires your confirmation that Apache-2.0 is intended. |
| **Acceptance** | All four sources agree. |

### 1.4 ✅ Environment and cost record

| | |
|---|---|
| **Recommendation** | `results/environment_information.txt` — solver versions, OS, CPU model, RAM, and measured wall-clock + peak memory per stage. |
| **Reason** | No runtime, memory or hardware figure exists anywhere. A reader cannot judge the cost of reproduction. |
| **Reference** | MMDetection publishes **Mem (GB)** and **Inf time (fps)** beside accuracy. |
| **Files** | new `results/environment_information.txt` |
| **Effort** | M — **requires actually running the stages and measuring**; numbers will not be invented. |
| **Risk** | Low. Needs the restricted data (or an open-data study) to run. |
| **Acceptance** | Each stage has a measured runtime and peak RSS on named hardware. |

---

## Tier 2 — Important before public release

### 2.1 ✅ Issue templates, including an irreproducible-result template

| | |
|---|---|
| **Recommendation** | `.github/ISSUE_TEMPLATE/`: `bug_report.yml`, `reproduction_problem.yml`, `study_area_help.yml`, `feature_request.yml`, `config.yml`. |
| **Reason** | `.github/` currently holds only `workflows/`. A reproduction failure is the report we most need to be diagnosable. |
| **Reference** | MMDetection [`reimplementation_questions.md`](https://github.com/open-mmlab/mmdetection/blob/main/.github/ISSUE_TEMPLATE/reimplementation_questions.md) asks for command, config dir, modifications, dataset, `collect_env.py` output, and "what you expect and what you get". SB3 ships 5 templates including `question.yml`. |
| **Files** | new `.github/ISSUE_TEMPLATE/*` |
| **Effort** | S |
| **Risk** | None |
| **Acceptance** | Opening an issue offers typed choices; the reproduction template requires `ulap-scope info` output and expected-vs-actual. |

### 2.2 ✅ PR template

Reference: SB3 and Transformers both ship one. Ours should encode
`CONTRIBUTING.md`'s existing rule — *describe what changed in the
physics/geometry, not just the code* — plus a figure-regeneration checkbox.
Files: `.github/PULL_REQUEST_TEMPLATE.md`. Effort S. Risk none.

### 2.3 ✅ `CHANGELOG.md`

Reference: [PyG's](https://github.com/pyg-team/pytorch_geometric/blob/master/CHANGELOG.md)
Keep-a-Changelog format with PR links. Files: new `CHANGELOG.md`. Effort S.
Risk none. Acceptance: today's work is recorded under `[Unreleased]`.

### 2.4 ✅ Correct the two stale documentation claims

- `research-paper/README.md` cites `blender/` as paper-backing code; it is now a
  3-file working directory (I5).
- `study.toml` reads as the scientific record but **does not drive the
  pipeline** — `apply-study-config` is unimplemented (I4). One sentence in
  `README.md` and `ulap-scope/README.md` prevents a reader assuming otherwise.

Effort S. Risk none — this *removes* an overclaim.

### 2.5 ✅ Pipeline troubleshooting guide

The three-environment install is the main adoption barrier. `examples/` has
troubleshooting; the pipeline does not. Files: new
`docs/TROUBLESHOOTING.md`. Effort M. Risk none.

### 2.6 🔒 Publish a built scene artifact

Ship an exported Mitsuba scene from the **open-data** study so users can run RT
stages without Blender. Analogous to SAM's checkpoints. **Gated**: must be built
from `newton-open_scene_manifest.json`, never geoportal data, and adds a binary
artifact to a repo we just shrank to 20 MB. Effort L. Risk medium (repo size,
licensing).

---

## Tier 3 — Valuable after release

| # | Item | Reference | Effort |
|---|---|---|---|
| 3.1 | `results/expected_metrics.json` + a test asserting against it | SB3 determinism test | M |
| 3.2 | Lint/format/type-check in CI (ruff + mypy) with badges | SB3 badges: CI, docs, coverage, black | M |
| 3.3 | Publish to PyPI; tag versioned releases | PyG, SB3 | M |
| 3.4 | `studies/` — community-contributed study areas as first-class dirs | Detectron2 [`projects/`](https://github.com/facebookresearch/detectron2/tree/main/projects) (10 paper implementations) | M |
| 3.5 | Documentation website | Transformers, MMDetection | L |
| 3.6 | GitHub Discussions + curated `good first issue`s | Transformers | S |

**3.4 is the one to prioritise post-release.** `fetch_open_scene.py` already
builds a scene anywhere on earth; a `studies/` directory turns that capability
into a contribution pathway — *"add your city"* is a far more approachable first
contribution than *"add a propagation model"*, and it directly serves the goal of
seeing this work adopted across the Global South.

---

## Tier 4 — Explicitly not doing

| Practice | Reference | Why not |
|---|---|---|
| Registry/factory architecture | MMDetection | One pipeline, no zoo — abstraction cost exceeds benefit |
| Hosted model zoo | MMDetection, Detectron2 | Our artifact is a scene, not weights |
| Separate benchmark repo | SB3's RL Zoo | Splits a small project in two |
| Hosted web demo | SAM | Ongoing cost beyond our resourcing |
| Bilingual README | MMDetection | Premature |
| Large CI matrix | Transformers | Current 3-version matrix is proportionate |

---

## Recommended structure, adapted

The brief's proposed layout, mapped to what we actually need. **Directories we
do not need are not created.**

```text
README.md  LICENSE  NOTICE  CITATION.cff  CONTRIBUTING.md
CODE_OF_CONDUCT.md  SECURITY.md  DATA.md          ← all present
CHANGELOG.md                                      ← 2.3, add

.github/
  workflows/                                      ← present
  ISSUE_TEMPLATE/                                 ← 2.1, add
  PULL_REQUEST_TEMPLATE.md                        ← 2.2, add

ulap-scope/          ← the package (= brief's src/ + scripts/); keep the name
  ulap_scope/{config,geo,study,wizard,pipeline,cli}.py
  ulap_scope/stages/                              ← = brief's scripts/
  tests/                                          ← present
examples/            ← = brief's examples/ + notebooks/; present
docs/                ← present
openspec/            ← spec-first change control; no reference project has this
results/                                          ← 1.4 / 3.1, add
  environment_information.txt
  expected_metrics.json
```

**Deliberately not adopted:**

- `configs/{baselines,proposed_method,ablations}/` — we have one pipeline and no
  baseline/proposed split. Revisit if `apply-study-config` lands and study files
  become the experiment unit.
- `src/{data,models,training,evaluation,metrics}/` — the ML layout does not fit a
  geospatial→RT pipeline. `ulap_scope/` already separates config, geo core, stage
  runner and stages.
- `tests/{unit,integration,smoke}/` — tests already live beside their packages,
  with `-m rt` separating integration from unit. Splitting by kind would scatter
  them across two packages for no gain.
- `scripts/prepare_data.*`, `train.*` — `ulap-scope <stage>` is the launch verb;
  a second entry point would create two ways to do one thing.

---

## Sequencing

1. **Now, no approval needed** — 1.2 figure provenance, 2.1 issue templates,
   2.2 PR template, 2.3 changelog, 2.4 stale-claim corrections.
2. **Needs your decision** — 1.1 seeding (regenerates all figures), 1.3 licence,
   2.6 scene artifact.
3. **Needs a run on real data** — 1.4 environment/cost record.
4. **After release** — Tier 3, starting with `studies/`.

Items in (1) are additive, behaviour-preserving, and independently verifiable.
Everything that could change a number, a licence, or an API is in (2).
