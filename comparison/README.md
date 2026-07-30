# Comparison studies C1 and C3

Two of the three studies pre-registered in [`benchmarks/METHOD.md`](../benchmarks/METHOD.md).
The metrics were fixed there **before** any number was produced, and are not renegotiated
below. Every configuration declared was run, and every one is reported.

| | Question | Script | Result | Figure |
|---|---|---|---|---|
| **C1** | How closely does the shipped analytical model track deterministic ray tracing? | [`c1_rt_vs_analytical.py`](c1_rt_vs_analytical.py) | [`results/c1.json`](results/c1.json) | [`figures/c1_rt_vs_analytical.png`](figures/c1_rt_vs_analytical.png) |
| **C3** | What does terrain and ground-following actually change, numerically? | [`c3_ablation.py`](c3_ablation.py) | [`results/c3.json`](results/c3.json) | [`figures/c3_ablation.png`](figures/c3_ablation.png) |

**C2** (deterministic RT vs stochastic TR 38.901) is covered in [`C2.md`](C2.md), with
results in [`results/c2.json`](results/c2.json) and figures `figures/c2_*.png`.

## How to reproduce

```sh
export ULAP_WORK_DIR=/path/to/rtwork      # holds scene_build/, mitsuba_scene/, mitsuba_scene_terrain/
export MPLBACKEND=Agg
python comparison/c1_rt_vs_analytical.py
python comparison/c3_ablation.py
```

Both scripts need Sionna RT 2.0.1 + Mitsuba 3.8.0 + Dr.Jit 1.3.1. The runs recorded here
were made on `spark-5804` (NVIDIA GB10, aarch64), Mitsuba variant
`cuda_ad_mono_polarized` — recorded, not assumed, per METHOD rule 2. **These are GPU
runs.** The paper's CPU-sovereignty claim is the `benchmarks/` harness's job, not this
directory's.

Both studies use the **Newton, Barbados government scene** (576 footprints, 55.5 m of
relief) — the geometry the ray tracer was actually run on. The bundled open-data
`examples/` scene (585 OSM buildings) is *not* used and the two are never mixed. If
`$ULAP_WORK_DIR` is missing, `c1` falls back to the open-data scene and stamps a
`LIMITATION` string plus a failure record into the JSON rather than producing a silently
cross-scene number.

---

## C1 — analytical model vs ray tracing

**Ground truth.** The ray-traced transect from `sionna_analysis.py`: a Sionna `PathSolver`
(max_depth 6, LoS + specular + diffuse + refraction) on 14 receivers at 1.5 m, spaced
100 m from 50 m to 1350 m along the radial from the *Rising Sun* tower toward the scene
origin, flat scene, 3.5 GHz. Read from `$ULAP_WORK_DIR/sionna_out/link_metrics.csv`
(md5 `08afea6d…`, byte-identical to the committed `blender/sionna_out/link_metrics.csv`).

**Challenger.** `examples/ulap_demo/propagation.py` — free space + two-ray + knife-edge —
run on the *same manifest the ray tracer used*, same tower, same bearing, same 14
distances, `use_terrain=False` to mirror the flat Mitsuba scene.

**One correction is applied and reported separately.** Sionna's path gain includes the
antenna patterns; the analytical model's does not. The RT run uses a `tr38901` element at
the TX and a short `dipole` at the RX, both at default orientation, and this transect
leaves the TX at **172° azimuth — squarely in the element's back lobe**, where `tr38901`
clamps 30 dB below its 8 dBi peak. That is a −20.2 dB units offset, not a physics
disagreement. Both conventions are reported; the antenna gains are obtained by calling
Sionna's own `v_tr38901_pattern` / `v_dipole_pattern`, so they cannot drift from what the
solver applied. The correction is exact for the LoS ray only.

### Results

Path-loss exponent fitted to the ray-traced transect: **n_rt = 1.732**.

| cell | RMS err | bias | de-biased RMS | max abs err | Pearson r | n_analytical | Δn |
|---|---|---|---|---|---|---|---|
| **average / antenna-corrected** *(primary — library default)* | **0.11 dB** | **−0.05 dB** | 0.10 dB | 0.36 dB | **0.99991** | 1.739 | **+0.007** |
| none / antenna-corrected | 1.85 dB | −1.69 dB | 0.76 dB | 2.53 dB | 0.99951 | 1.917 | +0.186 |
| coherent / antenna-corrected | 4.91 dB | −1.28 dB | 4.74 dB | 15.10 dB | 0.86614 | 2.042 | +0.311 |
| average / raw (isotropic) | 20.26 dB | +20.26 dB | 0.26 dB | 21.12 dB | 0.99968 | 1.780 | +0.049 |
| none / raw | 18.64 dB | +18.62 dB | 0.90 dB | 20.77 dB | 0.99978 | 1.959 | +0.227 |
| coherent / raw | 19.63 dB | +19.03 dB | 4.78 dB | 22.92 dB | 0.87055 | 2.084 | +0.352 |

