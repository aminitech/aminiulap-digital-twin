/**
 * visual/capture.spec.ts — reproducible visual evidence for the Ulap digital-twin
 * comparison work.
 *
 *   bash visual/run.sh            # one command, regenerates every PNG in visual/shots/
 *
 * Design rules (all of them are load-bearing; see visual/README.md):
 *
 *   1. FIXED EVERYTHING. Viewport 1600x900, deviceScaleFactor 1, dark scheme,
 *      en-US / UTC. Nothing here resizes the viewport or moves a camera.
 *   2. NO RANDOM STATE. `ulap-twin-ui/app.js:70` seeds tower azimuths from
 *      `Math.random()`. An init script replaces Math.random with a fixed-seed
 *      mulberry32 PRNG *before* any page script runs, so the twin renders the same
 *      towers every time.
 *   3. NO WALL-CLOCK STATE. `app.js` animates propagation rings off the
 *      requestAnimationFrame timestamp (`state.t`). An init script wraps rAF so the
 *      harness can pin that timestamp to FROZEN_T. Every shot is therefore the
 *      *same frame*, not "whatever frame we happened to grab".
 *   4. HERMETIC BY DEFAULT. `ulap-twin-ui/index.html` pulls Geist from
 *      fonts.googleapis.com. All non-loopback requests are aborted so the shots are
 *      identical online and offline (the page falls back to system fonts).
 *      Set VISUAL_ALLOW_NETWORK=1 to let the webfont through — the shots will then
 *      differ from the committed ones, by design.
 *   5. READINESS IS OBSERVED, NEVER SLEPT. Each shot waits on a real signal:
 *      document.fonts.ready, the intro/loader element being removed from the DOM,
 *      images decoded, or an explicit `window.__RT_COMPARE_READY__`.
 *   6. VOLATILE READOUTS ARE MASKED, NOT EDITED. FPS counters and "computed in
 *      N ms" badges cannot be deterministic. They are covered with an opaque
 *      Playwright mask box so a reader can SEE that something was hidden, and the
 *      exact selectors are recorded in shots/manifest.json.
 *   7. FAILURES ARE CAPTURED AT THE SAME SETTINGS. Streamlit is not installed in
 *      the pinned venv; that is captured, not skipped.
 */
import { test, expect, Page, Locator } from '@playwright/test';
import { spawn, ChildProcess } from 'node:child_process';
import { createServer } from 'node:net';
import { createHash } from 'node:crypto';
import * as fs from 'node:fs';
import * as path from 'node:path';

// ---------------------------------------------------------------- constants

const REPO_ROOT = path.resolve(__dirname, '..');
const SHOTS_DIR = path.join(__dirname, 'shots');

/** The pinned interpreter for the repo's example apps. */
const PYTHON =
  process.env.VISUAL_PYTHON ||
  'python3';

const VIEWPORT = { width: 1600, height: 900 };
const DEVICE_SCALE_FACTOR = 1;

/** The single pinned animation timestamp every shot is taken at (ms). */
const FROZEN_T = 20_000;

/** Fixed PRNG seed substituted for Math.random in the page. */
const RNG_SEED = 0x5CD7_0001;

const ALLOW_NETWORK = process.env.VISUAL_ALLOW_NETWORK === '1';

// ---------------------------------------------------------------- manifest

type ShotRecord = {
  file: string;
  shows: string;
  url: string;
  viewport: string;
  deviceScaleFactor: number;
  frozenAnimationTimestampMs: number | null;
  rngSeed: string;
  externalNetwork: 'blocked' | 'allowed';
  maskedSelectors: string[];
  maskPlaceholder: string | null;
  readinessSignal: string;
  consoleErrors: string[];
  sha256: string;
  bytes: number;
};

const manifest: ShotRecord[] = [];

/**
 * Local servers bind an OS-assigned port, which would make manifest.json and the
 * failure log differ run-to-run for a reason that has nothing to do with pixels.
 * Normalise it so those files are diffable too.
 */
function normPort(s: string): string {
  return s.replace(/127\.0\.0\.1:\d+/g, '127.0.0.1:<ephemeral>');
}

