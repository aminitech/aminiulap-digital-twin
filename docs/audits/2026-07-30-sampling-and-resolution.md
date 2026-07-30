# Audit — the sampling default and the spatial resolution of the two compared figures

**Date:** 2026-07-30
**Scope:** `sionna_terrain_ground.py`, `sionna_coverage.py`, and every published number
downstream of them
**Status:** both defaults changed, everything downstream re-run, one paper claim
invalidated outright and several more moved — including two that moved **against** the
argument they support

---

## Bottom line

Two decisions, both taken on a stated criterion and both measured before they were taken:

| | Was | Is | Why |
|---|---|---|---|
| `samples_per_tx` (ground-following) | 1e6 | **1e8** | 47 % of the map was unsampled rather than shadowed. 1e8 is the largest value that keeps the CPU/LLVM backend under 10 min per run |
| `samples_per_tx` (coverage) | 1e7 | **1e8** | the same estimator, and the two figures must carry the same noise |
| cell size (coverage) | 5 m | **8 m** | the paper prints the two maps side by side; they were on different grids |
| cell size (ground-following) | 8 m | **8 m** | unchanged — 8 m is the grid the estimator can actually fill |

Both are overridable and now share their environment variables so they cannot drift apart
again: `ULAP_RM_CELL_M`, `ULAP_RM_SAMPLES_PER_TX`, and the pre-existing
`ULAP_GF_SAMPLES_PER_TX` (which still works, and still wins for the ground-following stage).

**The honest headline is not the improvement.** It is that raising the sample count
revealed that about a quarter of the paper's "21.6 % of cells differ by more than 10 dB"
and **more than half of its "terrain changes the serving cell in 21.9 % of cells"** were
Monte-Carlo noise, not terrain. Those numbers are now 16.3 % and 10.0 %.

---

## Decision 1 — the sampling default

### The criterion, stated before the measurement

`RadioMapSolver` is a Monte-Carlo estimator: a cell that collects no ray hit reads zero
path gain and is plotted identically to a cell that is genuinely dark. The map exists to
support a claim about shadow. So the default was required to satisfy, in order:

* **S1 — fitness.** Most dark cells must be explainable by geometry that is *independent
  of the ray tracer*. Operationally: the fraction of "extra shadow" cells that the DTM +
  building-footprint line-of-sight march cannot explain must be **below 50 %**. This test
  already exists in `comparison/f8_plane_stack.py`; it was not invented for this decision.
* **S2 — convergence.** The no-coverage fraction the stage prints must be on the
  estimator's asymptote, not its steep slope: **within 2× of its value at ten times the
  samples**.
* **S3 — cost, and where the ceiling comes from.** Subject to S1 and S2, take the
  cheapest. The ceiling is not invented: `benchmarks/RASPBERRY-PI-4.md` publishes a
  **310 s full-pipeline** result on four Cortex-A72 cores as evidence for the paper's
  sovereignty claim, and `METHOD.md` runs 3 repeats × 2 backends. A default that puts one
  stage into the hours on the CPU/LLVM backend destroys a published claim to buy a
  cleaner figure. **Limit: ≤ 10 minutes per stage run on `llvm_ad_mono_polarized`.**

### What was measured

8 m cells, K = 57 planes, Newton scene, seed 42. GPU = GB10 `cuda_ad_mono_polarized`;
CPU = `llvm_ad_mono_polarized`, same host, 20 cores, `CUDA_VISIBLE_DEVICES=""`.

| samples/tx | plane map blank | gf map blank | unexplained by geometry | GPU stack (57 solves) | CPU stack (57 solves) |
|---|---|---|---|---|---|
| 1e6 *(was shipped)* | 44.34 % | 47.00 % | 85.1 % | 0.41 s | 15.1 s |
| 1e7 | 6.99 % | 10.99 % | 81.0 % | 1.02 s | 35.5 s |
| **1e8** *(chosen)* | **0.13 %** | **1.16 %** | **51.5 %** | **7.25 s** | **262 s** |
| 1e9 | 0.00 % | 0.24 % | 4.6 % | 69.06 s | 2383 s |

