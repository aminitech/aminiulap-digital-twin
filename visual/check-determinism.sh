#!/usr/bin/env bash
# Prove the shots are reproducible: capture N times and compare sha256 per file.
#
#   bash visual/check-determinism.sh        # 3 runs (default)
#   bash visual/check-determinism.sh 5      # 5 runs
#
# Two runs is not enough — the non-determinism this harness had to kill (an
# interval-driven LIVE/REC toggle, a variable-width "computed in N ms" badge)
# reproduced roughly one run in four. Three is the floor.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SHOTS="$HERE/shots"
RUNS="${1:-3}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

for i in $(seq 1 "$RUNS"); do
  echo "=== run $i / $RUNS ==="
  bash "$HERE/run.sh" >/dev/null
  ( cd "$SHOTS" && sha256sum ./*.png | sort ) > "$TMP/$i.sha"
done

echo
echo "=== sha256 comparison against run 1 (empty diffs == deterministic) ==="
fail=0
for i in $(seq 2 "$RUNS"); do
  if diff -u "$TMP/1.sha" "$TMP/$i.sha"; then
    echo "run $i: identical to run 1"
  else
    echo "run $i: DRIFT (see diff above)" >&2
    fail=1
  fi
done

if [ "$fail" -ne 0 ]; then
  echo "DRIFT: see visual/README.md § Determinism" >&2
  exit 1
fi
echo "OK: all shots byte-identical across $RUNS runs"
