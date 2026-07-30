# `visual/` — reproducible visual evidence

Fixed-viewport, fixed-camera, fixed-scene screenshots of the Ulap digital twin and the
committed Sionna-RT render outputs. Everything here regenerates from one command; if a
third party runs that command and gets a different PNG, that is a bug in this harness,
not a matter of taste.

**Failures are captured, not hidden.** Three of the twelve shots are failure states. They
are taken at the same viewport, in the same run, with the same settings as the rest.

---

## Regenerate everything

```bash
bash visual/run.sh
```

That is the whole command. It:

1. starts the repo's own twin-viewer server (`examples/apps/twin_viewer/serve.py`) on an
   OS-assigned free port,
2. starts a stdlib `http.server` rooted at the repo root so the comparison page can reach
   `blender/sionna_out/*.png`,
3. drives the cached Playwright chromium through the twelve shots,
4. writes `visual/shots/*.png`, `visual/shots/manifest.json`, and
   `visual/shots/failure-coverage-explorer.log`,
5. tears both servers down.

Prove it is deterministic:

```bash
bash visual/check-determinism.sh      # 3 capture runs, sha256 diffed per file
bash visual/check-determinism.sh 5    # more paranoid
```

Two runs is not enough. Every non-determinism this harness had to kill reproduced
roughly **one run in four**, so a two-run check passes on a broken harness most of the
time. The committed shots were verified byte-identical across **6 consecutive full
invocations** on this host.

### Requirements

| thing | value | why |
| --- | --- | --- |
| browser | `/home/$USER/.cache/ms-playwright/chromium-1232/chrome-linux/chrome` | **There is no Chrome for ARM64.** This box is aarch64 (GB10). The bundled Playwright chromium is the only browser; `run.sh` passes it as an explicit `executablePath`, so the usual Playwright browser-revision check is bypassed and no download is attempted. |
| runner | `@playwright/test` 1.61.0 | Not vendored into this repo. `run.sh` searches, in order: `PW_BIN`, `visual/node_modules`, repo-root `node_modules`, then two known installs on this box. Elsewhere: `cd visual && npm install`. |
| python | `python3` on PATH, overridable with `VISUAL_PYTHON` | numpy / matplotlib / pillow present, **streamlit deliberately absent (the recorded hashes were produced with a venv carrying numpy/matplotlib/pillow and no streamlit)** — see the failure case below. |

Overrides: `VISUAL_CHROMIUM`, `VISUAL_PYTHON`, `PW_BIN`, `VISUAL_ALLOW_NETWORK`.

---

## Fixed settings (identical for every shot)

| setting | value |
| --- | --- |
| viewport | **1600 × 900** (no test resizes it) |
| deviceScaleFactor | **1** |
| colour scheme / locale / timezone | `dark` / `en-US` / `UTC` |
| colour profile | `--force-color-profile=srgb` |
| text rasterisation | `--font-render-hinting=none --disable-lcd-text` |
| WebGL | ANGLE + SwiftShader software rasteriser (`--use-angle=swiftshader --enable-unsafe-swiftshader`); this box is headless with no GPU path to the browser |
| workers / retries | 1 / 0 — a retried shot is a different shot |
| CSS animation | `animations: 'disabled'` on every `page.screenshot` |
| JS animation clock | pinned to **t = 20000 ms** (see below) |
| `Math.random` | replaced with fixed-seed mulberry32, **seed `0x5cd70001`** (see below) |
| external network | **blocked** — every non-loopback request is aborted |

### Camera

Neither viewer is driven by the harness. Both cameras are whatever the *app's own code*
produces from a fixed input, and the harness never clicks, drags, scrolls, or resizes:

* **2-D map (`index.html`)** — orthographic-style fit computed by `app.js:fit()` from the
  viewport. Pinning the viewport pins the camera.
