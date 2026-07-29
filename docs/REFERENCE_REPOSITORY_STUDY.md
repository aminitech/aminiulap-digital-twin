# Reference Repository Study

What seven well-regarded paper-with-code projects actually do, and which of it
transfers to a first research release from a small team.

**Method.** Every claim below is grounded in a file or page fetched on
2026-07-29, cited inline. Where a reference project *lacks* a practice, that is
recorded too — the point is to copy what works, not to assume popularity implies
rigour. Ratings are evidence-based, never derived from stars.

**Scale caveat.** Transformers, MMDetection and Lightning are staffed
engineering organisations. Their practices are studied for *mechanism*, not
volume. A first paper release that imitates their surface area will collapse
under its own maintenance cost.

---

## 1. Stable-Baselines3 — the correctness exemplar

*Priority study #1: correctness, testing, benchmarking, scientific reliability.*

**The transferable insight: SB3 separates three kinds of test, and names them.**
From the `tests/` listing ([contents API](https://github.com/DLR-RM/stable-baselines3/tree/master/tests)):

| Test | Size | What it guards |
|---|---|---|
| `test_run.py` | 7.7 kB | *Does it execute* — smoke |
| `test_deterministic.py` | 1.4 kB | *Is it reproducible* — scientific |
| `test_identity.py` | 2.1 kB | *Does learning actually learn* — behavioural |
| `test_gae.py`, `test_distributions.py`, `test_preprocessing.py` | 6.9–9.9 kB | Numerical correctness of individual maths |
| `test_save_load.py` | 34.5 kB | Round-trip integrity — the largest single file |

`test_deterministic.py` is the highest-value pattern for us. It trains each of
A2C, DQN, PPO, SAC and TD3 **twice with `SEED = 0`** and asserts **exact
equality**, not a tolerance:

```python
assert sum(results[0]) == sum(results[1]), results
assert sum(rewards[0]) == sum(rewards[1]), rewards
```

That is a scientific guarantee expressed as a unit test. It costs ~1.4 kB.

**Benchmarks live outside the library.** The README points to
[RL Baselines3 Zoo](https://github.com/DLR-RM/rl-baselines3-zoo) for "training,
evaluating agents, tuning hyperparameters" and "a collection of tuned
hyperparameters for common environments", with results hosted on the OpenRL
Benchmark (wandb). The core repo stays small; the benchmark burden is a separate
artifact.

**Honest negative:** the docs' [examples page](https://stable-baselines3.readthedocs.io/en/master/guide/examples.html)
has **no dedicated reproducibility section**. `set_random_seed` appears only
inside a multiprocessing example, with no discussion of nondeterminism sources.
Even the correctness exemplar under-documents seeding in prose — it encodes it
in a test instead. That is arguably the better choice, and it is the one we can
afford.

**Scope discipline:** the README states development is "focused on bug fixes and
maintenance", with newer algorithms in a *contrib* repository. Saying "this is
stable, new work goes elsewhere" is a maintenance strategy, not an admission.

---

## 2. MMDetection — the configuration and model-zoo exemplar

*Priority study #2: experiment configuration, modularity, model zoos, reproducibility.*

**The transferable insight: every reported number is a row that links to the
config that produced it, the weights, and the training log.** From
[`configs/faster_rcnn/README.md`](https://github.com/open-mmlab/mmdetection/blob/main/configs/faster_rcnn/README.md):

| Backbone | Style | Lr schd | Mem (GB) | Inf time (fps) | box AP | Config | Download |
|---|---|---|---|---|---|---|---|
| R-50-FPN | pytorch | 1x | 4.0 | 21.4 | 37.4 | config | model \| log |

Note what the columns *include*: **memory and inference time alongside
accuracy**. Cost of reproduction is treated as part of the result. The `log` link
resolves to a JSON of training metrics — the raw evidence, not a summary.

**Configuration is inheritance, not duplication.** From
[`docs/en/user_guides/train.md`](https://github.com/open-mmlab/mmdetection/blob/main/docs/en/user_guides/train.md):

```python
_base_ = '../mask_rcnn/mask-rcnn_r50-caffe_fpn_ms-poly-1x_coco.py'
```

with runtime overrides via `--cfg-options 'Key=value'`, and one launch verb:
`python tools/train.py ${CONFIG_FILE}`. Baseline, proposed method and ablation
all use the same command; the only thing that varies is a file under version
control. That is the mechanism that prevents undocumented differences between
experiments.

**They ask reproducers for structured evidence.** The issue template
[`reimplementation_questions.md`](https://github.com/open-mmlab/mmdetection/blob/main/.github/ISSUE_TEMPLATE/reimplementation_questions.md)
requires: the command run, the config dir, whether the user modified code *"Did
you understand what you have modified?"*, the dataset, `collect_env.py` output,
install method, relevant environment variables, and **"what you expect and what
you get"**. This converts "your numbers are wrong" into a diagnosable report.

**Honest negative:** `train.md` contains **no discussion of random seeds,
determinism flags, or reproducibility**. The most config-rigorous project studied
does not document seeding in its training guide.

---

## 3. Segment Anything — the adoption exemplar

*Priority study #3: accessible launch, demonstrations, checkpoints, adoption.*

**The transferable insight: the first screen answers "what does this do" in one
sentence, with no framework vocabulary.**

> "Segment Anything Model (SAM) produces high quality object masks from input
> prompts such as points or boxes, and it can be used to generate masks for all
> objects in an image."

**Two entry points, not twenty.** `SamPredictor` (prompted) and
`SamAutomaticMaskGenerator` (automatic). A new user picks in seconds.

**Graded install paths (four), cheapest first:** one-line
`pip install git+https://…`; clone + `pip install -e .`; optional extras
(`opencv-python pycocotools matplotlib onnxruntime onnx`); and a CLI
`python scripts/amg.py`. Optional dependencies are *marked optional* rather than
demanded up front.

**Licensing is stated per artifact.** Code and model are Apache-2.0; the SA-1B
dataset sits behind a separate research licence the user must accept. Model
licence, code licence and data licence are **three different questions** and SAM
answers each — directly relevant to us, where geoportal data, vendored add-ons
and our own code have three different statuses.

**Minimal community surface:** only `README`, `LICENSE`, `CONTRIBUTING.md`,
`CODE_OF_CONDUCT.md` at root; no `.github/` directory at all (404). A landmark
release shipped with *less* community infrastructure than we already have.

---

## 4–7. Supporting projects

**Hugging Face Transformers** — the most complete community infrastructure of
the seven: `CODE_OF_CONDUCT.md`, `CONTRIBUTING.md`, `SECURITY.md`,
`CITATION.cff`, `MIGRATION_GUIDE_V5.md`, `dependabot.yml`, and **six issue
templates**: `bug-report.yml`, `feature-request.yml`, `new-model-addition.yml`,
`migration.yml`, `i18n.md`, `config.yml`. The templates encode the contribution
*types they want*. A dedicated "add a new model" template is a standing
invitation to a specific kind of contribution.

**PyTorch Geometric** — release discipline via
[`CHANGELOG.md`](https://github.com/pyg-team/pytorch_geometric/blob/master/CHANGELOG.md)
following [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), with
`[Unreleased]` / `Added` / `Changed` / `Deprecated` sections and **every entry
linking to its PR**. Cheap to maintain, and it makes the project legible over
time.

**Detectron2** — the strongest *extensibility* pattern:
[`projects/`](https://github.com/facebookresearch/detectron2/tree/main/projects)
contains ten paper implementations (DensePose, PointRend, ViTDet, TridentNet,
MViTv2, …) as first-class directories inside the main repo. New research lands
beside the library without forking it or bloating the core. Root is minimal —
**only `LICENSE` and `README.md`** — with everything else under `docs/`
(`tutorials`, `notes`, `modules`).

**PyTorch Lightning** — `CITATION.cff` + `SECURITY.md` at root, Apache-2.0.
Confirms the pattern: mature projects converge on machine-readable citation plus
a security policy, and push everything else into `docs/`.

---

## Required comparison table

Ratings: **Excellent / Strong / Partial / Weak / N/A**. Evidence is the basis for
each rating; popularity is not.

| Project | Main research contribution | Quick start quality | Reproducibility | Architecture | Testing | Documentation | Community pathway | Best practice to copy | Practice not suitable for us |
|---|---|---|---|---|---|---|---|---|---|
| **Stable-Baselines3** | Reliable RL algorithm implementations (JMLR 22:268) | **Strong** — 13-line full example plus a 3-line "one liner" | **Strong** — `test_deterministic.py` asserts exact equality at `SEED=0` across 5 algorithms; but no prose reproducibility section in the docs | **Strong** — one `BaseAlgorithm` interface; contrib repo for new algorithms | **Excellent** — 25 test modules separating smoke / determinism / learning-works / numerical / save-load | **Strong** — RTD site, migration guide | **Strong** — 5 issue templates incl. `question.yml` and `custom_env.yml`; PR template | **The determinism test as a unit test** — 1.4 kB that makes a scientific promise enforceable | Separate benchmark repo + wandb hosting; we have one pipeline, not a zoo |
| **MMDetection** | Detection toolbox & benchmark (arXiv 1906.07155) | **Partial** — powerful but config-heavy; new user must learn the config system first | **Excellent** — every result row links config + weights + training log, with Mem (GB) and fps reported | **Excellent** — `_base_` inheritance + `--cfg-options`; registry/factory for models & datasets | **Strong** — CI across versions | **Excellent** — bilingual (`README_zh-CN.md`), layered user/advanced guides | **Strong** — `reimplementation_questions.md` for irreproducible results | **The model-zoo row**: result ↔ config ↔ artifact ↔ log, with reproduction *cost* as a column | Full registry/factory abstraction and a hundreds-row zoo — we have one pipeline and no checkpoints |
| **Segment Anything** | Promptable segmentation foundation model (arXiv 2304.02643) | **Excellent** — one-sentence purpose, 4 graded install paths, 2 API entry points, hosted demo + 2 notebooks | **Partial** — checkpoints and inference reproduce; training data pipeline not released | **Strong** — deliberately two public classes | **Weak** — no visible test suite or CI in repo root | **Partial** — README + notebooks; no docs site | **Partial** — `CONTRIBUTING` + CoC only; **no `.github/` at all** | **First-screen clarity + per-artifact licensing** (code / model / dataset stated separately) | Hosted web demo and 11M-image dataset release — far beyond our resourcing |
| **Transformers** | Library + EMNLP 2020 demo paper | **Excellent** — pipeline example works in ~3 lines | **Partial** — model cards carry results; library version ≠ paper version | **Excellent** — uniform model API; `Auto*` factories | **Excellent** — very large CI matrix | **Excellent** — full docs site, tasks & conceptual guides | **Excellent** — 6 typed issue templates, dependabot, migration guide | **Typed issue templates that solicit the contributions you want** (e.g. `new-model-addition.yml`) | Its entire scale: CI matrix, i18n, release cadence — actively harmful to imitate at our size |
| **PyTorch Geometric** | GNN library (Fey & Lenssen 2019) | **Strong** — concise README examples | **Partial** — benchmarks documented; per-paper reproduction varies | **Strong** — composable `MessagePassing` base | **Strong** — CI + tests | **Strong** — docs site + `#cite` anchor in README | **Strong** — `CHANGELOG.md` with PR links | **Keep a Changelog discipline** — cheap, high legibility | Breadth of dataset/model coverage |
| **Detectron2** | Detection/segmentation platform | **Strong** — `GETTING_STARTED` + model zoo | **Strong** — model zoo maps configs to weights and metrics | **Excellent** — `projects/` holds 10 paper implementations as first-class dirs | **Strong** | **Strong** — everything in `docs/`, root holds only LICENSE + README | **Partial** — no CoC/CONTRIBUTING at root | **`projects/` as the home for paper-specific code** — extension without forking | Model zoo scale; GPU-first assumptions |
| **PyTorch Lightning** | Training abstraction (JMLR 23:21-1321) | **Strong** | **Partial** | **Excellent** — `LightningModule` separates science from engineering | **Excellent** | **Excellent** | **Strong** — `CITATION.cff` + `SECURITY.md` | **Separating scientific code from infrastructure as an architectural rule** | Framework-scale abstraction layers |

---

## Cross-cutting conclusions

**1. Reproducibility is enforced by artifacts, not promised by prose.** SB3
encodes it in a 1.4 kB test; MMDetection encodes it in a config file plus a
training log. Neither writes an essay about it. Ours should be a test and a
config, not a paragraph.

**2. A result is only a result if you can point at the file that produced it.**
The MMDetection row is the pattern: *number → config → artifact → log*. This is
the single most valuable practice for a paper release, and it does not require a
model zoo — it requires that each figure name the command that made it.

**3. Report the cost of reproduction.** MMDetection publishes Mem (GB) and fps
next to accuracy. A reader deciding whether to attempt reproduction needs to know
what it will cost them. We currently publish no runtime, memory or hardware
figure anywhere.

**4. Minimal community surface is normal at launch.** SAM shipped with four root
files and no `.github/`. Detectron2's root is two files. **Our repository already
has more community infrastructure than five of the seven** — the gap is not
governance documents, it is issue templates and a changelog.

**5. Say what is out of scope.** SB3 states it is stable and directs new
algorithms to contrib. Scope discipline is what makes maintenance survivable for
a small team.

**6. Licence each artifact separately.** SAM: code Apache-2.0, model Apache-2.0,
dataset under a distinct research licence. We have four categories — our code,
vendored add-ons (GPL-3.0 / BSD-3-Clause), open data (ODbL / public domain), and
restricted geoportal layers — and `DATA.md` already handles this better than most
references handle their single dataset.

---

## What none of the reference projects have, and we do

Recorded because it bears on positioning, and because it is genuinely unusual:

- **A data availability statement with per-layer provenance and a live
  redistribution review** (`DATA.md`). SAM points at a licence; we document
  fourteen layers, their sensitivity, and an open government review.
- **Spec-first change control** (`openspec/`). Behaviour changes land as a
  proposal with spec deltas before implementation. None of the seven does this.
- **CPU-only execution as a design constraint.** Every reference project assumes
  GPUs. A ray-tracing pipeline that runs on a laptop CPU is not a limitation to
  apologise for — it is the reason a researcher without cluster access can use
  it at all.
