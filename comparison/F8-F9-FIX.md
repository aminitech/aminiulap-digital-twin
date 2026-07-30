# F8 / F9 — the ground-following receiver, and the two figures the paper compares

Two defects found by re-running the shipped RF stages, fixed, and **measured** rather than
asserted. Everything below is produced by `comparison/f8_plane_stack.py`; the raw record is
`comparison/results/f8.json` and the figures are `comparison/figures/f8_plane_stack.png` and
`comparison/figures/f8_ridge_shadow.png`.

Measured on `spark-5804` (NVIDIA GB10, aarch64), Sionna RT 2.0.1, Mitsuba variant
`cuda_ad_mono_polarized`, Newton (Barbados) government scene, 576 building footprints,
2 towers, 3.5 GHz, 8 m cells, `max_depth=5`, seed 42.

> **Re-run 2026-07-30 at `samples_per_tx = 1e8`.** Every number below was regenerated
> after the sampling default was raised 1e6 → 1e8 and `sionna_coverage.py` was moved
> 5 m → 8 m cells, so this study and the two shipped stages are now on the same settings.
> The two decisions, their criteria, their costs and the full before/after are in
> [`docs/audits/2026-07-30-sampling-and-resolution.md`](../docs/audits/2026-07-30-sampling-and-resolution.md).
> The F8 headline (28.97 % underground → 0 %) and the 0.75 % DTM ridge-shadow area are
> unchanged — both are pure geometry on an unchanged grid. Several of the *derived*
> numbers moved, and two moved **against** the argument this document makes; they are
> marked ⚠ below.

---

## F8 — the receiver was underground in 28.9 % of cells

### What was wrong

`sionna_terrain_ground.py` built `K = 9` horizontal planes spanning the terrain range and, per
map cell, took the plane **nearest** to `terrain + 1.5 m`.

Over 55.52 m of relief, 9 planes is 6.94 m spacing. Two consequences:

1. The receiver is nowhere near 1.5 m above ground — median offset **1.81 m**, worst case
   **3.47 m**.
2. "Nearest" rounds *down* as often as *up*, so in **28.97 % of cells the chosen plane sat
   below local ground** (10.44 % of cells more than 1 m below). Those cells are occluded by
   the terrain itself, read zero path gain, and were plotted identically to genuine radio
   shadow. The banding visible in the shipped figure runs along terrain contours — it is the
   plane stack, not propagation (top-right panel of `f8_plane_stack.png`).

### What changed

**1. Selection rule: nearest → ceiling.** Each cell now takes the *lowest plane at or above*
`terrain + 1.5 m`. The height error becomes one-sided, in `[0, spacing)`, and the receiver can
never be underground. A residual guard flags (as NaN, not as coverage) any cell whose selected
plane is still below local ground; measured count on Newton is **0**.

**2. `K` is derived from a stated tolerance, not hard-coded.**

```
MAX_HEIGHT_ERR_M = 1.0                                   # env: ULAP_GF_MAX_HEIGHT_ERR_M
K = ceil(relief / MAX_HEIGHT_ERR_M) + 1                  # env override: ULAP_GF_PLANES
```

For Newton that gives `K = 57`, spacing 0.991 m. **1.0 m is argued, not tuned:**

- it keeps every cell inside a **1.5–2.5 m AGL** band, i.e. still a human-height receiver;
- it is at or below the terrain relief already present *inside one 8 m radio-map cell*
  (0.19 m median / 0.42 m p90 / 2.2 m max on this DTM, whose posting is 30.6 × 29.8 m).
  Below ~0.5 m a finer stack resolves the DTM's own bilinear interpolant, not the radio.

`K` was fixed by this criterion **before** the coverage numbers were read, and is reported
whatever it produced. The tolerance sweep is exposed (`ULAP_GF_MAX_HEIGHT_ERR_M=0.5` → K=113,
max error 0.496 m) so the choice can be re-argued without editing code.

### F8 numbers, before and after

`K=9` planes are an exact subset of the `K=57` stack (56 = 8 × 7), so before and after are read
off the **same Monte-Carlo solves** — none of the difference is re-solve noise. Two intermediate
rows separate the rule change from the `K` change.