function record(r: Omit<ShotRecord, 'sha256' | 'bytes'>) {
  const abs = path.join(SHOTS_DIR, r.file);
  const buf = fs.readFileSync(abs);
  manifest.push({
    ...r,
    sha256: createHash('sha256').update(buf).digest('hex'),
    bytes: buf.length,
  });
  // eslint-disable-next-line no-console
  console.log(`  shot ${r.file}  ${buf.length} B  sha256:${createHash('sha256').update(buf).digest('hex').slice(0, 16)}…`);
}

// ---------------------------------------------------------------- helpers

async function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const srv = createServer();
    srv.once('error', reject);
    srv.listen(0, '127.0.0.1', () => {
      const p = (srv.address() as any).port as number;
      srv.close(() => resolve(p));
    });
  });
}

type Proc = { child: ChildProcess; log: string[] };

function spawnLogged(cmd: string, args: string[], cwd = REPO_ROOT): Proc {
  const child = spawn(cmd, args, { cwd, stdio: ['ignore', 'pipe', 'pipe'] });
  const log: string[] = [];
  child.stdout?.on('data', (d) => log.push(String(d)));
  child.stderr?.on('data', (d) => log.push(String(d)));
  return { child, log };
}

/** Poll until `url` answers with any HTTP status, or throw after timeoutMs. */
async function waitForHttp(url: string, timeoutMs: number, proc?: Proc): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let lastErr = '';
  while (Date.now() < deadline) {
    if (proc && proc.child.exitCode !== null) {
      throw new Error(
        `process exited with code ${proc.child.exitCode} before serving ${url}\n` +
          proc.log.join(''),
      );
    }
    try {
      const res = await fetch(url, { signal: AbortSignal.timeout(2000) });
      if (res.status) return;
    } catch (e) {
      lastErr = String(e);
    }
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error(`timed out waiting for ${url}: ${lastErr}`);
}

/**
 * Runs BEFORE any page script. Kills the two sources of non-determinism in
 * ulap-twin-ui: Math.random tower azimuths, and the rAF-timestamp animation clock.
 */
function determinismInitScript(seed: number) {
  return `(() => {
    // --- fixed-seed mulberry32 in place of Math.random ------------------------
    let __s = ${seed} >>> 0;
    Math.random = function () {
      __s = (__s + 0x6D2B79F5) >>> 0;
      let t = __s;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
    // --- pinnable animation clock -------------------------------------------
    window.__frozenT = null;
    const __raf = window.requestAnimationFrame.bind(window);
    window.requestAnimationFrame = function (cb) {
      return __raf(function (ts) { cb(window.__frozenT === null ? ts : window.__frozenT); });
    };
    // --- stoppable interval timers -------------------------------------------
    // app.js:486 flips #t-clock between "LIVE" and "● REC" on a forever
    // setInterval. Masking alone cannot beat it: the timer can fire between the
    // mask box being measured and the screenshot being taken, which changes the
    // element's width and leaks a character out from under the mask. Track every
    // interval so the harness can stop the page's clock outright before shooting.
    const __intervals = new Set();
    const __si = window.setInterval.bind(window);
    window.setInterval = function () {
      const id = __si.apply(null, arguments);
      __intervals.add(id);
      return id;
    };
    window.__stopTimers = function () {
      __intervals.forEach(function (id) { clearInterval(id); });
      __intervals.clear();
    };
  })();`;
}

/** Abort every non-loopback request so the run is hermetic. */
async function makeHermetic(page: Page) {
  if (ALLOW_NETWORK) return;
  await page.route('**/*', (route) => {
    const url = route.request().url();
    if (/^(data|blob|about):/.test(url)) return route.continue();
    let host = '';
    try {
      host = new URL(url).hostname;
    } catch {
      return route.continue();
    }
    if (host === '127.0.0.1' || host === 'localhost' || host === '::1' || host === '') {
      return route.continue();
    }
    return route.abort('blockedbyclient');
  });
}

function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push(m.text().slice(0, 300));
  });
  page.on('pageerror', (e) => errors.push(`pageerror: ${String(e).slice(0, 300)}`));
  return errors;
}

/**
 * Wait until the page's visible text stops changing — the observed equivalent of
 * "all the count-up animations and one-shot timers have finished". Text inside the
 * `exclude` selectors is ignored, because those are the readouts that never settle
 * by design (FPS counters, the LIVE/REC toggle driven by a forever setInterval).
 *
 * This is a real signal, not a sleep: it throws instead of silently continuing.
 */
