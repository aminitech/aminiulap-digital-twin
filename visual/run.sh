#!/usr/bin/env bash
# Regenerate every screenshot in visual/shots/ from the committed spec.
#
#   bash visual/run.sh
#
# Env overrides:
#   VISUAL_CHROMIUM=/path/to/chrome   browser binary (default: cached PW chromium)
#   VISUAL_PYTHON=/path/to/python     interpreter for the repo's example apps
#   VISUAL_ALLOW_NETWORK=1            let the Google-Fonts webfont through
#                                     (shots will then differ from the committed ones)
#   PW_BIN=/path/to/playwright        explicit @playwright/test CLI
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"

# ---- locate a @playwright/test install -------------------------------------
# There is no npm install in this repo for the visual harness; we reuse whatever
# @playwright/test is already on the box (see visual/README.md § Requirements).
CANDIDATES=(
  "${PW_BIN:-}"
  "$HERE/node_modules/.bin/playwright"
  "$ROOT/node_modules/.bin/playwright"
  "/home/$USER/Ulap/wg3wi6-sutd/runnables/node_modules/.bin/playwright"
  "/home/$USER/Ulap/amini-cloud/web/node_modules/.bin/playwright"
)
PW=""
for c in "${CANDIDATES[@]}"; do
  [ -n "$c" ] && [ -x "$c" ] && { PW="$c"; break; }
done
if [ -z "$PW" ]; then
  cat >&2 <<'EOF'
error: no @playwright/test CLI found.

  Install it next to the spec:   cd visual && npm install
  or point at an existing one:   PW_BIN=/path/to/node_modules/.bin/playwright bash visual/run.sh

Do NOT run `npx playwright install chromium` on this aarch64 box unless you have
to — a cached chromium already exists, see visual/README.md.
EOF
  exit 2
fi

# @playwright/test resolves `import ... from '@playwright/test'` from the spec's
# directory; when the CLI lives in a sibling checkout, NODE_PATH bridges the gap.
PW_MODULES="$(cd "$(dirname "$PW")/.." && pwd)"
export NODE_PATH="${PW_MODULES}${NODE_PATH:+:$NODE_PATH}"

echo "playwright : $PW"
echo "chromium   : ${VISUAL_CHROMIUM:-/home/$USER/.cache/ms-playwright/chromium-1232/chrome-linux/chrome}"
echo "python     : ${VISUAL_PYTHON:-python3}"
echo "network    : $([ "${VISUAL_ALLOW_NETWORK:-0}" = 1 ] && echo allowed || echo blocked-except-loopback)"
echo

exec "$PW" test --config "$HERE/playwright.config.ts" "$@"