| | K=9 nearest **(shipped)** | K=9 ceiling | K=57 nearest | K=57 ceiling **(fixed)** |
|---|---|---|---|---|
| plane spacing | 6.94 m | 6.94 m | 0.991 m | 0.991 m |
| cells with receiver **below ground** | **28.97 %** | 0.00 % | 0.00 % | **0.00 %** |
| … more than 1 m below | **10.44 %** | 0.00 % | 0.00 % | **0.00 %** |
| median \|chosen − target\| | **1.81 m** | 3.21 m | 0.25 m | **0.45 m** |
| max \|chosen − target\| | **3.47 m** | 6.94 m | 0.50 m | **0.99 m** |
| cells within 1 m of target | 24.5 % | 12.0 % | 100 % | **100 %** |
| map no-coverage fraction | **18.76 %** | 0.40 % | 1.32 % | **1.16 %** |
| median path gain | −115.41 dB | — | — | −116.51 dB |

Two honest notes on that table:

- The shipped 18.76 % no-coverage reproduces `comparison/results/c3.json` exactly, which is
  the cross-check that this harness measures the same thing C3 did. (Both were 28.12 % when
  both ran at `samples_per_tx = 1e7`; both moved together when the default was raised, which
  is the property the cross-check exists to protect.)
- **The fix does not simply lower the no-coverage number to the 0.82 % you get by excluding
  underground cells.** It lands at 1.16 %, *higher*. That is expected and is not a regression:
  the ceiling rule with 57 planes puts the receiver where it was always supposed to be — a
  median 0.45 m above target instead of 3.21 m (K=9 ceiling) — and a receiver at 1.5 m AGL is
  genuinely more obstructed than one 3–7 m up. The 0.82 % figure is what you get by *deleting*
  the bad cells; 1.16 % is what you get by *measuring them properly*.
- **Raising the sample count made the F8 case stronger, not weaker.** At 1e7 the shipped
  variant's extra shadow was 85.07 % underground artefact and 11.94 % unexplained; at 1e8 it
  is **97.07 % underground artefact and 2.17 % unexplained**. With sample starvation mostly
  removed, essentially *all* of the shipped map's spurious darkness is the receiver being
  below ground. That is the cleanest statement of F8 this study has produced.

### Cost of the new K

Cost is linear in `K` (K solves, a `[K, H, W]` float32 stack). Measured end-to-end on the
shipped stage via `/usr/bin/time`, same host, same work dir:

| | K = 9 | K = 57 (new default) |
|---|---|---|
| stage wall clock | 2.84 s | **9.05 s** (×3.19) |
| stage peak RSS | 564.6 MB | **636.9 MB** (+72 MB) |
| solver time alone (57 vs 9 planes, `samples_per_tx=1e8`) | 1.15 s | 7.25 s (×6.3) |
| stack memory (311 × 295 grid) | 3.3 MB | 20.9 MB |

The ×6.3 solve cost is exactly linear in K, as designed. It used to be nearly invisible
end-to-end (×1.17 at the old 1e6 sample default) because the stage was dominated by
interpreter start-up, scene load and figure rendering. At the 1e8 default the solve is now
the dominant term and the end-to-end multiplier is **×3.19**.

**The CPU caveat is no longer a caveat — it was measured.** On `llvm_ad_mono_polarized`
(same host, 20 cores, `CUDA_VISIBLE_DEVICES=""`) a single 8 m solve costs 0.265 s at 1e6,
4.60 s at 1e8 and 41.8 s at 1e9, essentially independent of cell size. The 57-plane stack
therefore costs ≈ 262 s on CPU at the new default, against 7.25 s on the GPU — a 36×
backend gap that the GPU-only numbers above hide. This measurement is what decided the
sampling default; see the audit.

---

## F9 — the two figures the paper compares used independent colour scales

### What was wrong

