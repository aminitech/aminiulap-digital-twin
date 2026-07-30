import { defineConfig } from '@playwright/test';

/**
 * Visual-evidence capture config.
 *
 * Everything that affects a pixel is pinned here so a third party regenerates
 * byte-identical PNGs:
 *   - viewport            1600 x 900 (never resized by a test)
 *   - deviceScaleFactor   1
 *   - colour scheme       dark, reduced motion, forced en-US / UTC
 *   - browser             the cached Playwright chromium on this box
 *                         (there is NO Chrome for ARM64 - see visual/README.md)
 *   - workers             1, retries 0  (a retried shot is a different shot)
 *
 * Override the browser with VISUAL_CHROMIUM=/path/to/chrome.
 */
const CHROMIUM =
  process.env.VISUAL_CHROMIUM ||
  '/home/$USER/.cache/ms-playwright/chromium-1232/chrome-linux/chrome';

export const VIEWPORT = { width: 1600, height: 900 } as const;
export const DEVICE_SCALE_FACTOR = 1;

export default defineConfig({
  testDir: __dirname,
  testMatch: /capture\.spec\.ts$/,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 180_000,
  expect: { timeout: 30_000 },
  reporter: [['list']],
  use: {
    browserName: 'chromium',
    viewport: { ...VIEWPORT },
    deviceScaleFactor: DEVICE_SCALE_FACTOR,
    colorScheme: 'dark',
    locale: 'en-US',
    timezoneId: 'UTC',
    // self-signed tailnet certs, if a URL is ever pointed at one
    ignoreHTTPSErrors: true,
    // no video/trace: they are not the evidence and they are not deterministic
    trace: 'off',
    video: 'off',
    screenshot: 'off',
    launchOptions: {
      executablePath: CHROMIUM,
      args: [
        '--no-sandbox',
        '--disable-dev-shm-usage',
        '--ignore-certificate-errors',
        // deterministic text rasterisation
        '--font-render-hinting=none',
        '--disable-lcd-text',
        // software WebGL: this box is aarch64 headless, there is no GPU path
        '--use-gl=angle',
        '--use-angle=swiftshader',
        '--enable-unsafe-swiftshader',
        // kill sources of frame-to-frame variation
        '--disable-features=PaintHolding,BackForwardCache',
        '--force-color-profile=srgb',
        '--force-device-scale-factor=1',
        '--hide-scrollbars',
      ],
    },
  },
});
