#!/usr/bin/env bash
# Build and render the Amini-branded HTML figures in this directory.
#
#   ./render.sh                  every *.src.html here
#   ./render.sh privacy-tiers
#
# For each <name>.src.html it produces:
#   <name>.html        self-contained (fonts + wordmark inlined as data URIs)
#   <name>.png         dark  — brand default, for web and decks
#   <name>-light.png   light — for print, papers and light slides
#
# Edit the .src.html only. <name>.html is generated and overwritten.
#
# Needs node and a local Chrome. Fonts are vendored in ./fonts (Geist, OFL).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGO="${FIG_LOGO_DIR:-$HERE/../brand/logo}"

CHROME="${CHROME_PATH:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
[ -x "$CHROME" ] || { echo "Chrome not found. Set CHROME_PATH=/path/to/chrome"; exit 1; }

targets=()
if [ $# -gt 0 ]; then targets=("$@"); else
  for f in "$HERE"/*.src.html; do targets+=("$(basename "$f" .src.html)"); done
fi

BUILD="$(mktemp)"; SHOT="$(mktemp)"; trap 'rm -f "$BUILD" "$SHOT"' EXIT

cat > "$BUILD" <<'PYEOF'
import base64, pathlib, sys
here, logo, name = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), sys.argv[3]

def b64(p, mime):
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()

faces = f"""<style>
@font-face{{font-family:"Geist";src:url("{b64(here/'fonts'/'Geist-Variable.woff2','font/woff2')}") format("woff2");font-weight:100 900;font-display:block}}
@font-face{{font-family:"Geist Mono";src:url("{b64(here/'fonts'/'GeistMono-Variable.woff2','font/woff2')}") format("woff2");font-weight:100 900;font-display:block}}
</style>"""

html = (here / f"{name}.src.html").read_text()
html = html.replace("</head>", faces + "\n</head>", 1)
html = html.replace("WORDMARK_BLACK", b64(logo / "wordmark-black.svg", "image/svg+xml"))
html = html.replace("WORDMARK_WHITE", b64(logo / "wordmark-white.svg", "image/svg+xml"))
(here / f"{name}.html").write_text(html)
print(f"  built {name}.html")
PYEOF

cat > "$SHOT" <<'JSEOF'
// Args arrive via env so no path is interpolated into a shell command line.
const puppeteer = require('puppeteer-core');
const path = require('path');
(async () => {
  const { FIG_CHROME, FIG_FILE, FIG_OUT_DARK, FIG_OUT_LIGHT } = process.env;
  const browser = await puppeteer.launch({
    executablePath: FIG_CHROME,
    args: ['--font-render-hinting=none'],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1120, height: 900, deviceScaleFactor: 2 });
  for (const [theme, out] of [['dark', FIG_OUT_DARK], ['light', FIG_OUT_LIGHT]]) {
    await page.goto('file://' + path.resolve(FIG_FILE) + '?theme=' + theme, { waitUntil: 'networkidle0' });
    await page.evaluate(() => document.fonts.ready);
    await (await page.$('body')).screenshot({ path: out });
    console.log('  ' + path.basename(out));
  }
  await browser.close();
})();
JSEOF

# puppeteer-core is cached outside the repo so nothing is vendored into git and
# repeat runs are instant. npx alone can't be used here: it puts the package in
# a temp tree that a script living elsewhere cannot resolve against.
DEPS="${FIG_DEPS_DIR:-$HOME/.cache/amini-figures}"
if [ ! -d "$DEPS/node_modules/puppeteer-core" ]; then
  echo "installing puppeteer-core into $DEPS (one time)"
  mkdir -p "$DEPS"
  npm install --silent --no-save --no-audit --no-fund --prefix "$DEPS" puppeteer-core@23
fi

for name in "${targets[@]}"; do
  echo "rendering ${name}"
  python3 "$BUILD" "$HERE" "$LOGO" "$name"
  NODE_PATH="$DEPS/node_modules" \
  FIG_CHROME="$CHROME" \
  FIG_FILE="$HERE/${name}.html" \
  FIG_OUT_DARK="$HERE/${name}.png" \
  FIG_OUT_LIGHT="$HERE/${name}-light.png" \
    node "$SHOT"
done

echo "done -> $HERE"