`sionna_coverage.py` computed `vmax = p99(own data); vmin = vmax − 80`, and
`sionna_terrain_ground.py` did the same on **its own** data. The paper prints
`coverage_pathgain_db_terrain.png` and `coverage_pathgain_db_terrain_groundfollow.png` adjacent
with a caption inviting comparison, so identical hue meant **different dB**. Measured gap on
this scene: p99 = −81.44 dB vs −79.63 dB, i.e. the two maps were on scales offset by 1.8 dB
before any rounding.

### What changed

Both stages now call `resolve_pathgain_scale(pg_db, group, figure)`:

- Figures are tagged with a **group**. The terrain plane map and the ground-following map are
  both in group `"terrain"`; the flat map is its own group.
- The **first figure in a group sets the scale**: `vmax = ceil(p99 / 5 dB) * 5 dB`,
  `vmin = vmax − 80`. The **80 dB dynamic-range convention is unchanged**; only the anchor is
  shared and quantised.
- Every later figure in the group **adopts that scale unchanged**, so one pipeline pass yields
  comparable figures with no re-render. Where a later map's own p99 is above the shared `vmax`,
  the top saturates — the saturated fraction is measured, printed to stdout, written into
  `sionna_out/pathgain_scale.json`, and appended to the colorbar label when it exceeds 0.5 %.
- **The figure says what scale it is on.** Both the title and the colorbar label carry
  `shared scale −160 to −80 dB (80 dB range, group 'terrain')`, and the terrain titles name the
  sibling figure they are comparable with.
- **Overrides:** `ULAP_PG_VMAX` / `ULAP_PG_VMIN` (dB) bypass the shared scale entirely.
  Deleting `sionna_out/pathgain_scale.json` rescales a group from scratch.

### F9 verification (live run, fresh scale file, 2026-07-30 settings)

```
coverage terrain  : vmin=-160.0 vmax=-80.0 dB (set by this figure; own p99 -82.4;  0.58 % saturated)
ground-following  : vmin=-160.0 vmax=-80.0 dB (set by coverage_pathgain_db_terrain.png;
                                               own p99 -82.3; 0.56 % saturated)
```

Both figures on one scale after a single pass. The override path was exercised too
(`ULAP_PG_VMAX=-70 ULAP_PG_VMIN=-170` → `vmin=-170.0 vmax=-70.0`).

**An unplanned benefit of harmonising the grid and the sample count (F11/F10).** The two
maps' own p99 values used to be 1.8 dB apart (−81.4 vs −79.6), which is why the
first-writer-wins rule cost the second figure 1.10 % saturation and printed a "your p99 is
above the shared vmax" note on every run. On one grid at one sample count they now agree to
**0.12 dB** (−82.41 vs −82.29), neither exceeds the shared `vmax`, and the note no longer
fires. F9's compromise between comparability and headroom has largely stopped costing
anything.

---

## The question the abstract depends on

> Does ground-following still reveal genuine ridge shadowing that the horizontal receiver plane
> misses, once the discretisation artefact is removed?

**Yes — but it is roughly 0.2 % of the map, not the ~28 % the shipped figure implied.**

Chasing this exposed a **third** problem, which turned out to dominate the answer.

### The residual "extra shadow" is mostly not shadow at all

Attribution of the cells that are dark in the ground-following map but lit on the horizontal
plane, using an **independent** geometric ray march over the DTM and the building footprints —
computed from the terrain and footprint data, never from the ray tracer:

| | shipped (K=9 nearest) | fixed (K=57 ceiling) |
|---|---|---|
| extra shadow, fraction of map | 18.70 % | 1.12 % |
| … underground discretisation artefact | **97.07 %** | 0.00 % |
| … ridge shadow (terrain blocks at 1.5 m AGL, clear on the plane) | 0.12 % | 26.36 % |
| … building shadow | 0.64 % | 22.19 % |
| … **unexplained by geometry** | 2.17 % | **51.45 %** |

*(Those are the 2026-07-30 numbers at `samples_per_tx = 1e8`. At the 1e7 the study
originally used they were 23.53 % / 85.07 % / 0.26 % / 2.72 % / 11.94 % and
7.67 % / 0.00 % / 5.41 % / 13.64 % / 80.95 %. Raising the sample count moved the fixed
column's unexplained share from 81 % to 51 % — the paragraph below is the reason, and it
is now half-solved rather than fully open.)*