* **3-D scene (`scene.html`)** — `scene.js:focusTx()`:
  `controls.target = (tx, 10, tz)`,
  `camera.position = (tx − min(WW,WH)·0.42, max(WW,WH)·0.34, tz + min(WW,WH)·0.5)`,
  FOV 46°, aspect 1600/900. Site is the app default (Rising Sun); the layer under test is
  selected by the URL hash (`#radio` / `#paths` / `#both`), which is a committed,
  non-interactive input.

### The six things that would otherwise make this non-deterministic

Each of these was found by capturing repeatedly and diffing pixels, not by reasoning.

1. **Random tower azimuths.** `ulap-twin-ui/app.js:70` seeds `state.towers[].az` from
   `Math.random()`. An `addInitScript` replaces `Math.random` with a fixed-seed mulberry32
   *before any page script runs*, so the towers are identical every run.
2. **rAF-timestamp animation.** `app.js:drawRings()` animates propagation pulses off the
   `requestAnimationFrame` timestamp (`state.t`). The same init script wraps
   `requestAnimationFrame` so the harness can pin the timestamp handed to callbacks. Every
   shot is taken at **t = 20000 ms** — the same frame, not "whatever frame we happened to
   grab".
3. **Count-up animations still running at shutter time.** `app.js:refreshReadout(true)`
   animates `#m-cov` over 900 ms via anime.js, finishing *after* the intro overlay is
   removed. Waiting only for the intro caught the counter mid-flight. Fixed by a
   **DOM-settle gate**: the shot waits until the page's visible text (excluding the masked
   readouts) is unchanged across 3 × 200 ms samples, and throws if it never settles.
4. **A boot toast on a 2600 ms timer.** The shot now waits for `#toast` to drop its
   `.show` class, so no run can straddle its appearance.
5. **A forever `setInterval` rewriting the topbar.** `app.js:486` flips `#t-clock` between
   `LIVE` and `● REC` every 2 s. Masking alone could not beat it — the timer fires between
   the mask box being measured and the shutter, which changes the element's width and
   leaks a character out from under the mask (observed). The init script therefore tracks
   every `setInterval` id and exposes `window.__stopTimers()`, which the harness calls
   before shooting.
6. **Webfont over the network.** `ulap-twin-ui/index.html` loads Geist from
   `fonts.googleapis.com`. All non-loopback requests are aborted, so the shots are
   identical online and offline; the page falls back to the system sans/mono stack. Set
   `VISUAL_ALLOW_NETWORK=1` to let the webfont through — the shots will then legitimately
   differ from the committed ones.

### What is masked, and why

Some readouts are physically incapable of being deterministic. For each of them the
harness does three things, in order, and records all of it in `shots/manifest.json`:

1. stops the page's interval timers (`window.__stopTimers()`),
2. substitutes a fixed-width placeholder `———` (`maskPlaceholder` in the manifest) and
   pins the element's box, so the mask rectangle cannot change size,
3. paints an opaque `#2A2A2E` box over it with Playwright's `mask:` option — so a reader
   can **see** that something was hidden, rather than having a number quietly rewritten.

`maskedSelectors` per shot:

| selector | shot | what it is |
| --- | --- | --- |
| `#t-fps` | 2-D map, no-data failure | frame-rate counter |
| `#t-clock` | 2-D map, no-data failure | `LIVE` / `● REC` toggle on a forever `setInterval(2000)` |
| `#s-fps` | 3-D scenes | frame-rate counter |
| `#badge-txt` | 3-D scenes | "Radio map computed in *N* ms" / "Paths computed in *N* ms" |

Nothing else is edited, hidden, cropped, or retouched. No shot is retried, and no frame is
chosen for looking better than another.

---

## The shots

All twelve are 1600×900, dSF 1, PNG. `shots/manifest.json` carries the per-shot URL,
readiness signal, masked selectors, captured console errors, byte size and sha256.

