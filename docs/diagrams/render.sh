#!/usr/bin/env bash
# Render the Amini-branded diagrams from their Mermaid sources.
#
#   ./render.sh              render every .mmd in this directory
#   ./render.sh scdt-architecture
#
# Outputs land one level up in docs/ so the paths referenced by README.md and
# ARCHITECTURE.md stay stable:
#
#   <name>.svg / <name>.png              dark  (repo + docs default)
#   <name>-light.svg / <name>-light.png  light (paper, print, slides)
#
# Requires node. mermaid-cli is fetched on demand via npx; nothing to install.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$(cd "$HERE/.." && pwd)"
MMDC=(npx -y @mermaid-js/mermaid-cli@11)

# 2x scale keeps the PNGs legible when GitHub downsamples them.
SCALE=2
WIDTH=2200

render() {
  local name="$1" theme="$2" suffix="$3"
  echo "  ${name}${suffix}"
  "${MMDC[@]}" \
    --input "$HERE/${name}.mmd" \
    --output "$OUT/${name}${suffix}.svg" \
    --configFile "$HERE/theme-${theme}.json" \
    --backgroundColor transparent \
    --width "$WIDTH" --quiet
  "${MMDC[@]}" \
    --input "$HERE/${name}.mmd" \
    --output "$OUT/${name}${suffix}.png" \
    --configFile "$HERE/theme-${theme}.json" \
    --backgroundColor "$4" \
    --width "$WIDTH" --scale "$SCALE" --quiet
}

targets=()
if [ $# -gt 0 ]; then
  targets=("$@")
else
  for f in "$HERE"/*.mmd; do
    targets+=("$(basename "$f" .mmd)")
  done
fi

for name in "${targets[@]}"; do
  echo "rendering ${name}"
  render "$name" dark  ""       "#121212"
  render "$name" light "-light" "#FFFFFF"
done

echo "done -> $OUT"