51 % unexplained is not a result, it is a symptom. `RadioMapSolver` is a Monte-Carlo estimator:
a cell that collects no ray hits reads zero path gain and is plotted identically to a cell that
is genuinely dark. A receiver 1.5 m above ground sees the towers at a far more grazing angle
than one on a plane a median 22.6 m up, so it starves first. Sweeping `samples_per_tx` with
everything else held fixed:

| `samples_per_tx` | horizontal plane no-coverage | ground-following no-coverage | extra shadow | ridge / building / unexplained | GPU solve (58 solves) |
|---|---|---|---|---|---|
| 1e6 *(the superseded default)* | 44.34 % | **47.00 %** | 15.84 % | 1 % / 14 % / **85 %** | 0.37 s |
| 1e7 | 6.99 % | 10.99 % | 7.67 % | 5 % / 14 % / **81 %** | 0.99 s |
| **1e8** *(the shipped default since 2026-07-30)* | 0.13 % | **1.16 %** | 1.12 % | 26 % / 22 % / 51 % | 7.11 s |
| 1e9 | **0.00 %** | **0.24 %** | **0.24 %** | **81 % / 14 % / 5 %** | 69.26 s |

The no-coverage fraction falls about 10× per decade of samples and shows no floor until 1e8–1e9.
**At the 1e6 the stage used to ship with, 47 % of the ground-following map was unsampled, not
shadowed. At the 1e8 it ships with now, 1.16 % is — and against a converged dark fraction of
0.24 %, roughly four fifths of even that is still the estimator, not the terrain.** The
default is a cost bound, not convergence: 1e9 costs 40 minutes per run on the CPU/LLVM
backend. Run `ULAP_GF_SAMPLES_PER_TX=1e9` before making any claim about shadow *area*.

At convergence (1e9), the picture is clean and the answer is unambiguous:

- The horizontal plane has **zero** dark cells.
- The ground-following map has **0.24 %** dark cells, all of them "extra shadow".
- **81.2 % of those are corroborated as genuine ridge shadow** by the independent DTM
  ray march — terrain blocks the line to *both* towers at 1.5 m AGL but not on the horizontal
  plane. 14.2 % is building shadow; 4.6 % remains unexplained.
- So genuine, ray-traced, terrain-caused shadow that the horizontal plane cannot represent is
  **≈ 0.19 % of the map** (~178 of 91 745 cells).
- Independently, pure DTM geometry says **0.75 %** of the map is terrain-blocked from both
  towers at 1.5 m AGL. The ray tracer finds usable coverage in about three quarters of that
  area via diffraction and reflection — which is itself a point in the ray tracer's favour, and
  a reason the effect is smaller than geometry alone predicts.

### What the paper may now claim about ridge shadowing

**It may claim that ground-following resolves genuine ridge shadowing that a horizontal
receiver plane cannot represent — and it must state that this affects ≈ 0.2 % of the map
(0.75 % by terrain geometry alone), not the ~28 % of dark cells the published figure shows.
It may not point at the dark area of `coverage_pathgain_db_terrain_groundfollow.png` as
evidence: 85 % of that area was the receiver being underground and essentially all of the
remainder is Monte-Carlo sample starvation at the shipped sample count.**

If the paper wants a *quantitative* argument for the plane stack, shadow is the wrong metric.
The stronger, artefact-free numbers are the level and server-selection differences, which are
well clear of the Monte-Carlo noise floor (0.0033 best-server change for a same-configuration
re-solve at a different seed):

| ground-following (fixed) vs horizontal plane | 1e7 (superseded) | **1e8 (shipped)** |
|---|---|---|
| median Δ path gain | −0.20 dB | **−0.22 dB** |
| p10 / p90 Δ | −16.21 / +5.62 dB | ⚠ **−12.56 / +3.14 dB** |
| rms Δ | 9.77 dB | ⚠ **7.98 dB** |
| cells differing by > 10 dB | 21.6 % | ⚠ **16.3 %** |
| best-server change fraction | 0.236 (71× the 0.0033 floor) | **0.223** (86× the 0.0026 floor) |