CPU per-solve figures are measured directly (0.265 s / 0.622 s / 4.604 s / 41.809 s at
1e6 / 1e7 / 1e8 / 1e9) and multiplied by K = 57; the GPU figures are the whole stack
timed end to end. CPU solve cost is **independent of cell size** (4.604 s at 8 m vs
4.698 s at 5 m at 1e8) — the LLVM backend is ray-bound, not grid-bound.

### The verdict, and it is not clean

**No value satisfies S1 and S2 inside the S3 ceiling. That is the result, and it is
reported as one rather than resolved by moving a criterion.**

* **1e8 misses S1 by 1.5 points** *(mechanism since identified — see `comparison/RESIDUAL.md`: the 51.5 % decomposes into 90.4 % grazing-incidence Monte-Carlo starvation and 9.6 % real shadow the S1 march under-resolved; 0.0 % remains unexplained under the proposed S1′ attribution)* (51.5 % unexplained against the 50 % bar) and **misses
  S2 by a factor of 2.4** (1.16 % against 0.24 % a decade later — a 4.9× fall where the
  bar was 2×).
* **1e9 passes S1 decisively** (4.6 % unexplained) but costs **2383 s ≈ 40 minutes per
  stage run on the CPU backend**, i.e. ~2 hours for one benchmark cell's three repeats and
  an estimated 5 hours on the Raspberry Pi 4 whose whole pipeline is currently 310 s. It
  fails S3 by more than two orders of magnitude. S2 is also *unproven* at 1e9 — the 1e10
  run needed to demonstrate it was not affordable, so even the value that passes S1 cannot
  be shown to be converged.

**1e8 is therefore chosen as a cost-bounded compromise and is documented as one, in the
code, in the stage's runtime output, and here.** At 1e8 the ground-following map is 1.16 %
blank against a converged dark fraction of 0.24 %: **roughly four fifths of the blank area
is still sample starvation, not shadow.** A dark cell still may not be read as shadow at
the default. Any claim about shadow *area* must be run at `ULAP_GF_SAMPLES_PER_TX=1e9`,
which reproduces the 0.24 % / 81 % ridge-corroborated result.

### Rejected, and why

* **1e6 (the status quo).** 47 % of the map unsampled. Indefensible; this is the defect.
* **1e7.** 11.0 % blank, 81 % of extra shadow unexplained. It costs 1.02 s of GPU solve
  against 1e8's 7.25 s — the saving is 6 s on the reference GPU and 227 s on CPU, for a
  map that is 9× more wrong. Rejected on S1.
* **1e9.** The only value that passes S1. Rejected on S3, on measured CPU cost, with the
  published Pi 4 result as the thing it would break. It is one environment variable away
  and the code says so.
* **A per-backend default** (1e9 on CUDA, 1e8 on LLVM) was considered and rejected: it
  would mean the two backends no longer produce comparable output, which is the
  determinism property `METHOD.md` rule 4 and `benchmarks/tables/determinism.tex` exist to
  test. A default that makes the CPU and GPU maps differ by construction is worse than a
  default that is honestly under-converged on both.

### Where the cost is unacceptable, stated plainly

The CPU/LLVM backend carries the paper's sovereignty claim, and it is where this change
hurts. `sionna_terrain_ground` on that backend goes from **1.86 s to ~262 s of solve** —
a 140× increase, from "instant" to "four and a half minutes", ×3 repeats. On a Raspberry
Pi 4 the same stage is estimated at **20–30 minutes**, against 14.2 s today. The Pi 4
result in `benchmarks/RASPBERRY-PI-4.md` has **not** been re-run and is now stale for
three of its five stages. That is a real regression in the "five minutes for the complete
study" story and it is not hidden in a median: the full pipeline on a Pi 4 is now
plausibly half an hour rather than five minutes. Someone should re-run the Pi.

---

## Decision 2 — the spatial resolution

### The criterion, stated before the measurement

* **R1 — resolve the geometry that casts the shadow.** The cell must be small enough that
  a typical building footprint is not aliased away.
