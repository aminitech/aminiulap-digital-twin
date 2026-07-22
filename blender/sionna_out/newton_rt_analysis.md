# Newton, Barbados — Sionna RT Digital-Twin Propagation Study

**Scene:** Newton / Rising Sun study area, south-central Barbados
**Engine:** Sionna RT 2.0.1 (ray tracing) on a BlenderGIS-built scene — extruded government building footprints (LiDAR `AVG_HEIGHT`), `itu_` materials, Mitsuba XML export
**Local CRS on plots:** EPSG:21292 (Barbados 1938 Grid); scene basemap built in Web Mercator
**Towers referenced:** Newton (30 m), Rising Sun (24 m monopole, ~970 m ENE of centre), Boarded Hall (15 m), Oistins
**Primary band:** 3.5 GHz, with a 1.8 / 6 / 10 GHz sweep and 28 / 60 GHz mmWave comparison
**Author:** RF / digital-twin workstream · 2026-07-22

---

## 1. Executive summary

The ray-tracer is producing physically clean, internally consistent results. The Rising Sun radial link fits a log-distance model with a path-loss exponent of **n = 1.73** and an RMS residual of **0.15 dB** — this is a textbook line-of-sight (LoS), ground-reflection-dominated rural link, not a cluttered urban one. The frequency sweep behaves exactly as free-space physics predicts (≈5–6 dB of extra loss per doubling of frequency, no anomalous excess loss), which means **3.5 GHz is the coverage/capacity sweet spot**: 1.8 GHz buys ~6 dB more reach at the cost of capacity, and every band above 6 GHz pays a predictable λ² penalty. mmWave (28/60 GHz) is LoS-only with large coverage holes and should be reserved for fixed-wireless or hotspot use, not area coverage.

The two findings that matter operationally are: (1) the coverage picture **changes dramatically** between the idealized "flat ground" render and the realistic "ground-following at 1.5 m" render — planning decisions must be made on the ground-following/terrain maps, not the flat one; and (2) the four-tower SINR map is **interference-limited at the cell edges** (deep-red pockets where Newton and Rising Sun overlap, and inside the built-up Newton village), which is an antenna-tilt / power-control / frequency-reuse problem, not a coverage-hole problem.

The main caveats before these numbers are treated as bankable: the geometry is in a distance-distorting projection, the materials are concrete/generic with no foliage or rain, and there is no field calibration yet. Recommendations are in §6.

---

## 2. How to read each output

Before interpreting, a shared vocabulary for the figures.

**Path-gain (coverage) maps.** Colour = received path gain in dB (yellow ≈ −80 to −90 dB strong, blue/purple ≈ −140 dB and below weak). Red triangles are transmitters. **White = no ray hit** the grid cell within the solver's depth/sample budget — i.e. below the noise floor or in deep shadow, *not* zero interference. "Best-server" means each pixel is coloured by whichever tower gives it the strongest signal.

**SINR map.** Colour = signal-to-interference-plus-noise ratio in dB. Green (15–30 dB) = high throughput; yellow (~10 dB) = usable; red (<5 dB, down to −5) = cell-edge, interference-dominated, low or no service. Unlike the path-gain map, red here can sit right next to a tower if a *second* tower is interfering.

**Serving-cell / handover map.** Each pixel coloured by which tower serves it. Boundaries between colours are handover lines; ragged boundaries indicate ping-pong risk.

**Delay-spread / link-metrics chart & CSV.** `path_gain_dB` is the link budget vs distance; `delay_spread_ns` is the RMS spread of multipath arrival times; `num_paths` is how many distinct rays reached the receiver. Low delay spread = a clean channel; high delay spread = frequency-selective fading that an OFDM waveform must equalize.

**Flat vs terrain vs ground-following.** Three fidelity tiers of the same scene: *flat ground* (buildings on a plane — optimistic, smooth), *terrain drape* (buildings on the 55–110 m DEM — adds hill shadowing), *ground-following at 1.5 m AGL* (receiver at handset/pedestrian height following the terrain — the most realistic and most fragmented).

**Perspective ray / radiomap renders.** The 3D views (yellow TX, white RX dots, drawn rays; and the radiomap draped over terrain) are geometry sanity checks — confirm the rays leave the tower, reflect off the right facets, and reach receivers.

---

## 3. Quantitative findings — the Rising Sun radial link

Fitting `link_metrics.csv` (14 receivers, 50–1350 m from the Rising Sun tower) to a log-distance model `PL = 10·n·log₁₀(d) + C`:

| Quantity | Value | Interpretation |
|---|---|---|
| Path-loss exponent **n** | **1.73** | Below free-space (n = 2). Constructive ground reflection (two-ray, below breakpoint) over open farmland. |
| Slope | 17.3 dB/decade | vs 20 dB/decade for free space |
| RMS fit residual | **0.15 dB** | Exceptionally clean — an unobstructed LoS radial with almost no random shadowing |
| Path gain range | −98.9 dB @ 50 m → −123.8 dB @ 1350 m | ~25 dB over 1.3 km |