⚠ **These moved against the argument, and that is the point of re-running.** About a
quarter of the old "21.6 % of cells differ by more than 10 dB" was Monte-Carlo noise at
1e7 samples, not a terrain effect: at 1e8 it is 16.3 %, and the distribution tails
narrow correspondingly (p10 −16.2 → −12.6 dB, rms 9.8 → 8.0 dB). The serving-cell
result survives essentially intact (0.236 → 0.223) and its margin over the noise floor
*improves* (71× → 86×) because more samples quiet the floor faster than they quiet the
signal — which is what a real effect looks like.

**Which noise floor.** 86× uses *this* study's floor (0.00258, a single re-solve of the
horizontal plane at a second seed). C3 establishes the floor differently — three seeds on
the ground-following variant itself, 0.00989 — and gives **22.5×**. C3's is the
conservative one, it is the one the paper quotes in both places it appears, and it is
bound in `claims/claims.yaml` (`best-server-change-over-noise`) so the two cannot drift
apart again. Both floors fell with the sample count (0.0033 → 0.0026 and 0.0103 → 0.0099).

The plane stack earns its complexity on **16.3 % of cells differing by more than 10 dB and
22.3 % of cells changing serving tower**, not on shadow area.

---

## Where this work was wrong, or is still limited

- **My first attempt at F9 was wrong.** I made the shared scale "only ever widen", which is
  more information-preserving but means the pipeline's own stage order leaves the two figures
  on different scales until a second pass — exactly the defect F9 is about. It was replaced
  with first-writer-wins plus a measured, printed saturation fraction. The failed design and
  its live output are recorded here rather than quietly dropped.
- ~~**The `samples_per_tx` default was left at 1e6.**~~ **Decided 2026-07-30: raised to 1e8**
  and every number in this document re-run at it. The whole benchmark matrix was re-run too.
  1e8 is a *cost bound*, not convergence — 1.16 % blank against 0.24 % genuine — and the
  stage now prints that gap on every run rather than hiding behind a threshold that stops
  firing once the default is raised. `ULAP_GF_SAMPLES_PER_TX` still overrides.
- ~~**The two figures the paper compares are still on different grids.**~~ **Decided
  2026-07-30: both are 8 m**, read from one shared `ULAP_RM_CELL_M`. `sionna_coverage.py`
  moved 5 m → 8 m, which is a genuine loss of published spatial resolution and is recorded
  as such; the reason it went that way rather than 5 m is that at the affordable sample
  count the 5 m grid leaves 3.54 % of cells unsampled against 8 m's 1.16 %.
- ~~**CPU (Mitsuba LLVM) cost of K = 57 was not measured.**~~ **Measured 2026-07-30**:
  0.265 s / 4.60 s / 41.8 s per 8 m solve at 1e6 / 1e8 / 1e9, ≈36× the GPU. It is the
  number that set the sampling default. Full end-to-end CPU and CUDA wall clock for the
  new defaults is in `benchmarks/tables/results.md`.
- **The DTM line-of-sight test ignores diffraction and is a straight-line march at 192 samples
  per link.** It is deliberately crude: its job is to be *independent* of the ray tracer, not
  to be a second propagation model. Where it and the ray tracer disagree, the ray tracer is the
  better physics; the LoS mask is only used to label *why* a cell is dark.

## Reproduce

```bash
export ULAP_WORK_DIR=/path/to/rtwork MPLBACKEND=Agg
/path/to/venv-rt/bin/python comparison/f8_plane_stack.py     # ~2 min, writes results/f8.json
# F9 end-to-end:
rm -f "$ULAP_WORK_DIR/sionna_out/pathgain_scale.json"
/path/to/venv-rt/bin/python ulap-scope/ulap_scope/stages/sionna_coverage.py terrain
/path/to/venv-rt/bin/python ulap-scope/ulap_scope/stages/sionna_terrain_ground.py
cat "$ULAP_WORK_DIR/sionna_out/pathgain_scale.json"
```