**Cost.** RT solve 15.8 ms median (3 repeats, cold 36.6 ms) + 3.9 ms scene load. Analytical
0.74 ms warm, 66.4 ms cold (cold includes the one-off rasterisation of all 576 footprints).
Solve-for-solve the analytical model is **21× cheaper**; but *including* its rasterisation
it is **~3× more expensive than the entire RT solve** on this GPU. Both ratios are in the
JSON. A 14-receiver transect is the smallest RT workload in the pipeline and says nothing
about coverage-map cost.

**Reproduction check.** Re-solving the transect reproduced the committed CSV to within
0.005 dB path gain and 0.005 ns delay spread, with identical path counts.

### What this means, including the parts that are inconvenient

1. **The cheap model wins on this transect, and that is the headline.** With the antenna
   offset removed, the analytical model matches deterministic ray tracing to **0.11 dB RMS**
   at **all 14 of 14** points, with a path-loss exponent that differs by **0.007**. On this
   measurement, determinism buys reproducibility and auditability — not accuracy. Any claim
   that ray tracing is *needed* for median path gain along a clear radial is not supported
   by this number.

2. **But the agreement is partly definitional, and quoting the 0.11 dB without this is
   misleading.** Two facts from the run: the shipped stage computes RT path gain as an
   **incoherent sum of per-path powers** (`Σ|aᵢ|²`), not a coherent field sum; and the
   **median RT path count on this transect is 2** — a LoS ray plus one ground bounce. An
   incoherent 2-path sum over a flat ground plane *is* the phase-averaged two-ray model,
   which is exactly what `ground_reflection="average"` computes. The two methods are
   evaluating near-identical mathematics here. The result is real and reportable; it is
   evidence that **this transect is an easy case**, not that ray tracing is redundant.

3. **The knife-edge term contributed nothing.** The decomposition (`analytical_terms` in the
   JSON) shows `diffraction_db = 0.0` at **all 14 points** and `los = True` everywhere. The
   only term in the analytical model that knows the 576 buildings exist never fired. This is
   a free-space-plus-ground-reflection agreement, not a scene agreement. A transect chosen
   to cross buildings would test something this one does not.

4. **Which sub-model you pick matters more than the model class.** `coherent` — physically
   the more "correct" ground-reflection mode — is **45× worse** (4.91 dB vs 0.11 dB RMS,
   r 0.87 vs 0.9999, max error 15.1 dB), because it predicts interference fringes that the
   incoherent RT metric averages away. Turning ground reflection off entirely still gets
   within 1.85 dB.

5. **Delay-spread blindness — the failure mode METHOD requires C1 to expose.** The
   analytical model has **no delay domain at all**. It produces one scalar per point: no
   CIR, no taps, no delay spread. It is not inaccurate there; it returns nothing.
   The ray tracer reports a median RMS delay spread of 0.31 ns with three spikes where a
   third path appears:

   | distance | RT delay spread | RT paths | analytical |
   |---|---|---|---|
   | 450 m | **361.07 ns** | 3 | *no output* |
   | 550 m | 168.32 ns | 3 | *no output* |
   | 950 m | **196.86 ns** | 3 | *no output* |

   A 361 ns spread is ~108 m of excess path length and is the kind of number that sizes a
   cyclic prefix or an equaliser. A planner working from the analytical model would see a
   flat, benign radial and have no signal that these ranges exist. **This, not path-gain
   accuracy, is what the ray tracer buys on this transect.**

---

## C3 — flat vs terrain-plane vs ground-following

Three variants, each reproducing what a shipped stage does, all solved on **one common
grid** (identical centre, size and 8 m cells; the flat and terrain Mitsuba scenes were
verified to have identical x/y extent, so cells compare one-to-one). 3.5 GHz, `max_depth`
5, 10⁷ samples/TX, 2 in-scene towers, 295 × 311 cells. The shipped stages use 5 m (flat)
and 8 m (ground-following) cells; that is harmonised to 8 m here and the change is declared.

- **`flat`** — flat scene, TX z = h, plane at z = 1.5 m *(`sionna_coverage.py`)*
- **`terrain_plane`** — terrain scene, TX z = ground_z + h, **one** plane at zmax + 5 m
  *(`sionna_coverage.py terrain`)*
- **`terrain_ground`** — terrain scene, **K = 9** planes from 56.2 m to 111.8 m; each cell
  reads the plane nearest local terrain + 1.5 m *(`sionna_terrain_ground.py`)*

**A control arm was added.** "Fraction of cells whose best server changes" is meaningless
without knowing how much of it a re-run of the *same* configuration produces. Each variant
was run 3× with different solver seeds, and the same-variant/different-seed change fraction
is the noise floor any between-variant number must clear.

### Results

| variant | median | p10 | p90 | no-coverage | wall (median) | MC noise floor |
|---|---|---|---|---|---|---|
| `flat` | −113.98 dB | −125.04 | −93.03 | 9.2 % | 0.025 s | 0.85 % |
| `terrain_plane` | −115.73 dB | −126.83 | −93.22 | 7.0 % | 0.020 s | 0.33 % |
| `terrain_ground` | −117.42 dB | −127.66 | −92.90 | 28.1 % | 0.193 s (9 solves) | 0.86 % |