| file | what it shows |
| --- | --- |
| `twin-viewer-2d-map.png` | `ulap-twin-ui/index.html` — the 2-D operations map: 576 LiDAR-height building footprints, the Newton and Rising Sun towers, the analytical coverage heatmap and propagation rings, left control panel, right analysis readout (29.0 % predicted coverage, RSS P50 −103 dBm, cell radius 485 m). |
| `twin-viewer-3d-radio.png` | `scene.html#radio` — three.js twin, path-gain radio map draped on the ground plane, viridis scale. |
| `twin-viewer-3d-paths.png` | `scene.html#paths` — the same camera, 440 traced ray paths from the TX, ray-density legend. |
| `twin-viewer-3d-both.png` | `scene.html#both` — radio map **and** ray paths together. Same camera as the two above, so the three are directly comparable. |
| `rt-compare-fidelity.png` | `visual/pages/rt-compare.html?c=fidelity` — **terrain drape vs ground-following at 1.5 m AGL**, 3.5 GHz. `coverage_pathgain_db_terrain.png` vs `coverage_pathgain_db_terrain_groundfollow.png`, each in an identical 700×640 box, `object-fit: contain` (no crop, no stretch). |
| `rt-compare-band.png` | `visual/pages/rt-compare.html?c=band` — **sub-6 sweep vs mmWave**. `sweep_frequency.png` (1.8/3.5/6/10 GHz medians) vs `mmwave_concrete_coverage.png` (28 & 60 GHz, concrete-only), same identical boxes. |
| `defect-f8-receiver-plane.png` | `visual/pages/defect-f8-receiver-plane.html` — **defect F8**, the receiver-plane selection rule drawn over one plane interval, beside the before/after measurements. See below. |
| `defect-f9-colour-scale.png` | `visual/pages/defect-f9-colour-scale.html` — **defect F9**, the two published coverage figures' own colourbars, cropped out of the committed PNGs and stood side by side, then aligned on one dB axis. See below. |
| `defect-f10-sampling.png` | `visual/pages/defect-f10-sampling.html` — **defect F10**, no-coverage fraction against rays per transmitter, plus what the residual extra shadow is made of at each level. See below. |
| `failure-coverage-explorer.png` | **FAILURE.** See below. |
| `failure-twin-viewer-no-data.png` | **FAILURE.** See below. |
| `failure-f9-shared-scale-absent.png` | **FAILURE.** See below. |

### Reading the RT comparison honestly

The two source renders in `?c=fidelity` carry **independent colourbar ranges**
(A ≈ −160…−85 dB, B ≈ −155…−80 dB). They are *not* on a shared colour scale. Compare the
spatial structure and read each colourbar; do not compare hue between panels. This caveat
is printed in the page footer so it travels with the screenshot.

Captions on the comparison page are quoted from
`blender/sionna_out/newton_rt_analysis.md`; the PNGs themselves are used unmodified.

---

## The coverage-map defects — F8, F9, F10

Three defects were found and fixed in the coverage stages and written up in
`docs/audits/2026-07-29-f8-f9-receiver-plane-and-colour-scale.md`. Three shots exist so a
reader can *see* each one rather than take the audit's numbers on trust, and a fourth
records the one "after" state that cannot be photographed at all.

**Where the numbers come from.** Every value on these three pages is fetched by the page
itself, live, from `comparison/results/f8.json` over loopback at capture time, and the
**JSON pointer is printed next to it** (`verdict.underground_cell_fraction`,
`sample_convergence.by_samples_per_tx.…`, and so on). Nothing is transcribed into the HTML
except axis furniture and the colourbar crop geometry. Each page also stamps the results
file's own `generated_utc` into the shot, so two shots of two different datasets can never
be mistaken for each other — see the caveat at the end of this section.

### `defect-f8-receiver-plane.png` — the receiver was underground

To produce a map at a constant 1.5 m above ground over 55.5 m of relief the stage solved
`K = 9` horizontal planes and, per cell, picked the one **nearest** to `terrain + 1.5 m`.
Nine planes over 55.52 m is 6.94 m spacing, so "nearest" reaches up to ±3.47 m — and below
1.5 m of that is *underground*.