The sub-free-space exponent is the signature of a rural LoS link where the ground bounce adds to the direct ray. That the residual is 0.15 dB tells us this particular transect runs over open ground with no buildings interrupting it — consistent with the coverage maps, where the strong yellow lobe from Rising Sun points into the open field east of Newton.

**Multipath structure — the delay-spread spikes.** Delay spread is essentially zero (0.1–1 ns, `num_paths = 2`: direct + ground) at every receiver *except* four points where a third ray appears:

| Distance | RMS delay spread | Excess path length | Coherence bandwidth Bc ≈ 1/(2π·τ) |
|---|---|---|---|
| 450 m | 361 ns | ~108 m | ~440 kHz |
| 550 m | 168 ns | ~50 m | ~950 kHz |
| 950 m | 197 ns | ~59 m | ~810 kHz |
| 1050 m | 3.95 ns | ~1 m | ~40 MHz |

Where a building or terrain facet throws a long echo (100 m of extra path at 450 m), the coherence bandwidth collapses to well under 1 MHz. A 100 MHz OFDM carrier at those exact spots is **highly frequency-selective** and leans hard on the cyclic prefix and equalizer. These are isolated, scene-specific reflectors — not a general condition — but they are precisely the locations a link-adaptation or sensing algorithm should care about. (For the ISAC / network-as-sensor roadmap, these third-path returns *are* the sensing observable: log the full channel impulse response — per-path delay, angle, Doppler — not just the aggregate delay spread.)

---

## 4. Frequency behaviour

**Sub-6 sweep (flat-ground best-server medians):**

| Band | Median path gain | Δ vs previous | Free-space λ² prediction |
|---|---|---|---|
| 1.8 GHz | −108 dB | — | — |
| 3.5 GHz | −114 dB | −6 dB | −5.8 dB |
| 6.0 GHz | −119 dB | −5 dB | −4.7 dB |
| 10.0 GHz | −123 dB | −4 dB | −4.4 dB |

Every step matches the free-space frequency term (20·log₁₀(f₂/f₁)) to within ~1 dB. There is **no anomalous excess loss** with frequency in this scene — the penalty for going higher is purely the shrinking aperture, exactly as theory says. Practical read: 1.8 GHz gives ~6 dB more link margin (≈2× the coverage radius) than 3.5 GHz but with proportionally less spectrum/capacity; bands above 6 GHz cost margin for capacity you only benefit from close to the tower. **3.5 GHz is the correct primary band** for this coverage/capacity trade.

**mmWave (concrete-only materials):** 28 GHz median −130 dB, 60 GHz median −136 dB. The 6 dB gap is roughly the frequency term; 60 GHz additionally carries ~15 dB/km of oxygen absorption that this concrete-only run understates. Both maps show **large white NLoS holes** — mmWave here is a LoS-only technology. Use it for fixed-wireless access or dense hotspots with engineered LoS, never for area coverage, and expect these figures to be **optimistic** (no foliage, no rain — see caveats).

---

## 5. Coverage, SINR and multi-tower behaviour

**Fidelity matters more than any single number.** The flat-ground 3.5 GHz map shows a broad, smooth coverage blanket. The terrain-drape map introduces hill shadowing (white NLoS wedges to the NW). The **ground-following 1.5 m map is markedly more fragmented** — deep shadow behind the Newton village buildings and in terrain lows. This is the realistic UE-height experience and is the map planning should use. The gap between "flat" and "ground-following" is the gap between a marketing coverage map and what a phone actually sees.

**SINR is interference-limited, not coverage-limited.** The four-tower SINR map (2 W/sector, 100 MHz) is green (15–30 dB, high throughput) across the cell interiors but shows **red cell-edge pockets** where Newton's and Rising Sun's footprints overlap, and inside the dense SW built-up area where shadowing drops the serving signal while a neighbour still interferes. The problem at those pixels is not lack of signal — it is competing signal. Levers: antenna down-tilt, transmit-power balancing, inter-cell interference coordination (ICIC), or fractional frequency reuse.

**Handover / serving-cell.** The best-server association is dominated by **Newton and Rising Sun** — the two towers inside the study box. Boarded Hall and Oistins sit far outside the window and serve almost none of it; in the four-tower model they contribute mainly as distant interferers. Either expand the study area to make those two meaningful, or reconsider whether the four-tower scenario is the right one to evaluate here.