Repeat-to-repeat spread of the median is ≤ 0.05 dB for every variant.

| pair | best-server change | median Δ | p10 Δ | p90 Δ | RMS Δ | >10 dB |
|---|---|---|---|---|---|---|
| flat → terrain_plane | **21.9 %** | −0.37 dB | −8.73 | +10.25 | 8.62 dB | 16.5 % |
| flat → terrain_ground | **26.8 %** | −0.75 dB | −16.22 | +4.19 | 9.95 dB | 17.4 % |
| terrain_plane → terrain_ground | **23.4 %** | −0.38 dB | −17.59 | +5.20 | 10.81 dB | 25.3 % |
| terrain_plane → terrain_ground *(artifact removed, see below)* | 22.8 % | −0.06 dB | −15.63 | +5.60 | 9.57 dB | 20.6 % |

### What this means

1. **The pre-registered median is the metric most likely to mislead here.** All three
   variants sit within **3.4 dB** of each other on median path gain, and terrain_plane →
   terrain_ground moves the median by **−0.38 dB**. A coverage report that quotes only the
   median would conclude that terrain is nearly irrelevant. It is not: **25 % of cells
   differ by more than 10 dB**, and p10 moves by −17.6 dB. Raising or lowering the
   measurement plane moves cells in both directions, and the median cancels it. Report the
   tails.

2. **Ground-following earns its cost on best-server assignment.** 23.4 % of cells change
   best server between the single terrain plane and the nine-plane stack — **27× the
   0.86 % Monte-Carlo noise floor**, so it is a terrain effect, not solver noise, and it
   survives artifact removal (22.8 %). The cost is ~8–10× a single-plane solve. For a
   handover/neighbour-list product that is a real difference; for a median-coverage number
   it is not.

3. **The single terrain plane is badly placed, which is the honest case *for* the
   machinery.** The `zmax + 5 m` cut sits a **median 22.6 m** above local ground and up to
   **60.5 m** above it in the valleys. It is not a 1.5 m handset plane anywhere except on
   the hilltops.

4. **But the nine-plane stack has a discretisation artifact we found and are reporting.**
   With 9 planes over 55.5 m of relief the plane spacing is 6.94 m, so nearest-plane
   selection can land the measurement point up to 3.47 m **below** local ground.
   **29.0 % of cells** have their selected plane underground. Those cells read zero path
   gain and are indistinguishable from genuine shadow in the shipped map — they are the
   contour-following white bands visible in the figure's third panel. Excluding them drops
   terrain_ground's no-coverage fraction from **28.1 % to 6.8 %**, i.e. essentially *all*
   of the apparent extra shadow in the ground-following map is discretisation, not radio.
   The shipped `coverage_pathgain_db_terrain_groundfollow.png` should not be read as a
   coverage-hole map at its stated 28 %.

---

## Limitations (all of them)

- **Uncalibrated.** There is no measurement campaign, drive test, or published dataset
  anywhere in this directory. C1 compares two *models* to each other. Agreement between
  them is evidence of consistency, **not** of accuracy against reality. Neither model has
  been shown to be right.
- **1×1 V-polarised, single element.** Both studies use one `tr38901` element at the TX and
  one `dipole` at the RX, V-polarised, no downtilt, no sector pattern, no MIMO. A real
  sector antenna would change every number.
- **C1 is one transect, 14 points, fully LoS, one tower, one frequency, flat scene.** The
  diffraction term never fired. It is not a test of the analytical model in clutter or
  shadow, and no such test is presented here.
- **C1's RT ground truth is an incoherent per-path power sum**, which structurally favours
  the analytical model's phase-averaged two-ray mode. See finding 2 above.
- **GPU only.** Everything here ran on `cuda_ad_mono_polarized`. No CPU/LLVM cell was run,
  so nothing in this directory supports or refutes the paper's CPU claim.
- **Timing is indicative, not a benchmark.** Dr.Jit caches compiled kernels on disk, so
  "cold" means first solve in a fresh interpreter, not first solve ever. On an empty cache
  the C3 cells took 0.16 s / 0.16 s / 1.41 s instead of 0.025 / 0.020 / 0.193 s.
  `benchmarks/` owns the authoritative timing harness.
- **C3 harmonises cell sizes** to 8 m; the shipped flat stage uses 5 m and 10⁷ samples at
  that resolution, so its published map is not cell-for-cell the `flat` variant here.
- **C2 is absent.** The stochastic TR 38.901 comparison — the one that would test the
  paper's "deterministic is an upgrade" claim head-on — is not in this directory.
- **No failed cells.** Both scripts record failures rather than dropping them (METHOD
  rule 5); on the recorded runs `failures` is empty in both JSONs. That is an outcome, not
  an absence of the mechanism.