The left panel draws exactly that, over **one plane interval**, with the ground rising
linearly across it: the plane stack, the target line, the plane "nearest" actually selects,
and the shaded band where the selection is below the ground. Beneath it, the same interval
as a signed height error, with the "below local ground" band shaded and the "ceiling" rule
drawn over the top for comparison.

**Why a diagram and not a screenshot.** `comparison/results/f8.json` carries the relief
(55.52 m) and its extremes (54.74 / 110.26 m) but **no terrain height profile**, so no
terrain profile is drawn — the page says so, and the caption in `manifest.json` says so.
Drawing a plausible-looking hill would have been inventing data.

What the interval picture buys instead is a **prediction that can be checked**. With ground
uniform across one interval, "nearest" is below ground for

```
(spacing/2 − rx_agl) / spacing = (3.47 − 1.5) / 6.94 = 28.39 %
```

and the stage measured **28.97 %** on the real 91,745-cell grid. The page prints both and
the difference. That is the rule, not a coincidence — which is the whole point of the
diagram. Both figures are read live out of `f8.json`
(`variants.K9_nearest__shipped.plane_spacing_m`, `config.rx_agl_m`,
`verdict.underground_cell_fraction.before`).

The right panel is the before/after table straight from `verdict.*`, plus the claim the
numbers actually support (serving-cell association change against the Monte-Carlo noise
floor) rather than the shadow-area claim the published figure implied.

### `defect-f9-colour-scale.png` — the two figures were on different colour scales

`sionna_coverage.py` and `sionna_terrain_ground.py` each computed `vmax` from the 99th
percentile of **their own** data and set `vmin = vmax − 80`. The paper places the resulting
figures adjacent with a caption inviting comparison.

This one needs no argument at all, because the defect is visible in the committed pixels.
In both PNGs the colourbar rectangle occupies the **identical rows, 92–1051**, and both are
the same viridis ramp (top `rgb(253,231,37)`, bottom `rgb(68,1,84)` in each). Only the tick
**labels** differ. So:

* **Panel 1 — as published.** Both colourbars cropped straight out of the committed PNGs at
  their published position and stood side by side. Same ramp, same screen height; the dB
  labels beside them disagree.
* **Panel 2 — aligned on one dB axis.** The same two crops, with B shifted **up 34 source
  pixels** so the two dB axes coincide. Now the labels agree and the ramps are visibly
  offset. That displacement *is* F9.

The crops are CSS windows onto the unmodified files (`overflow: hidden` + negative offsets,
drawn at natural size inside one uniform `scale()`). **No pixel is recoloured, resampled or
re-rendered.** The exact crop box and scale are printed in the page footer.

**How 34 px / 2.83 dB was measured** — this is the one number on these pages that comes
from neither `f8.json` nor the audit, so here is the method. Locate the colourbar (the only
tall run of saturated columns, x 1224–1271), find its extent by fitting the inverted viridis
LUT against row index, find the tick marks (dark pixels in x 1272–1279), and fit dB against
row from the tick spacing:

```bash
python3 - <<'EOF'
from PIL import Image
import numpy as np, matplotlib.cm as cm
vir = (np.array([cm.viridis(i/255.0)[:3] for i in range(256)]) * 255)
inv = lambda rgb: ((vir - rgb) ** 2).sum(1).argmin() / 255.0
for n, f, top in [('A', 'coverage_pathgain_db_terrain.png', -90.0),
                  ('B', 'coverage_pathgain_db_terrain_groundfollow.png', -80.0)]:
    im = np.array(Image.open('blender/sionna_out/' + f).convert('RGB')).astype(float)
    ys = np.arange(100, 1045)                       # inside the bar
    ts = np.array([inv(im[y, 1245]) for y in ys])   # colour -> normalised position
    a = np.polyfit(ys, ts, 1)
    y1, y0 = (1.0 - a[1]) / a[0], (0.0 - a[1]) / a[0]
    dark = (im[:, 1272:1280].mean(2) < 140).sum(1)  # tick marks
    tr = np.where(dark >= 4)[0]
    g, cur = [], [tr[0]]
    for v in tr[1:]:
        (cur.append(v) if v - cur[-1] <= 3 else (g.append(cur), cur := [v]))
    g.append(cur)
    cs = np.array([np.mean(x) for x in g])
    p = np.polyfit(cs, top - 10.0 * np.arange(len(cs)), 1)
    print(n, 'vmax %.2f  vmin %.2f  span %.2f' % (np.polyval(p, y1), np.polyval(p, y0),
                                                  np.polyval(p, y1) - np.polyval(p, y0)))
EOF
```