* **R2 — the estimator must be able to fill it.** Halving the cell quarters the rays per
  cell. A grid the sampling default cannot fill publishes holes as detail. R2 and Decision
  1 are therefore coupled and were decided jointly.
* **R3 — do not discard published resolution without cause.** Between two values that pass
  R1 and R2, prefer the one already in the paper (5 m).

### What was measured

**R1, from the scene manifest — 576 footprints:**

| | value |
|---|---|
| median narrow dimension of a footprint | 12.88 m |
| p10 narrow dimension | 8.33 m |
| footprints narrower than one 8 m cell | **9.2 %** |
| footprints narrower than one 5 m cell | **3.8 %** |
| median √(true footprint area) | 11.72 m |
| DTM posting | 30.58 × 29.82 m |
| terrain relief inside one cell (median / p90 / max) | 8 m: 0.24 / 0.55 / 4.81 m · 5 m: 0.15 / 0.35 / 3.19 m |

**R2, at the 1e8 default (GPU, K = 57 stack):**

| cells | grid | plane map blank | gf map blank | GPU stack | CPU stack |
|---|---|---|---|---|---|
| **8 m** | 311 × 295 = 91 745 | **0.13 %** | **1.16 %** | **7.25 s** | 262 s |
| 5 m | 498 × 471 = 234 558 | 1.36 % | 3.54 % | 13.66 s | 268 s |

And at the *old* sample count, which is what the shipped code actually was:

| cells | samples | plane map blank | gf map blank |
|---|---|---|---|
| 5 m | 1e7 *(shipped `sionna_coverage.py`)* | **18.92 %** | 22.12 % |
| 8 m | 1e6 *(shipped `sionna_terrain_ground.py`)* | 44.34 % | 47.00 % |

### The verdict: 8 m, and it costs something

**R1: both pass; 5 m is better by 5.4 points** (96.2 % vs 90.8 % of footprints wider than
one cell). **R2: 8 m wins decisively** — at the affordable sample count the 5 m grid
leaves **3× the artefact** (3.54 % vs 1.16 % blank) for **1.9× the GPU solve**. Matching
8 m's artefact level at 5 m needs ≈2.5e8 samples/tx, i.e. ~2.5× the cost on both backends.
**R3 prefers 5 m and is overruled by R2.**

A third measurement supports the same answer and is worth stating because it is about
evidence rather than cost: the terrain these two maps exist to compare comes from a
**30.6 × 29.8 m DTM posting**. At 8 m the map is already 3.8× finer than its own elevation
data. A 5 m terrain-shadow map claims spatial detail the source does not contain.

**What this costs, recorded rather than buried:** `coverage_pathgain_db.png` and
`coverage_pathgain_db_terrain.png` were 5 m maps and are now 8 m. That is a real,
deliberate reduction in published spatial resolution — 234 558 cells down to 91 745 — and
the paper's figure captions must stop saying 5 m.

**What it bought, which nobody had measured:** at its shipped 5 m / 1e7 defaults the
terrain plane map — *the figure the paper compares the ground-following map against* — was
itself **18.92 % unsampled**. Nobody had ever printed that number. At 8 m / 1e8 it is
**0.13 %**. `sionna_coverage.py` now prints its own no-coverage fraction on every run and
warns above 2 %.

**An unplanned benefit.** On one grid at one sample count the two maps' own 99th
percentiles now agree to **0.12 dB** (−82.41 vs −82.29), where they were **1.8 dB** apart
before. F9's shared-colour-scale compromise — first-writer-wins, with the second figure
saturating — has stopped costing anything measurable: saturation is 0.58 % and 0.56 %, and
neither map's p99 exceeds the shared `vmax`, so the "your p99 is above the shared scale"
note no longer fires.

---

## Everything that moved

All numbers from re-running `comparison/f8_plane_stack.py` (111.7 s, 1.10 GB peak RSS, 0
failures), `comparison/c3_ablation.py` (39.1 s, 0.92 GB, 0 failures) and
`bash benchmarks/run.sh` on `spark-5804`.