async function waitForDomSettle(page: Page, exclude: string[], timeoutMs = 25_000) {
  const key = () =>
    page.evaluate((sels: string[]) => {
      const skip = new Set<Element>();
      for (const s of sels) document.querySelectorAll(s).forEach((e) => skip.add(e));
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      const out: string[] = [];
      for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        let p: Element | null = (n as Text).parentElement;
        let skipped = false;
        while (p) {
          if (skip.has(p)) { skipped = true; break; }
          p = p.parentElement;
        }
        if (!skipped) out.push((n.nodeValue || '').trim());
      }
      return out.join('');
    }, exclude);

  const deadline = Date.now() + timeoutMs;
  let last = await key();
  let stable = 0;
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 200));
    const now = await key();
    stable = now === last ? stable + 1 : 0;
    last = now;
    if (stable >= 3) return; // 3 x 200 ms unchanged
  }
  throw new Error('DOM text never settled — a readout is animating forever; add it to masks');
}

/** Pin the animation clock at FROZEN_T and let three frames flush through it. */
async function freezeClock(page: Page) {
  await page.evaluate((t) => {
    (window as any).__frozenT = t;
  }, FROZEN_T);
  await page.evaluate(
    () =>
      new Promise<void>((res) =>
        requestAnimationFrame(() =>
          requestAnimationFrame(() => requestAnimationFrame(() => res())),
        ),
      ),
  );
}

type ShotOpts = {
  file: string;
  shows: string;
  url: string;
  readiness: string;
  masks?: string[];
  frozen?: boolean;
  errors: string[];
};

/** Placeholder substituted for volatile readouts before they are masked. */
const MASK_PLACEHOLDER = '———';

/**
 * Readouts that can never be deterministic and are therefore masked.
 *   #t-fps / #s-fps  — frame-rate counters
 *   #t-clock         — app.js:486 flips this between "LIVE" and "● REC" on a
 *                      forever setInterval(2000), so its value depends purely on
 *                      how long the page has been open
 *   #badge-txt       — "Radio map computed in N ms" / "Paths computed in N ms"
 */
const TWO_D_VOLATILE = ['#t-fps', '#t-clock'];
const THREE_D_VOLATILE = ['#s-fps', '#badge-txt'];

async function shoot(page: Page, o: ShotOpts) {
  const maskSelectors = o.masks ?? [];

  // A mask box is sized to the element it covers, so masking alone is NOT enough:
  // "12.3 ms" and "123.4 ms" produce different-width boxes and therefore different
  // pixels. Replace the volatile text with a fixed-width placeholder first, THEN
  // paint the mask over it. Both steps are recorded in shots/manifest.json.
  if (maskSelectors.length) {
    await page.evaluate((sels: string[]) => {
      // 1. stop the page's own interval timers so nothing rewrites the text (and
      //    resizes the mask box) between here and the shutter
      (window as any).__stopTimers?.();
      // 2. substitute the fixed-width placeholder
      for (const s of sels) {
        document.querySelectorAll(s).forEach((el) => {
          const e = el as HTMLElement;
          e.textContent = '———';
          // 3. pin the box so even a stray write cannot change the masked area
          const r = e.getBoundingClientRect();
          e.style.display = 'inline-block';
          e.style.width = `${Math.round(r.width)}px`;
          e.style.overflow = 'hidden';
          e.style.whiteSpace = 'nowrap';
        });
      }
    }, maskSelectors);
  }

  const masks: Locator[] = maskSelectors.map((s) => page.locator(s));
  fs.mkdirSync(SHOTS_DIR, { recursive: true });
  await page.screenshot({
    path: path.join(SHOTS_DIR, o.file),
    fullPage: false,
    animations: 'disabled', // freeze CSS animations/transitions too
    caret: 'hide',
    scale: 'css',
    mask: masks,
    maskColor: '#2A2A2E',
  });
  record({
    file: o.file,
    shows: normPort(o.shows),
    url: normPort(o.url),
    viewport: `${VIEWPORT.width}x${VIEWPORT.height}`,
    deviceScaleFactor: DEVICE_SCALE_FACTOR,
    frozenAnimationTimestampMs: o.frozen === false ? null : FROZEN_T,
    rngSeed: `mulberry32:0x${RNG_SEED.toString(16)}`,
    externalNetwork: ALLOW_NETWORK ? 'allowed' : 'blocked',
    maskedSelectors: maskSelectors,
    maskPlaceholder: maskSelectors.length ? MASK_PLACEHOLDER : null,
    readinessSignal: o.readiness,
    consoleErrors: o.errors.map(normPort),
    sha256: '',
    bytes: 0,
  } as any);
}