```
A vmax -82.80  vmin -162.51  span 79.71     # terrain drape
B vmax -79.99  vmin -159.75  span 79.77     # ground-following
```

Both span 80 dB, as `vmin = vmax − 80` implies. The offset between them is
**2.83 dB** (34 px at the measured 12.0 px/dB), so the same hue reads ~2.8 dB *lower* on
panel A than on panel B. Panel B already sits within 0.05 dB of the shared scale the fix
resolves (`vmin = −160, vmax = −80`); panel A is the one that is off.

The earlier estimate in this file — "A ≈ −160…−85, B ≈ −155…−80" — was eyeballed off the
tick labels and is superseded by the numbers above.

**The "after", in the stage's own words.** The rendered shared-scale pair does not exist
(below), but the fix *is* captured in text: `f8.json` carries the stage stdout, which now
prints the scale each figure resolved and its saturation fraction. The page quotes those
lines verbatim from `stage_cost.{K9,K57_default}.stdout_tail`, and flags that they are the
ground-following figure's lines — the audit's claim that *both* terrain figures land on the
same scale in one pipeline pass is not something this artifact itself contains.

### `defect-f10-sampling.png` — most of the dark area was never sampled

A dark cell has two causes that look identical in the figure: nothing reaches it, or no ray
landed on it. They are told apart by firing more rays and watching. The left chart plots
no-coverage fraction against `samples_per_tx` on log–log for the ground-following map, the
single horizontal plane, and the extra shadow between them — **four measured points,
nothing interpolated**. The right chart is what the residual is attributed to (ridge /
building / unexplained by geometry) at each level.

Two details worth knowing:

* The exact zero at 10⁹ (`terrain_plane_no_coverage_fraction = 0.0`) **cannot be drawn on a
  log axis.** It is plotted as a dashed open marker on the axis floor and labelled
  "0.00 % — cannot be drawn on a log axis", rather than silently clamped to the floor value.
* The **stage default is read, not assumed** — out of
  `stage_cost.K57_default.stdout_tail` — and compared against the default named in the
  audit's own F10 table. When those two disagree, the page says so on the shot. They did
  disagree the first time this ran: the audit was written against 10⁶, and the stage default
  had since moved to 10⁸. The committed figures in `blender/sionna_out/` predate the change.

---

## Failure cases (captured, at the same settings)

### 1. `failure-coverage-explorer.png` — the Streamlit app cannot start

`examples/apps/coverage_explorer/app.py` needs Streamlit. The pinned interpreter does not
have it, and installing a heavyweight dep was out of scope, so the spec **attempts the
documented launch for real**, records the interpreter's exact output, and then photographs
Chromium's genuine connection-refused page at 1600×900.

```
$ …/venv-twin/bin/python -m streamlit run examples/apps/coverage_explorer/app.py --server.port <ephemeral>
exit code: 1

…/venv-twin/bin/python: No module named streamlit
```

Verbatim output is committed at `shots/failure-coverage-explorer.log`. The spec is written
so that if Streamlit *is* installed on some other host, the app starts, the real UI is
photographed, and the `shows` field in `manifest.json` says so — i.e. the failure is
recorded as a fact about this host, not baked in as an assumption.

