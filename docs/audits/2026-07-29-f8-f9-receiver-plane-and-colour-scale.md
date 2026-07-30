# Audit — the ground-following map measured its own mistake

**Date:** 2026-07-29
**Scope:** `sionna_terrain_ground.py`, `sionna_coverage.py`, and the claims the paper makes about them
**Status:** fixed, reproduced on two architectures, one claim in the paper's abstract requires revision

---

## Bottom line

The paper's abstract says ground-following maps *"resolve ridge shadowing that a horizontal
receiver plane cannot represent."* Ridge shadowing is real, and ground-following does resolve
it. But at the settings the code ships with, **the dark area in the published figure is
overwhelmingly measurement error, not shadow.**

Two defects compounded, and a third was found while fixing them:

| | Defect | Effect on the published figure |
|---|---|---|
| **F8** | Receiver placed below ground in 28.97 % of cells | ~85 % of the "extra shadow" |
| **F10** | Only 10⁶ rays per transmitter | 47 % of the map unsampled at shipped settings |
| **F9** | The two compared figures used independent colour scales | Comparing them by eye was invalid |

After all three are addressed, genuine ridge shadow is **≈0.2 % of the map** — about 178 of
91,745 cells. The published figure implies roughly 28 %.

---

## F8 — the receiver was underground

### What the code did

To produce a map at a constant 1.5 m above ground over 55.5 m of relief, the stage solved a
stack of `K = 9` horizontal planes and, per cell, selected the plane **nearest** to
`terrain + 1.5 m`.

Nine planes across 55.5 m is 6.94 m spacing. "Nearest" therefore selects a plane up to
±3.47 m from target — and roughly half the time that is *below* it. A receiver below local
ground is occluded by terrain, returns zero path gain, and renders as shadow.

### Measured, on the 91,745-cell grid the stage actually uses

| | shipped (K=9, nearest) | fixed (K=57, ceiling) |
|---|---|---|
| Receiver below local ground | **28.97 %** | **0 %** |
| … by more than 1 m | 10.44 % | 0 % |
| Median height offset | 1.81 m | 0.45 m |
| Max height offset | 3.47 m | 0.99 m |
| No-coverage fraction | 28.12 % | 10.99 % |

Two changes, and the rule matters more than the count:

1. **Ceiling instead of nearest.** The selected plane is now always at or above the target
   height, so the receiver can never be underground. This alone takes 28.97 % to 0 %.
2. **`K` derived from a stated tolerance** (`ceil(relief / 1.0 m) + 1 = 57`) rather than a
   magic number, with `ULAP_GF_MAX_HEIGHT_ERR_M` and `ULAP_GF_PLANES` overrides.

Cost: stage wall clock 1.79 s → 2.09 s (×1.17); solver time alone ×6.3; peak RSS 564 → 637 MB.
Measured on GPU; the ×6.3 will be more visible on the CPU backend and is unmeasured there.

A useful property of the design: **K=9 is an exact subset of the K=57 stack** (56 = 8×7), so
before and after come from the *same solves*. The comparison carries no re-solve noise.

---

## F10 — most of the rest was under-sampling, not shadow

With F8 fixed, 81 % of the residual "extra shadow" was still unexplained by terrain or
building geometry. A sweep of `samples_per_tx` shows why: no-coverage falls roughly 10× per
decade of samples, with no floor until 10⁸–10⁹.

| samples/tx | plane no-cov | ground-follow no-cov | extra shadow | ridge / building / unexplained |
|---|---|---|---|---|
| **10⁶ (shipped)** | 44.3 % | **47.0 %** | 15.8 % | 1 / 14 / **85 %** |
| 10⁷ | 6.99 % | 11.0 % | 7.67 % | 5 / 14 / **81 %** |
| 10⁸ | 0.13 % | 1.16 % | 1.12 % | 26 / 22 / 51 % |
| 10⁹ | 0.00 % | **0.24 %** | 0.24 % | **81 / 14 / 5 %** |

**At the shipped default, 47 % of the ground-following map is blank because the ray tracer
did not look, not because anything is in shadow.** Only at 10⁹ does the residual resolve into
genuine geometry, and by then it is a quarter of a percent of the map.

The default was left at 10⁶ deliberately — raising it would silently change the wall-clock
figures published in `benchmarks/`. It is now a parameter (`ULAP_GF_SAMPLES_PER_TX`) with a
loud runtime warning. **Someone must decide** whether to raise the default or caveat every
dark cell in the paper.

### Independent corroboration

A pure-geometry line-of-sight test against the DTM — no ray tracer involved — puts genuine
ridge shadow at **0.75 % of the map**. The ray tracer resolves less than that (≈0.2 %)
because diffraction fills most of it in. Two independent methods agree the effect is real
and small.

---