// ---------------------------------------------------------------- servers

let twinServer: Proc | undefined;
let twinBase = '';
let staticServer: Proc | undefined;
let staticBase = '';

test.beforeAll(async () => {
  fs.mkdirSync(SHOTS_DIR, { recursive: true });

  // (1) the repo's OWN twin-viewer server — using the shipped app is the point
  const twinPort = await freePort();
  twinServer = spawnLogged(PYTHON, [
    'examples/apps/twin_viewer/serve.py',
    '--host', '127.0.0.1',
    '--port', String(twinPort),
    '--no-open',
  ]);
  twinBase = `http://127.0.0.1:${twinPort}`;
  await waitForHttp(`${twinBase}/index.html`, 30_000, twinServer);

  // (2) a stdlib static server rooted at the repo root, so the comparison page can
  //     reach blender/sionna_out/*.png by absolute path
  const staticPort = await freePort();
  staticServer = spawnLogged(PYTHON, [
    '-m', 'http.server', String(staticPort),
    '--bind', '127.0.0.1',
    '--directory', REPO_ROOT,
  ]);
  staticBase = `http://127.0.0.1:${staticPort}`;
  await waitForHttp(`${staticBase}/visual/pages/rt-compare.html`, 30_000, staticServer);
});

test.afterAll(async () => {
  twinServer?.child.kill('SIGTERM');
  staticServer?.child.kill('SIGTERM');
  // manifest is the machine-readable proof of what was captured and how
  manifest.sort((a, b) => a.file.localeCompare(b.file));
  fs.writeFileSync(
    path.join(SHOTS_DIR, 'manifest.json'),
    JSON.stringify(
      {
        note:
          'Regenerate with `bash visual/run.sh`. sha256 values are the determinism ' +
          'check: two runs on the same host must produce identical hashes.',
        viewport: `${VIEWPORT.width}x${VIEWPORT.height}`,
        deviceScaleFactor: DEVICE_SCALE_FACTOR,
        frozenAnimationTimestampMs: FROZEN_T,
        rngSeed: `mulberry32:0x${RNG_SEED.toString(16)}`,
        externalNetwork: ALLOW_NETWORK ? 'allowed' : 'blocked',
        shots: manifest,
      },
      null,
      2,
    ) + '\n',
  );
});

// ---------------------------------------------------------------- 1. twin viewer

test('twin viewer — 2-D operations map (index.html)', async ({ page }) => {
  const errors = collectConsoleErrors(page);
  await page.addInitScript(determinismInitScript(RNG_SEED));
  await makeHermetic(page);

  const url = `${twinBase}/index.html`;
  await page.goto(url, { waitUntil: 'load' });

  // readiness: data present -> fonts settled -> intro overlay gone from the DOM
  await page.waitForFunction(() => !!(window as any).TWIN_DATA, null, { timeout: 30_000 });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForFunction(() => !document.getElementById('intro'), null, { timeout: 30_000 });
  // the boot toast auto-hides at +2600 ms; wait it out so the shot never straddles it
  await page.waitForFunction(
    () => !document.getElementById('toast')?.classList.contains('show'),
    null,
    { timeout: 30_000 },
  );
  // #m-cov is an anime.js count-up; wait for every readout to stop moving
  await waitForDomSettle(page, TWO_D_VOLATILE);
  await freezeClock(page);

  await expect(page.locator('canvas#map')).toBeVisible();

  await shoot(page, {
    file: 'twin-viewer-2d-map.png',
    shows:
      'ulap-twin-ui/index.html — 2-D operations map: 576 LiDAR-height building ' +
      'footprints, 2 towers, analytical coverage rings, left control panel.',
    url,
    readiness:
      'window.TWIN_DATA set → document.fonts.ready → #intro removed → boot toast hidden ' +
      '→ DOM text settled (3 x 200 ms) → clock pinned',
    masks: TWO_D_VOLATILE,
    errors,
  });
});

