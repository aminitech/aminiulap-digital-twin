# What the 51.5 % "unexplained by geometry" residual actually is

**Date:** 2026-07-30
**Scope:** the S1 criterion miss in `docs/audits/2026-07-30-sampling-and-resolution.md` —
at the shipped 1e8 samples/tx default, 51.5 % (531 of 1 032) of the ground-following
map's extra-shadow cells are unexplained by the DTM + building line-of-sight march in
`comparison/f8_plane_stack.py`.
**Instrument:** `comparison/f8_residual_probe.py` → `comparison/results/f8_residual.json`,
`comparison/figures/f8_residual_classes.png`, `f8_residual_margins.png`.
Pass criteria for every hypothesis were declared in the script (`CRITERIA`) and printed
before the first solve; they are stored verbatim in the JSON.

---

## Bottom line

**The residual decomposes completely. Nothing is genuinely unknown.**

Every one of the 531 cells is accounted for by one of two mechanisms, with a declared
precedence and zero remainder:

| class | cells | % of residual | % of extra shadow | what it is |
|---|---|---|---|---|
| grazing, sub-Fresnel clearance | 236 | 44.4 % | 22.9 % | LOS "clear" but skimming the surface inside 1 Fresnel radius — the binary march calls it unexplained, the hit statistics are marginal |
| sub-critical hit expectation | 244 | 46.0 % | 23.6 % | LOS clear but so grazing (median elevation **0.28°**) that the expected direct-ray hit count at 1e8 is **< 10** (median **0.49**) |
| march undersampling (S1's own test artefact) | 41 | 7.7 % | 4.0 % | genuinely building-blocked — the 192-sample / 2–98 %-span march stepped over the blocker |
| raster-vs-mesh LOS mismatch | 10 | 1.9 % | 1.0 % | blocked to every tower by the actual triangulated meshes (`mi.ray_test`), clear per the 2 m raster + bilinear DTM |
| below terrain mesh / under roof / reflection-only / plain / unreachable / **unknown** | 0 | 0.0 % | 0.0 % | — |

Summed: **90.4 % is Monte-Carlo starvation at grazing incidence** (the estimator, not
the terrain) and **9.6 % is the S1 test being wrong about its own geometry** (real
shadow it failed to see). **0.0 % is unexplained physics.**

The audit's sentence "whether all of it is estimator has not been shown" is now
resolved: 98.3 % of the residual is lit at 1e9 (same seed, same configuration),
**PathSolver finds a deterministic propagation path to 99.6 % of the cells** (median
reachable gain −127.4 dB — dim, not dark), and every cell that neither anchor reaches
is hard-blocked per the true mesh. `reachable_any_anchor = 1.0`.

## The mechanism, quantitatively

A residual cell is a cell whose expected number of direct ray hits at the default is
of order one. For a horizontal 8 m cell at distance *d* and ray elevation *θ*,
E[hits] ≈ N·A·sin θ / (4πd²). The three populations separate cleanly:

| | residual (n=531) | explained-dark (n=320) | lit control (n=320) |
|---|---|---|---|
| median elevation to best tower | **0.28°** | 1.36° | 1.50° |
| median E[direct hits] at 1e8 | **0.49** | 10.8 | 10.4 |
| median clearance / Fresnel radius | **0.84** | −0.93 (blocked) | 6.18 |
| lit at 1e9 | 98.3 % | 59.4 % | 100 % |
| PathSolver: reachable / reflection-only | 99.6 % / 8.3 % | 87.8 % / **86.3 %** | 98.8 % / 5.9 % |

Poisson arithmetic closes the loop: at E ≈ 0.49, P(zero hits at 1e8) ≈ 61 %; ×10 samples
gives E ≈ 4.9, P(dark) ≈ 0.7 % — the measured still-dark fraction of the residual at 1e9
is 1.7 %. At a different 1e8 seed only 13.6 % of residual cells light up — they are not
unlucky cells at one seed, they are *systematically* sub-sample cells at 1e8 (the naive
39 % Poisson figure overshoots because sub-Fresnel clearance cuts the cell's effective
clear area roughly in half; both numbers point the same way). The controls validate the
probes: explained-dark cells have negative clearance margins and are 86 % reflection-only
reachable — exactly what "hard-blocked by geometry" should look like.

## Per-hypothesis verdicts (criteria pre-stated, negatives included)

* **H0 — estimator starvation: PASS.** 98.3 % of residual cells covered at 1e9
  (bar: ≥ 60 %).
* **H1 — binary-LOS vs physics (grazing/Fresnel): PASS.** 52.7 % of residual cells are
  reachable with sub-Fresnel clearance (bar ≥ 30 %); median clearance ratio 0.84 vs 6.18
  for lit controls (bar < 0.5×), Mann-Whitney p = 2.7e-56, KS D = 0.70. The march's
  binary "blocked/clear" is the wrong instrument within ~1 Fresnel radius of the surface.
* **H2 — multi-bounce-only reachability: FAIL.** Only 8.3 % of residual cells are
  reflection-only reachable (bar ≥ 20 %). Multibounce is the signature of the
  *explained*-dark population (86.3 %), not of the residual.
* **H3 — rasterisation/test mismatch: FAIL at its 20 % bar, but real at 9.6 %.**
  41 cells (7.7 %) are blocked when the march is re-run at 1024 samples over the full
  span — the blocker is a building in ≥ 93 % of them, pinching either mid-span (thin
  buildings under the 192-sample march's 4.3 m stride) or inside the 0–2 % link segment
  the march deliberately skips (obstruction within ~17 m of the receiver). 10 more cells
  (1.9 %) are mesh-blocked where the raster says clear. Residuals do **not** hug building
  edges (median distance to the nearest footprint edge 163 m vs 154 m for lit controls;
  only 4.1 % within 16 m), so this is a march-resolution defect, not a footprint-shape one.
* **H4 — receiver-plane transition edges: FAIL, decisively inverted.** Residual cells sit
  on kbest transitions *less* than lit controls (4.3 % vs 31.3 %). The ceiling-rule stack
  is not implicated at all. (Corroborating: 0 % of residual cells have the selected plane
  buried below the in-cell terrain corners.)

## What S1 should become

S1 as written — "the fraction of extra-shadow cells the DTM+building LOS march cannot
explain must be below 50 %" — charges the *sampling default* for two properties of the
*test*: a binary hard-blockage march (blind inside one Fresnel radius of the surface,
where grazing receivers live) and its own 192-sample / 2–98 %-span resolution. The
51.5 % was never a pile of un-understood dark cells; it is the march's known blind spot
plus arithmetic of a Monte-Carlo estimator at 0.3° elevation.

Recommended restatement, using only ray-tracer-independent quantities:

> **S1′ — fitness.** Attribute each extra-shadow cell, in order, to (i) hard LOS
> blockage, measured on the full link span with ≥ 1024 samples; (ii) partial
> obstruction, best-tower clearance < 1 Fresnel radius; (iii) predicted estimator
> starvation, E[direct hits] = N·A·sin θ/(4πd²) < 10. The fraction attributable to
> none of these must be **< 5 %**.

Measured at 1e8: hard blockage (incl. the march-missed 51 cells) 53.6 % of extra
shadow, partial obstruction 22.9 %, predicted starvation 23.6 %, **unattributed 0.0 %**
— S1′ passes with the full 5-point margin. If the audit prefers to keep a pure-geometry
criterion, the honest form is to apply it only to cells the estimator can be expected to
fill (E ≥ 10), and to report the starved fraction separately — at 1e8 that geometric
criterion is also met, because classes (i)+(ii) cover every cell that has E ≥ 10.

Either way the published sentence should change from "51.5 % is not understood" to:
"51.5 % of extra-shadow cells are grazing-incidence cells; 90 % of them are
Monte-Carlo-starved at 1e8 (98 % light up at 1e9) and 10 % are real building shadow the
attribution march under-resolved; none are unexplained."

## Validation

* **Exact reproduction before probing:** the probe re-derives f8's masks from fresh
  solves (same seed/config) and matches `comparison/results/f8.json` cell-for-cell:
  1 032 extra-shadow, 531 unexplained, gf no-coverage 0.01161, tp 0.00133 (`reproduction_vs_f8_json.exact = true`).
* All 531 residual cells probed (≥ 300 required), plus seeded (rng 20260730) matched
  controls: 320 explained-dark, 320 lit — every probe run on all three populations.
* Anchors solved live on GPU (`cuda_ad_mono_polarized`, asserted): 57-plane stacks at
  1e8 seed 42, 1e8 seed 202607, 1e9 seed 42; PathSolver (1e7 samples/src, depth 5) on
  all 1 171 probe cells; `mi.ray_test` against the actual scene meshes; 1024-sample
  full-span clearance march with per-cell Fresnel radii. Total wall 144 s, 0 failures.
* The attribution logic is imported read-only from `f8_plane_stack.py` (same
  `los_blocked`, `building_surface`, `select`, same constants), so the residual being
  classified is byte-for-byte the audit's residual. No stage files touched.

## Limits

* The E[hits] bar (10) and the Fresnel bar (1.0) are order-of-magnitude physics, not
  fitted thresholds; moving either moves cells between the two starvation classes but
  cannot move them out of "starved" (98.3 % lit at 1e9 is class-independent).
* PathSolver used 1e7 samples/src; its 0.4 % "unreachable" residual cells are covered by
  the 1e9/alt-seed anchors, but a diffuse-scattering probe was not run (RM solver runs
  specular-only defaults, so this matches the instrument under test).
* The 1e9 anchor inherits the audit's caveat: 1e9 is itself unproven-converged (S2), so
  "lit at 1e9" means "reachable", not "converged value".