**Drive-test animation (`moving_rx.gif`).** The moving-receiver run demonstrates dynamic best-server tracking and a live link budget along a route — the right harness for validating handover thresholds and ping-pong. (The opening frame's −200 dB / "step 0" is a placeholder before the first sample, not a result.)

---

## 6. Caveats — read before treating numbers as bankable

1. **Projection / distance fidelity.** The scene was assembled in Web Mercator, which stretches distance ~2.6% at 13°N. Link budgets and delay-spread excess-path figures inherit that error. **Rebuild the geometry in UTM 20N (EPSG:32620)** for metric-accurate path lengths before any figure is quoted externally.
2. **Materials are optimistic.** `itu_` generic materials; the mmWave run is concrete-only. There is **no foliage and no rain** — both are first-order effects in humid, vegetated, tropical Barbados, especially at 6 GHz+. Add `itu_vegetation`/foliage loss, seasonal wet-ground permittivity, and ITU-R P.838 rain attenuation at the local rain rate before trusting mmWave coverage.
3. **Geometry simplifications.** Buildings are flat-top extrusions from LiDAR `AVG_HEIGHT` — no roof pitch, no indoor structure, no small clutter (vehicles, poles, walls). Indoor penetration is not modelled.
4. **Fidelity tier.** Quote the **ground-following/terrain** maps for planning; the flat-ground maps are a smooth idealization useful only for relative comparisons (e.g. the frequency sweep).
5. **Sampling artifacts.** The speckled/dithered look of the maps is radio-map grid sampling and finite ray count, not physical fading. Document and, where decisions depend on it, raise the solver's `max_depth` and samples-per-cell and the radio-map resolution.
6. **No field calibration yet.** These are simulator outputs. They have not been reconciled against a drive test or against the deployed Ulap Scope stochastic plan (TR 38.901: coverage 38.7%, RSS P50 −72.6 dBm, SINR P50 10.3 dB).

---

## 7. Recommendations

**Immediate (fidelity & trust)**
- Rebuild the study area in **UTM 20N (EPSG:32620)** and re-export; re-run the link-metrics transect to confirm the 2.6% distance correction on path length and delay.
- Add **foliage and rain** to the material/channel model; re-run the mmWave and 6/10 GHz cases, which are currently the most optimistic.
- **Calibrate** the RT output against one real drive test and against the Ulap Scope TR 38.901 plan. Reconcile the deterministic (RT) and stochastic (3GPP) coverage numbers and record the offset.

**Planning decisions supported now**
- Adopt **3.5 GHz as the primary coverage/capacity band**; hold 1.8 GHz as a coverage-fill/rural option (~6 dB margin) and treat 28/60 GHz strictly as engineered-LoS FWA/hotspot.
- Base all coverage/acceptance calls on the **ground-following 1.5 m** map, not flat.
- Attack the **cell-edge SINR** red zones with down-tilt + power balancing + ICIC/frequency reuse before adding sites; only add a tower if a genuine coverage hole (not an interference overlap) remains.
- Resolve the **tower set**: Boarded Hall and Oistins add nothing inside this window — either enlarge the study box so a 4-tower model is meaningful, or evaluate the realistic 2-tower (Newton + Rising Sun) case.

**Toward the S-CDT / ISAC roadmap**
- Log the **full channel impulse response** (per-path delay, angle-of-arrival, Doppler), not just aggregate delay spread. The third-path returns at 450/550/950 m are the raw material for network-as-sensor: today's "delay-spread spike" is tomorrow's sensing detection.
- Turn the moving-receiver harness into a repeatable, scripted **drive-test replay** so handover thresholds and ping-pong can be regression-tested as the scene evolves.
- Record and version the solver parameters (`max_depth`, samples, radio-map cell size, band, materials) alongside each output so figures are reproducible and provenance-tracked — consistent with the zero-trust/integrity spine.

---

## 8. Figure index

| File | What it shows | Use it for |
|---|---|---|
| `scene_render.png` / `scene_render_terrain.png` / `blender_perspective.png` | The built scene (flat / on terrain / oblique) | Geometry sanity check |
| `coverage_pathgain_db.png` | 3.5 GHz best-server, flat ground | Relative comparison only (optimistic) |
| `coverage_pathgain_db_terrain.png` | 3.5 GHz, terrain drape (55–110 m) | Hill-shadowing view |
| `coverage_pathgain_db_terrain_groundfollow.png` | 3.5 GHz, 1.5 m AGL following terrain | **Planning / acceptance** (most realistic) |
| `link_metrics.csv` / `link_metrics.png` | Path gain & delay spread vs distance, Rising Sun radial | Log-distance fit, multipath analysis (§3) |
| `sweep_frequency.png` | 1.8 / 3.5 / 6 / 10 GHz medians | Band selection (§4) |
| `mmwave_concrete_coverage.png` | 28 & 60 GHz, concrete-only | FWA/hotspot feasibility (optimistic) |
| `sinr_map.png` | Best-server SINR, 4 towers, 2 W, 100 MHz | Interference / cell-edge (§5) |
| `multitower_bestserver_handover.png` | Path gain + serving-cell association | Handover, tower-set review (§5) |
| `moving_rx.gif` | Drive-test with live link budget | Dynamic/handover validation |
| `persp_paths.png` / `persp_radiomap.png` | 3D rays and draped radiomap | Ray-geometry verification |