// scene.html accepts #paths / #radio / #both — a deterministic, committed way to
// select the scene, so the three shots differ only in the layer under test.
for (const mode of ['radio', 'paths', 'both'] as const) {
  test(`twin viewer — 3-D scene (#${mode})`, async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await page.addInitScript(determinismInitScript(RNG_SEED));
    await makeHermetic(page);

    const url = `${twinBase}/scene.html#${mode}`;
    await page.goto(url, { waitUntil: 'load' });

    // readiness: loader element removed by boot() once the scene is built
    await page.waitForFunction(() => !document.getElementById('loader'), null, { timeout: 60_000 });
    await page.evaluate(() => document.fonts.ready);
    await waitForDomSettle(page, THREE_D_VOLATILE);
    await freezeClock(page);

    await expect(page.locator('canvas#gl')).toBeVisible();

    await shoot(page, {
      file: `twin-viewer-3d-${mode}.png`,
      shows:
        `ulap-twin-ui/scene.html#${mode} — three.js twin, camera fixed by the app's own ` +
        `focusTx() (tower 0, no user interaction, so it is identical every run). ` +
        (mode === 'radio'
          ? 'Path-gain radio map draped on the ground plane.'
          : mode === 'paths'
            ? '440 traced ray paths from the TX.'
            : 'Radio map + traced ray paths together.'),
      url,
      readiness:
        '#loader removed by boot() → document.fonts.ready → DOM text settled (3 x 200 ms) ' +
        '→ clock pinned',
      masks: THREE_D_VOLATILE,
      errors,
    });
  });
}

// ---------------------------------------------------------------- 2. RT side-by-side

for (const [c, label] of [
  ['fidelity', 'terrain drape vs ground-following at 1.5 m AGL (3.5 GHz)'],
  ['band', 'sub-6 frequency sweep vs mmWave 28/60 GHz'],
] as const) {
  test(`RT outputs side-by-side — ${c}`, async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await page.addInitScript(determinismInitScript(RNG_SEED));
    await makeHermetic(page);

    const url = `${staticBase}/visual/pages/rt-compare.html?c=${c}`;
    await page.goto(url, { waitUntil: 'load' });

    // explicit readiness signal set once BOTH images have loaded or errored
    await page.waitForFunction(() => (window as any).__RT_COMPARE_READY__ === true, null, {
      timeout: 60_000,
    });
    await page.evaluate(() => document.fonts.ready);
    await page.evaluate(async () => {
      await Promise.all(
        Array.from(document.images).map((i) => (i.decode ? i.decode().catch(() => {}) : null)),
      );
    });

    // both panels must actually be showing a bitmap, not the failure card
    const broken = await page.evaluate(() =>
      Array.from(document.querySelectorAll('.missing')).map((e) => e.textContent),
    );
    expect(broken, `RT source PNG missing: ${JSON.stringify(broken)}`).toHaveLength(0);

    await shoot(page, {
      file: `rt-compare-${c}.png`,
      shows: `visual/pages/rt-compare.html?c=${c} — ${label}. Both panels in an identical 660x545 box, object-fit: contain (no crop, no stretch).`,
      url,
      readiness: 'window.__RT_COMPARE_READY__ === true (both <img> load/error) → images decoded',
      frozen: false,
      errors,
    });
  });
}

// ------------------------------------------- 3. coverage-map defects F8 / F9 / F10
//
// Before/after visual evidence for the three defects fixed in the coverage stages
// and written up in
//   docs/audits/2026-07-29-f8-f9-receiver-plane-and-colour-scale.md
//
// Every number on these pages is fetched by the page itself, live, from
// comparison/results/f8.json over loopback, and the JSON pointer is printed next
// to it — so the screenshot carries its own provenance. Nothing is hard-coded into
// the HTML except axis furniture and the colourbar crop geometry (which is a
// measurement of the committed PNGs; method in visual/README.md).
//
// These pages are deliberately inert: no setInterval, no requestAnimationFrame, no
// Math.random, no wall-clock, no webfont. They set window.__PAGE_READY__ once the
// fetch has resolved AND the DOM has been written, and window.__PAGE_FAILURES__ to
// the number of resources that failed — which the spec asserts, so a page that
// silently rendered "unavailable" cannot pass as evidence.

