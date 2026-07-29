# Concept illustrations

Nine 16:9 hand-drawn explainers for **"Sovereign Cognitive Digital Twins: Fusing
6G ISAC, AI-RAN, and Zero-Trust Edge Grids for National Resilience in the Global
South"** (Cayetano, Gichuru, Morris — Amini).

Each image explains exactly one cognitive anchor from the paper. They are for
READMEs, docs pages, slides and talks — **not** replacements for the paper's own
figures. The architecture figure, the SCOPE screenshots and the Sionna RT result
plates stay as they are.

- PNG, 2752 × 1536 (16:9), white background.
- Black hand-drawn line art, Sunglow `#FFC83C` as the single accent.
- **Sunglow is used for strokes, arrows and highlights only. All lettering is
  black** — `#FFC83C` on white is ~1.7:1 and fails the WCAG AA contrast floor
  the design system requires.

---

## The set

| # | File | Explains | Paper section |
|---|------|----------|---------------|
| 01 | `01-perception-gap.png` | Decisions with minutes-to-hours stakes made on data with hours-to-days latency, in the least-instrumented nations | §I.A The Climate Existential Threat |
| 02 | `02-network-as-a-sensor.png` | Don't build a second sensing estate — the waveform already carrying the traffic can also be listened to | §I.B Network as a Sensor; §III.B ISAC Structural Fusion |
| 03 | `03-background-subtraction.png` | `H_ISAC = H_target + H_background`: learn and subtract the static scene, and the hazard is what's left | §IV.A Dual-Function Radar-Communication |
| 04 | `04-six-layers-one-trust-spine.png` | The six-layer stack is only a stack because one zero-trust spine runs through every layer; the upper layers are still design | §III.A The Core Stack; Table I |
| 05 | `05-belief-state-under-delay.png` | O-RAN telemetry lands ~100 ms stale, so control on a belief state and carry the covariance into the decision | §V.B Belief-State Control under Telemetry Delay |
| 06 | `06-sovereign-compute-grid.png` | Sever the link to rented compute and the twin must keep running: on-territory, CPU-only, no CUDA or cloud | §VI.A The Sovereign Compute Grid |
| 07 | `07-privacy-tiers-at-the-door.png` | One channel maps terrain *and* reads bodies — gate it at the door: L1 passes, L2 is consented, L3 is noised out | §VI.D Privacy-by-Design Waveforms |
| 08 | `08-built-vs-specified.png` | The honesty boundary: what runs in Ulap SCOPE today vs. what is specified but never evaluated | §VII Barbados Implementation; Tables I–III |
| 09 | `09-frequency-ladder.png` | Every rung up in frequency buys resolution and costs reach — −108 dB at 1.8 GHz to −123 dB at 10 GHz, LoS lobes only at FR2 | §VII.H Newton Propagation Results; Table IV |

---

## Suggested use

**Repo README hero** — `02`. It carries the whole thesis in one frame and needs
no prior context.

**"What this actually is"** — `08`. The highest-value image in the set for a
public release: it sets expectations before anyone opens the code and goes
looking for an ISAC feed that is not there yet.

**Architecture docs** — `04`, then `03`, then `05`.

**Sovereignty / governance** — `06` and `07`.

**RF results** — `09`, above the real frequency-sweep figure: the illustration
is the intuition, the plot underneath is the evidence.

**Talks** — `01` opens well as a motivation slide.

Each table row doubles as alt text. From the repo root:

```markdown
![Don't build a second sensing estate — the waveform already carrying the
traffic can also be listened to](docs/illustrations/02-network-as-a-sensor.png)
```

---

## Caveats

- These are **conceptual illustrations, not figures.** No number in them is a
  measurement and none should be cited. The quantitative claims live in Table IV
  and Figures 8–13 of the paper.
- `09` compresses the frequency story. The mixed concrete/medium-dry-ground
  sweep is capped at 10 GHz by material validity, and the 28/60 GHz runs are
  concrete-only. The ladder shows the *trend*, not the study design — keep that
  caption nearby if it appears next to the real sweep.
- Hand-lettering is model-generated. Re-read the labels at full resolution
  before publishing anywhere permanent.
- **White background only.** These will look wrong dropped onto a dark page —
  wrap them in a white container if the surrounding docs are dark. That is a
  deliberate exception to the dark-mode-default rule: the style depends on ink
  on paper, and print and arXiv are light.

---

## Provenance

Generated with the [Ian Xiaohei Illustrations](https://github.com/helloianneo/ian-xiaohei-illustrations)
agent skill by **Ian** ([@ianneo_ai](https://x.com/ianneo_ai)), MIT-licensed. The
recurring black character is 小黑 ("Xiaohei"), part of Ian's visual language.

The skill defaults to handwritten Chinese annotations and a red / orange / blue
accent grammar. This set adapts it twice: to short English labels for an
international audience, and to the Amini palette — black plus Sunglow only.
Everything else follows the skill as written: white ground, one idea per image,
no top-left title, and Xiaohei performing the core action rather than
decorating it.

Per the skill's `NOTICE.md`, **keep this attribution to Ian if these images are
redistributed.**

Rendered via Nano Banana Pro at 2K, 16:9.