### C3 — the coverage-statistics table and the ablation verdict

| | before | after |
|---|---|---|
| flat: median / p10 / p90 dB | −113.98 / −125.04 / −93.03 | **−113.56 / −127.75 / −93.61** |
| flat: no-coverage | 9.22 % | **0.38 %** |
| terrain_plane: median / p10 / p90 dB | −115.74 / −126.83 / −93.22 | **−112.30 / −125.71 / −94.16** |
| terrain_plane: no-coverage | 6.99 % | **0.13 %** |
| terrain_ground: median / p10 / p90 dB | −117.51 / −127.32 / −92.93 | **−116.51 / −128.14 / −93.86** |
| terrain_ground: no-coverage | **10.99 %** | **1.16 %** |
| flat → terrain_plane best-server change | **21.91 %** | ⚠ **10.04 %** |
| flat → terrain_ground best-server change | 26.27 % | **21.93 %** |
| terrain_plane → terrain_ground best-server change | 23.59 % | **22.27 %** |
| … median Δ / rms Δ | −0.20 / 9.77 dB | **−0.22 / 7.98 dB** |
| … p10 Δ / p90 Δ | −16.21 / +5.62 dB | ⚠ **−12.56 / +3.14 dB** |
| … cells over 10 dB | **21.6 %** | ⚠ **16.3 %** |
| Monte-Carlo noise floor (terrain_ground) | 0.0103 | **0.00989** |
| change fraction ÷ noise floor | **22.9×** | **22.5×** |
| cost multiplier vs single plane | 347× | **60.4×** |
| terrain_ground wall (median of 3) | 6.59 s | **13.83 s** |

⚠ **Two of these moved against the argument.** More than half of the paper's terrain
ablation — "terrain changes the serving cell in 21.9 % of cells" — was Monte-Carlo noise
at 1e7 samples; the real figure is **10.0 %**. And about a quarter of "21.6 % of cells
differ by more than 10 dB" was noise; the real figure is **16.3 %**, with the
distribution tails narrowing to match. The serving-cell result for ground-following
survives (23.6 % → 22.3 %, still 22.5× the noise floor).

The `terrain_plane` median moving **+3.44 dB** is the largest single shift and deserves its
own sentence: an under-sampled Monte-Carlo radio map does not merely leave holes, it
*underestimates* received power in the cells it does sample, because it misses paths. Both
effects were present at 1e7 and both are corrected at 1e8.

### F8 — the receiver-plane study

Unchanged, because they are pure geometry on an unchanged grid:

| | value |
|---|---|
| cells with the receiver below ground, shipped rule | **28.968 %** (identical) |
| … after the ceiling fix | **0 %** (identical) |
| ridge shadow from independent DTM geometry | **0.753 %** (identical) |
| median / max height offset, before and after | 1.815 / 3.47 m and 0.453 / 0.991 m (identical) |

Moved:

| | before | after |
|---|---|---|
| terrain_plane no-coverage | 6.99 % | **0.13 %** |
| terrain_plane median dB | −115.74 | **−112.30** |
| K9 nearest (shipped) no-coverage | **28.12 %** | **18.76 %** |
| K57 ceiling (fixed) no-coverage | **10.99 %** | **1.16 %** |
| extra shadow, before-fix | 23.53 % | **18.70 %** |
| extra shadow, after-fix | 7.67 % | **1.12 %** |
| extra-shadow attribution, before-fix (ridge / building / underground / unexplained) | 0.3 / 2.7 / **85.1** / 11.9 % | 0.1 / 0.6 / **97.1** / **2.2 %** |
| extra-shadow attribution, after-fix | 5.4 / 13.6 / 0 / **81.0 %** | **26.4 / 22.2 / 0 / 51.5 %** |
| best-server change vs plane, after-fix | 0.23585 | **0.22270** |
| F8's own Monte-Carlo noise floor | 0.00333 | **0.00258** |
| … ratio (F8's floor, not C3's) | 71× | **86×** |
| solver time, K = 57 stack | 1.01 s | **7.25 s** |
| stage wall, K = 9 / K = 57 | 1.83 / 2.10 s | **2.84 / 9.05 s** |
| stage multiplier K57 ÷ K9 | ×1.15 | **×3.19** |
| stage peak RSS, K = 57 | 636.7 MB | **636.9 MB** |