const DEFECT_PAGES = [
  {
    page: 'paper-figures-before-after.html',
    file: 'paper-figures-before-after.png',
    shows:
      'PAPER FIGURES, BEFORE/AFTER — the two coverage figures the paper compares, old ' +
      'committed render beside the regenerated one at the released defaults (K=57 ceiling ' +
      'stack, one shared −160…−80 dB scale, one 8 m grid, 1e8 samples/tx). Old ground-following ' +
      'was 28.1 % dark, most of it receiver-underground artefact plus starvation; new states ' +
      'its 1.16 % unsampled fraction in its own title. Old images load from ' +
      'blender/sionna_out (unmodified committed files); new from pages/figassets. Numbers: ' +
      'docs/audits/2026-07-30 and comparison/results/f8.json.',
  },
  {
    page: 'defect-f8-receiver-plane.html',
    file: 'defect-f8-receiver-plane.png',
    shows:
      'DEFECT F8 — the receiver-plane selection rule, drawn over one plane interval from ' +
      'the real spacing and receiver height, beside the before/after measurements on the ' +
      '91,745-cell grid. Shows why "nearest" puts the receiver below local ground in ' +
      '28.97 % of cells and why "ceiling" cannot. The interval picture makes a prediction ' +
      'the page checks against the measurement: (spacing/2 − rx_agl) / spacing = 28.39 % ' +
      'vs 28.97 % measured. The diagram is a picture of the RULE, not of the Newton DTM — ' +
      'f8.json carries the relief but no height profile, so no terrain profile is drawn. ' +
      'Numbers: comparison/results/f8.json, fetched live at capture time with the JSON ' +
      'pointer printed per row and the file’s generated_utc stamped in the footer; ' +
      'narrative: docs/audits/2026-07-29-… § F8.',
  },
  {
    page: 'defect-f9-colour-scale.html',
    file: 'defect-f9-colour-scale.png',
    shows:
      'DEFECT F9 — the two published coverage figures on independent colour scales. The ' +
      'colourbar rectangle occupies identical pixel rows (92–1051) in both committed PNGs, ' +
      'so the defect is visible without touching a pixel: left, the two colourbars cropped ' +
      'straight out of the PNGs at their published position (same ramp, disagreeing dB ' +
      'labels); right, the same crops with B shifted up 34 source px so the dB axes align ' +
      '(labels agree, ramps offset). 34 px ÷ 12 px/dB = 2.83 dB. Crops are CSS windows onto ' +
      'the unmodified files — nothing recoloured, resampled or re-rendered. Context numbers ' +
      'from comparison/results/f8.json; shared scale (−160…−80, 5 dB grid) from the audit § F9.',
  },
  {
    page: 'defect-f10-sampling.html',
    file: 'defect-f10-sampling.png',
    shows:
      'DEFECT F10 — sample convergence. No-coverage fraction against rays per transmitter ' +
      '(log–log, four measured points, nothing interpolated) plus the attribution of the ' +
      'extra shadow at each level. Blank map area falls ~10x per decade of samples with no ' +
      'floor until 1e8–1e9, so a cell that fills in when you fire more rays was unsampled, ' +
      'not shadowed. Data: comparison/results/f8.json ‣ sample_convergence.by_samples_per_tx ' +
      '(all four rows), fetched live at capture time and stamped with the file’s ' +
      'generated_utc. The stage default is READ from stage_cost.K57_default.stdout_tail, not ' +
      'assumed, and the page compares it against the default named in the audit’s F10 ' +
      'table — so if the stage default moves after the audit is written, the shot says so.',
  },
] as const;

for (const d of DEFECT_PAGES) {
  test(`coverage defect — ${d.page}`, async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await page.addInitScript(determinismInitScript(RNG_SEED));
    await makeHermetic(page);

    const url = `${staticBase}/visual/pages/${d.page}`;
    await page.goto(url, { waitUntil: 'load' });

    // explicit readiness: the page's own fetch has resolved AND the DOM is written
    await page.waitForFunction(() => (window as any).__PAGE_READY__ === true, null, {
      timeout: 60_000,
    });
    await page.evaluate(() => document.fonts.ready);
    await page.evaluate(async () => {
      await Promise.all(
        Array.from(document.images).map((i) => (i.decode ? i.decode().catch(() => {}) : null)),
      );
    });
    await waitForDomSettle(page, []);

    // A page that failed to fetch its data still renders — it just renders
    // "unavailable". Assert the fetch worked, so a broken shot cannot pass as
    // evidence, and name what failed if it did.
    const failures = await page.evaluate(() => (window as any).__PAGE_FAILURES__);
    const visibleFailures = await page.evaluate(() =>
      Array.from(document.querySelectorAll('.fail, .missing')).map((e) =>
        (e.textContent || '').trim().slice(0, 200),
      ),
    );
    expect(
      { failures, visibleFailures },
      `${d.page} could not load its sources`,
    ).toEqual({ failures: 0, visibleFailures: [] });

    await shoot(page, {
      file: d.file,
      shows: d.shows,
      url,
      readiness:
        'window.__PAGE_READY__ === true (fetch of comparison/results/f8.json resolved and ' +
        'the DOM written) → document.fonts.ready → images decoded → DOM text settled ' +
        '(3 x 200 ms) → window.__PAGE_FAILURES__ asserted 0',
      frozen: false,
      errors,
    });
  });
}