**To turn this into a real screenshot:** `pip install streamlit` into the interpreter you
pass as `VISUAL_PYTHON` and re-run `bash visual/run.sh`. Nothing else needs to change.

### 2. `failure-twin-viewer-no-data.png` — the viewer with its scene data unreachable

Deliberate, reproducible fault injection: the harness aborts the request for
`ulap-twin-ui/data.js` via route interception. **Nothing in the repo is modified.**

The result is worth looking at: **the viewer fails silently.** The page is a near-black
1600×900 rectangle — no error banner, no fallback, no "failed to load scene" message; only
the abandoned intro progress bar and a stray element remain. `app.js` throws on
`D.buildings` with `D === undefined` and the render loop never starts. The captured page
errors are in `manifest.json` → `consoleErrors` for that shot. If the twin viewer is ever
put in front of a customer, this is the blank screen they get when an asset 404s.

---

### 3. `failure-f9-shared-scale-absent.png` — the F9 "after" does not exist to photograph

The F9 fix landed in `sionna_coverage.py` / `sionna_terrain_ground.py`. The committed
renders in `blender/sionna_out/` predate it, and **this harness photographs what the stages
committed — it does not run them.** So the pair a reader actually wants, the same two
figures on one scale, is not an image anywhere in this repo.

Rather than omit that, it is photographed at the same 1600×900 settings, and the page
*demonstrates* the absence instead of asserting it:

* it fetches the **live directory listing** of `/blender/sionna_out/` from the same static
  server the other shots use and prints every entry, unfiltered, with the two published
  path-gain terrain figures highlighted and the count of files matching
  `/shared|common|joint/` (currently `NONE`);
* it fetches the audit and quotes § F9 **verbatim**, so the claim that the fix landed in
  code is sourced rather than repeated;
* it states the acceptance criteria the "after" shot must meet when it does exist.

The spec asserts all of this: both fetches must succeed, the listing must contain the two
published figures, and it must contain **no** shared-scale variant. If a shared-scale render
ever lands, that last assertion fails loudly and this failure case has to be retired — it
cannot quietly stay "true" after it stops being true.

**To turn this into a real screenshot:** re-run the coverage stages so `blender/sionna_out/`
carries a shared-scale pair, then point the second panel of
`visual/pages/defect-f9-colour-scale.html` at it. Nothing else here needs to change.

## What could NOT be captured, and why

* **The Streamlit coverage explorer's actual UI.** Streamlit is not installed in the pinned
  venv (`VISUAL_PYTHON`), and installing a heavyweight dependency was explicitly out of
  scope for this task. Captured as a failure case instead (above), with the verbatim
  interpreter output. This is the single largest gap in this evidence set.
* **`ulap_demo` / `ulap-scope` import health for the coverage explorer.** Because the app
  dies at `import streamlit` (line 19) it never reaches `from ulap_demo import …`
  (line 26). Whether those imports resolve under this interpreter is therefore **unknown
  and untested here** — do not read the failure shot as evidence either way.
* **GPU-path rendering of the 3-D scene.** The shots use ANGLE + SwiftShader software
  rasterisation. Anti-aliasing and gradient dithering may differ from a GPU-backed browser,
  which is exactly why the shots are deterministic on this box but should not be
  byte-compared across machines.
* **Branded typography.** Because external requests are blocked for hermeticity, Geist /
  Geist Mono are not loaded and the pages render in the system sans/mono fallback. Re-run
  with `VISUAL_ALLOW_NETWORK=1` for the branded look; those shots will not match the
  committed hashes.
* **Anything requiring interaction.** No clicks, drags, scrolls, slider moves, or receiver
  placement. Every shot is the app's default state for the given URL. That is a deliberate
  objectivity constraint (no cherry-picked frames), not an oversight — the interactive
  states of both viewers are unphotographed.
* **`blender/sionna_out/moving_rx.gif`** and the other RT outputs not listed above. The
  comparison page deliberately shows only the two comparisons named in the task; adding
  more is a one-line edit to `COMPARISONS` in `pages/rt-compare.html`.