The before-fix attribution moving from 85.1 % to **97.1 %** underground makes F8's case
*stronger*: with sample starvation mostly removed, essentially all of the shipped map's
spurious darkness is the receiver being below local ground.

### Benchmark matrix — `benchmarks/tables/`

See "Validation" below for the measured table. In outline: `sionna_terrain_ground` is the
stage that changes, from the cheapest cell in the matrix to the most expensive, on both
backends. `sionna_coverage` changes little on GPU (it went from one 5 m/1e7 solve to one
8 m/1e8 solve) and moderately on CPU.

---

## Every paper number these two changes invalidate

The parent owns `claims/**` and the paper. This is the list.

### Bound in `claims/claims.yaml` — must be edited

| claim id | paper text | new value | verdict |
|---|---|---|---|
| `ablation-ground-following-nocov` | **11.0** | **1.16** | **INVALIDATED.** Tolerance is 0.2 pp; this is off by 9.8 pp. Table "coverage statistics by scene variant" must change. |
| `best-server-change-over-noise` | **22.9** | **22.52** | **Survives, barely.** Inside the 0.5 tolerance with 0.12 to spare. Quoted in two places; both should be updated to 22.5 rather than left to drift. |

### Bound in `claims/claims.yaml` — verified unchanged, no edit needed

`ground-following-below-ground` (28.97), `ground-following-after-fix` (0),
`ridge-shadow-magnitude` (0.75), `sweep-medians`, `sweep-penalty`, `transect-endpoints`,
`transect-delay-spikes`, `link-metrics-checksum` (`08afea6d…` re-verified byte-identical
after the re-run), `building-count`, `terrain-relief`.

### Not in the register, but published in the paper and now wrong

1. **Coverage statistics by scene variant** — every median, p10 and p90 in that table:
   flat −113.98 → **−113.56**, terrain_plane −115.74 → **−112.30**, terrain_ground
   −117.51 → **−116.51**; and every no-coverage entry: 9.22 → **0.38 %**, 6.99 →
   **0.13 %**, 10.99 → **1.16 %**.
2. **"Terrain changes the serving cell in 21.9 % of cells"** → **10.04 %**. The single
   largest correction in this round. More than half of it was estimator noise.
3. **"21.6 % of cells differ by more than 10 dB"** → **16.25 %**.
4. **The p10/p90/rms spread of the ground-following minus plane delta** — −16.21/+5.62,
   rms 9.77 dB → **−12.56/+3.14, rms 7.98 dB**.
5. **flat vs terrain_ground best-server change** 26.27 % → **21.93 %**.
6. **Any figure caption saying the coverage maps are on 5 m cells** — they are 8 m.
7. **Any statement that the ground-following map's no-coverage is ~11 %** → 1.16 %.
8. **§Computational cost** — every wall-clock and peak-RSS figure for `sionna_coverage`
   (flat and terrain) and `sionna_terrain_ground`, on both backends. `sionna_analysis` and
   `sionna_mmwave_sinr` are untouched and their numbers stand.
9. **The C3 cost multiplier** 347× → **60.4×**, if quoted.
10. **The "71×" ratio**, if it survives anywhere: F8's own floor now gives 86×. The paper
    should keep using C3's conservative 22.5× in both places, as the register requires.

### Stale rather than wrong — measurements that must be re-run before they are quoted again

11. **`benchmarks/results/bgi-ran-01-x86_64*.json`** and the cross-architecture table in
    `docs/audits/2026-07-29-f8-f9-receiver-plane-and-colour-scale.md`. The H200 has not
    been re-run at the new defaults. Its timings and its F8 reproduction are pre-change.
12. **`benchmarks/RASPBERRY-PI-4.md`** — the 310 s full-pipeline figure and three of its
    five stage rows are pre-change, and this is the change most likely to hurt there
    (`sionna_terrain_ground` 14.2 s → an estimated 20–30 min).