// ---------------------------------------------------------------- 4. failure cases

test('FAILURE — Streamlit coverage explorer cannot start', async ({ page }) => {
  const errors = collectConsoleErrors(page);
  const port = await freePort();

  // Attempt the documented launch, for real, with the pinned interpreter.
  const proc = spawnLogged(PYTHON, [
    '-m', 'streamlit', 'run',
    'examples/apps/coverage_explorer/app.py',
    '--server.port', String(port),
    '--server.address', '127.0.0.1',
    '--server.headless', 'true',
  ]);

  let started = true;
  try {
    await waitForHttp(`http://127.0.0.1:${port}/`, 25_000, proc);
  } catch {
    started = false;
  }

  const log = proc.log.join('').trim();
  fs.mkdirSync(SHOTS_DIR, { recursive: true });
  fs.writeFileSync(
    path.join(SHOTS_DIR, 'failure-coverage-explorer.log'),
    `$ ${PYTHON} -m streamlit run examples/apps/coverage_explorer/app.py --server.port <ephemeral>\n` +
      `exit code: ${proc.child.exitCode}\n\n${log.replace(new RegExp(String(port), 'g'), '<ephemeral>')}\n`,
  );

  await makeHermetic(page);
  const url = `http://127.0.0.1:${port}/`;
  // Navigate anyway. If the app is down this renders Chromium's real error page —
  // that IS the failure state, captured at the same viewport as every other shot.
  await page.goto(url, { waitUntil: 'load' }).catch(() => {});

  // A FAILED navigation rejects goto() while Chromium is still committing its own
  // error page, and screenshotting into that window intermittently dies with
  //   Protocol error (Page.captureScreenshot): Unable to capture screenshot
  // (observed roughly 1 run in 4, which is exactly the rate that makes a two-run
  // determinism check useless). The pixels were never wrong — the shutter simply
  // fired before the compositor had a frame. Wait for a settled document and for
  // two rAF ticks, i.e. for a frame to actually exist, before shooting.
  await page
    .waitForFunction(() => document.readyState === 'complete', null, { timeout: 15_000 })
    .catch(() => {});
  await page
    .evaluate(
      () =>
        new Promise<void>((res) =>
          requestAnimationFrame(() => requestAnimationFrame(() => res())),
        ),
    )
    .catch(() => {});

  await shoot(page, {
    file: 'failure-coverage-explorer.png',
    shows: started
      ? `Streamlit coverage explorer DID start on this host at ${url} (the recorded ` +
        `failure no longer reproduces — update visual/README.md).`
      : `FAILURE CASE — examples/apps/coverage_explorer/app.py could not be launched with ` +
        `${PYTHON} (streamlit is not installed in that venv; installing it was out of scope). ` +
        `Chromium's real connection-refused page at the same 1600x900 viewport. ` +
        `Exact interpreter output: shots/failure-coverage-explorer.log`,
    url,
    readiness:
      'launch attempt completed (exit code observed) → navigation settled → ' +
      'document.readyState complete → 2 rAF ticks (a frame exists to capture)',
    frozen: false,
    errors,
  });

  proc.child.kill('SIGTERM');
});