* **The F9 "after": a shared-scale rendering of the two coverage figures.** It does not
  exist in `blender/sionna_out/`, and producing it means running the RT stages, which this
  harness does not do. Captured as a failure case (above) with a live directory listing as
  the proof of absence. The nearest available substitute — the stage's own stdout printing
  the resolved shared scale — is quoted on `defect-f9-colour-scale.png`.
* **A terrain cross-section for F8.** `comparison/results/f8.json` carries the relief and
  its extremes but no DTM height profile, so the F8 page draws the *rule* over one plane
  interval and explicitly does not draw the Newton terrain. Do not read that diagram as a
  picture of the site.
* **The two coverage figures at a comparable spatial resolution.** They are on 5 m and 8 m
  grids. F9 fixed the colour axis, not the grid; the F9 page says so (audit § Outstanding,
  item 3).

## Determinism caveats (be honest about the boundary)

* sha256 equality is verified **run-to-run on the same host** (6 consecutive invocations
  at the time of writing). Across different hosts, chromium builds, or font sets, expect
  small rasterisation differences. The *spec* is the reproducible artifact; the hashes are
  the local proof that the spec has no internal randomness left in it.
* If a future run drifts, diff the PNGs and look at the changed bounding box before
  touching anything — every drift found here was a 20×150 px readout, not the scene.
* `shots/manifest.json` normalises the OS-assigned server ports to `<ephemeral>` so it is
  diffable too.
* **The three defect shots read a live artifact, on purpose.** `defect-f8-*`,
  `defect-f9-*` and `defect-f10-*` fetch `comparison/results/f8.json` at capture time
  rather than embedding its numbers, so the shot cannot silently go stale against the
  study. The cost is that **when the study re-runs, those three shots legitimately
  change** — that is a change of dataset, not a determinism bug. Each page therefore
  stamps the results file's `generated_utc` into the pixels, and the F10 page prints the
  stage default it read. If you are chasing a diff, check `generated_utc` first:

  ```bash
  sha256sum comparison/results/f8.json          # before
  bash visual/check-determinism.sh 3
  sha256sum comparison/results/f8.json          # after — must be unchanged
  ```

  The committed shots were verified byte-identical across two independent 3-run checks
  with `f8.json` and the two source PNGs proven unchanged across each.
* The F9 crop geometry (`x 1210–1350, y 30–1110`, colourbar rows 92–1051, 12.0 px/dB) is a
  measurement of **these** committed PNGs. If they are re-rendered at a different figure
  size, the crop is wrong and the page will show a misaligned bar rather than fail — so
  re-measure with the snippet above whenever `blender/sionna_out/coverage_pathgain_db_*`
  changes.

## Files

```
visual/
  run.sh                    one command; finds a @playwright/test CLI and runs the spec
  check-determinism.sh      captures twice, diffs sha256
  playwright.config.ts      viewport / dSF / locale / browser flags — all pinned here
  capture.spec.ts           the spec: servers, determinism init script, 8 shots
  package.json              declares @playwright/test 1.61.0 for a fresh checkout
  .gitignore                keeps runner scratch (test-results/) out of the evidence
  pages/rt-compare.html     side-by-side RT viewer, no external resources, ?c= selected
  pages/defect-f8-receiver-plane.html   F8: the plane-selection rule + before/after table
  pages/defect-f9-colour-scale.html     F9: the two committed colourbars, as published and aligned
  pages/defect-f10-sampling.html        F10: no-coverage vs samples/tx + shadow attribution
  pages/f9-shared-scale-absent.html     FAILURE: live proof the F9 "after" render does not exist
  shots/*.png               the evidence
  shots/manifest.json       per-shot settings + sha256
  shots/failure-coverage-explorer.log   verbatim interpreter output for failure case 1
```

Nothing outside `visual/` is written to. The repo's apps and RT outputs are read-only
inputs.