13. **`benchmarks/results/spark-5804-aarch64.json`** (and `-fresh`, `-sionna201`) are
    pre-change. The new run is `spark-5804-aarch64-local.json`, written alongside them by
    design. **`benchmarks/tables/` now mixes pre-change and post-change runs in one
    table.** A reader comparing the spark row against the bgi-ran-01 row is comparing
    1e6/1e7-era numbers against 1e8-era numbers and will read a settings change as a
    hardware difference. This is the most dangerous artefact of this round and the parent
    must either re-run the other hosts or label the table.

---

## Validation performed

```bash
export ULAP_WORK_DIR=/home/$USER/.claude/jobs/d53ee842/tmp/rtwork MPLBACKEND=Agg
RT=/home/$USER/.claude/jobs/d53ee842/tmp/venv-rt/bin/python

# defaults + every override path, live
$RT ulap-scope/ulap_scope/stages/sionna_coverage.py terrain
$RT ulap-scope/ulap_scope/stages/sionna_terrain_ground.py
ULAP_GF_SAMPLES_PER_TX=1e6 ULAP_RM_CELL_M=16 ULAP_GF_PLANES=5 $RT …terrain_ground.py
ULAP_RM_SAMPLES_PER_TX=1e6 …                     # shared var honoured
ULAP_RM_SAMPLES_PER_TX=1e6 ULAP_GF_SAMPLES_PER_TX=1e7 …   # stage-specific wins

# downstream
$RT comparison/f8_plane_stack.py      # 111.7 s, 1.10 GB peak RSS, 0 failures
$RT comparison/c3_ablation.py         #  39.1 s, 0.92 GB peak RSS, 0 failures
PYTHON=$RT bash benchmarks/run.sh     # full matrix, 3 repeats x 2 backends, + tables

# tests
cd ulap-scope && $RT -m pytest -q     # 48 passed
cd ulap-scope && $RT -m pytest -q -m rt  # 3 passed
```

Both `blender/` copies were re-synced and re-verified as byte-identical to the packaged
stages apart from their 8-line "duplicate copy" banner.

> **Superseded 2026-07-30:** the `blender/` duplicates have since been replaced by
> 27-line `runpy` shims delegating to the packaged canon, with a guard test
> (`test_no_duplicate_stages.py`) that fails on any future hand-copy. The drift class this
> paragraph describes no longer exists to re-sync.

---

## Where this work is wrong, or is still limited

* **The chosen default is not converged and is not claimed to be.** 1e8 leaves 1.16 % of
  the ground-following map blank against 0.24 % genuine. It was chosen on cost. The stage
  prints that gap on every run — deliberately as an unconditional note rather than a
  threshold warning, because a threshold warning goes silent exactly when the default is
  raised and the residual becomes easy to mistake for physics.
* **S2 could not be tested at 1e9.** Demonstrating convergence there needs a 1e10 run —
  ~11 minutes of GPU solve and an estimated 7 hours of CPU. So the value that passes the
  fitness test cannot itself be shown to be on the asymptote. The 1e9 column should be
  read as "much better", not as "converged".
* **8 m was chosen partly on cost, and 5 m is defensible at 2.5× the price.** If the
  parent would rather keep 5 m in the paper, the honest way is `ULAP_RM_CELL_M=5`
  *together with* `ULAP_RM_SAMPLES_PER_TX=2.5e8`, and re-running everything again. Setting
  the cell size alone would publish a finer grid with 3× the holes.
* **Only `spark-5804` was re-run.** Items 11–13 above.
* **The 51.5 % "unexplained by geometry" residual at 1e8 is not explained.** It shrinks to
  4.6 % at 1e9, so most of it is estimator; whether all of it is has not been shown.
* **The CPU stack figures (262 s, 2383 s) are `K × measured single-solve`, not a timed
  57-solve stack.** The end-to-end CPU stage wall clock in `benchmarks/tables/` is the
  measured one and is the number to quote.
</content>