test('FAILURE — twin viewer with its scene data unreachable', async ({ page }) => {
  const errors = collectConsoleErrors(page);
  await page.addInitScript(determinismInitScript(RNG_SEED));
  await makeHermetic(page);

  // Deliberate, reproducible fault injection: data.js never arrives.
  // This is the "the viewer failed to render" state, captured rather than hidden.
  await page.route('**/data.js', (r) => r.abort('failed'));

  const url = `${twinBase}/index.html`;
  await page.goto(url, { waitUntil: 'load' }).catch(() => {});
  // The app throws on `D.buildings`; wait for the failsafe that strips the intro,
  // so the broken state — not the splash — is what gets photographed.
  await page
    .waitForFunction(() => !document.getElementById('intro'), null, { timeout: 15_000 })
    .catch(() => {});
  await freezeClock(page).catch(() => {});

  // Assert the *specific* fault, not merely "some error happened" — the blocked
  // webfont would satisfy a bare non-empty check.
  expect(
    errors.filter((e) => e.startsWith('pageerror:')),
    `expected a page error from the missing scene data, got: ${JSON.stringify(errors)}`,
  ).not.toHaveLength(0);

  await shoot(page, {
    file: 'failure-twin-viewer-no-data.png',
    shows:
      'FAILURE CASE — ulap-twin-ui/index.html with data.js aborted by the harness ' +
      '(route interception; nothing in the repo was modified). Shows what the viewer ' +
      'actually renders when the scene payload is missing, at the same 1600x900 viewport.',
    url,
    readiness:
      '#intro removed by the page failsafe → clock pinned (a pageerror is asserted, ' +
      'so this shot cannot silently become a success)',
    masks: TWO_D_VOLATILE,
    errors,
  });
});

test('FAILURE — the F9 shared-scale rendering does not exist to photograph', async ({ page }) => {
  const errors = collectConsoleErrors(page);
  await page.addInitScript(determinismInitScript(RNG_SEED));
  await makeHermetic(page);

  // The "after" half of F9 is a picture that does not exist: the fix landed in the
  // stages, the committed renders predate it, and this harness does not run the RT
  // stages. Rather than omit the gap, photograph the proof of absence at the same
  // settings as everything else: the page fetches the LIVE directory listing of
  // blender/sionna_out/ and quotes the audit's F9 section verbatim.
  const url = `${staticBase}/visual/pages/f9-shared-scale-absent.html`;
  await page.goto(url, { waitUntil: 'load' });

  await page.waitForFunction(() => (window as any).__PAGE_READY__ === true, null, {
    timeout: 60_000,
  });
  await page.evaluate(() => document.fonts.ready);
  await waitForDomSettle(page, []);

  // The page must have really fetched both sources — otherwise it is asserting the
  // absence instead of demonstrating it, which is the thing this shot exists to avoid.
  const failures = await page.evaluate(() => (window as any).__PAGE_FAILURES__);
  expect(failures, 'the absence page could not fetch the listing and/or the audit').toBe(0);

  // And the listing must genuinely contain the two published figures and no
  // shared-scale variant. If a shared-scale render ever lands, this assertion fails
  // loudly and the failure case is retired — it cannot silently stay "true".
  const names = await page.evaluate(() =>
    Array.from(document.querySelectorAll('ul.ls li span:nth-child(2)')).map(
      (e) => (e.textContent || '').trim(),
    ),
  );
  expect(names).toContain('coverage_pathgain_db_terrain.png');
  expect(names).toContain('coverage_pathgain_db_terrain_groundfollow.png');
  expect(
    names.filter((n) => /shared|common|joint/i.test(n) && /\.png$/i.test(n)),
    'a shared-scale render now exists — retire this failure case and photograph it',
  ).toHaveLength(0);

  await shoot(page, {
    file: 'failure-f9-shared-scale-absent.png',
    shows:
      'FAILURE CASE — the F9 "after" state cannot be photographed. No shared-scale ' +
      'rendering of the two coverage figures exists in blender/sionna_out/; the fix landed ' +
      'in sionna_coverage.py / sionna_terrain_ground.py and the committed renders predate ' +
      'it. This harness photographs what the stages committed and does not run them, so the ' +
      'after panel is a gap in this evidence set — recorded here at the same 1600x900 ' +
      'settings rather than omitted. The page proves the absence rather than asserting it: ' +
      'it prints the LIVE directory listing of /blender/sionna_out/ (all entries, unfiltered) ' +
      'and quotes docs/audits/2026-07-29-… § F9 verbatim, both fetched at capture time.',
    url,
    readiness:
      'window.__PAGE_READY__ === true (directory listing and audit both fetched) → ' +
      'document.fonts.ready → DOM text settled (3 x 200 ms) → __PAGE_FAILURES__ asserted 0 ' +
      'and the listing asserted to contain the two published figures and no shared-scale variant',
    frozen: false,
    errors,
  });
});