## F9 — the two compared figures were on different colour scales

`sionna_coverage.py` and `sionna_terrain_ground.py` each computed `vmax` from the 99th
percentile of **their own** data, then `vmin = vmax − 80`. The paper places the resulting
figures adjacent with a caption inviting comparison. The same hue meant different dB in each.

Both now resolve a **shared scale per figure group**, quantised to a 5 dB grid, first-writer-
wins, with `ULAP_PG_VMIN` / `ULAP_PG_VMAX` overrides. Each figure prints the scale it is on
and the measured saturation fraction. Verified live: both terrain figures land on
`vmin = −160, vmax = −80` in a single pipeline pass.

**A failure worth recording:** the first implementation used an "only ever widen" rule, which
left the two figures on different scales until a second pipeline pass — reproducing the exact
defect F9 exists to fix. It was caught by running it, not by reading it.

---

## Cross-architecture reproduction

The study was re-run on a second machine with a different processor architecture.

| Metric | spark-5804 (GB10, aarch64) | bgi-ran-01 (H200, x86_64) |
|---|---|---|
| Underground, before | 0.28968 | 0.28968 |
| Underground, after | 0.0 | 0.0 |
| Extra shadow, before | 0.23526 | 0.23526 |
| Extra shadow, after | 0.07673 | 0.07672 |
| Ridge shadow from DTM geometry | 0.00753 | 0.00753 |
| Best-server change, after | 0.23585 | 0.23585 |
| Monte-Carlo noise floor | 0.00333 | 0.00333 |

Agreement to the last reported digit on every metric that matters. A Raspberry Pi 4 run is in progress and will be appended; it is genuinely slow there (57 planes plus a sample sweep to 10⁹ on four Cortex-A72 cores).

**One cell failed and is published as a failure rather than dropped:** `stage_cost` could not
run on the H200 because the deployment script placed the stage script at the wrong remote
path. That is a harness bug in the reproduction script, not a result.

**The x86_64 host also reproduced a known environment defect**: the first attempt failed with
`ImportError: … libLLVM.so could not be found`. This is the documented `DRJIT_LIBLLVM_PATH`
issue — dependency discovery, not an architecture limit. It recurred because the reproduction
script omitted the variable. Recording it because a defect that keeps re-appearing in fresh
scripts is a documentation failure, not bad luck.

---

## What the paper may now claim

**Supported:** ground-following resolves genuine ridge shadowing that a horizontal receiver
plane cannot represent, at **≈0.2 % of the map** (0.75 % by pure DTM geometry before
diffraction fill-in).

**Not supported:** any reading of the published figure in which the dark area represents
shadow. At shipped settings that area is ~28 % of cells, of which ~85 % was the receiver being
underground and essentially all the remainder was sample starvation.

**The stronger claim, and the one worth making instead:** the plane stack changes
**serving-cell association in 23.6 % of cells** against a 1.03 % Monte-Carlo noise floor — a
22.9× signal — and **21.6 % of cells differ by more than 10 dB**. The quantitative case for
ground-following is association and cell-edge behaviour, not shadow area.

*(The F8 study establishes its own noise floor at 0.33 %, which would give 71×. C3's is the
more conservative measurement and is the one used in the paper and here. Both are bound in
the claims register so they cannot drift apart again — an earlier draft quoted 71× in one
section and 22.9× in another.)*

---

## Outstanding

1. **The abstract needs revising** — quantify the ridge-shadowing claim rather than delete it.
2. ~~`comparison/results/c3.json` is stale.~~ **Done.** `c3_ablation.py` duplicated the
   nine-plane nearest rule; it now mirrors the stage and has been re-run. Only the
   ground-following row moves — median −117.51, p10 −127.32, p90 −92.93, no-coverage
   **11.0 %** (was 28.1 %). Two self-checks pass: 11.0 % matches the F8 study's independently
   measured 10.99 %, and the "excluding underground cells" arm now returns an identical
   result because there are none left to exclude. The paper's table and the prose after it
   are updated.

   Registering these numbers surfaced a further inconsistency that would otherwise have
   shipped: the same 23.6 % serving-cell change was quoted against **two different
   Monte-Carlo noise floors** in two sections — 0.33 % from the F8 study giving 71×, and
   1.03 % from C3 giving 22.9×, because the two studies establish the floor differently. The
   paper now uses the conservative C3 figure in both places, and both are bound in the claims
   register so they cannot drift apart again.
3. **The two compared figures are still on different grids** — 5 m cells versus 8 m. Colour is
   now comparable; spatial resolution is not.
4. **`samples_per_tx` default** — raise it, or caveat every dark cell. Not a technical
   question; it trades published wall-clock figures against figure honesty.
5. **CPU cost of K=57 unmeasured.** All timings are GPU.
