#!/usr/bin/env bash
# One command to reproduce the benchmark on any machine, including a Raspberry Pi.
#
#   bash benchmarks/run.sh                     # auto-detect backends, 3 repeats
#   bash benchmarks/run.sh --backends cpu      # CPU only (no GPU present)
#   bash benchmarks/run.sh --repeats 1         # quick feasibility check
#   PYTHON=./venv/bin/python bash benchmarks/run.sh
#
# It prepares the work dir, checks the prerequisites that would otherwise fail
# silently, runs the matrix, and regenerates the tables. Rules: benchmarks/METHOD.md
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
WORK="${ULAP_WORK_DIR:-${TMPDIR:-/tmp}/ulap-bench-work}"
REPEATS=3; BACKENDS=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repeats)  REPEATS="$2"; shift 2 ;;
    --backends) BACKENDS="$2"; shift 2 ;;
    --work-dir) WORK="$2"; shift 2 ;;
    -h|--help)  sed -n '2,14p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

fail () { echo "  ✗ $*" >&2; exit 1; }
ok   () { echo "  ✓ $*"; }

echo "── prerequisites ─────────────────────────────────────────"
command -v "$PYTHON" >/dev/null || fail "no interpreter at '$PYTHON' (set PYTHON=...)"
ok "interpreter: $($PYTHON -c 'import sys;print(sys.executable)')"

"$PYTHON" - <<'PY' || exit 1
import sys
try:
    import sionna.rt as rt, mitsuba as mi
except Exception as e:
    sys.exit(f"  ✗ sionna-rt not importable: {e}\n"
             f"    pip install -r benchmarks/requirements.txt")
print(f"  ✓ sionna-rt {rt.__version__}, mitsuba {mi.__version__}")
print(f"  ✓ llvm (CPU) variant available: {any(v.startswith('llvm') for v in mi.variants())}")
print(f"  ✓ cuda (GPU) variant available: {any(v.startswith('cuda') for v in mi.variants())}")
PY

# GNU time is required: without it the harness records zeros rather than failing.
if /usr/bin/time -f "%e" true >/dev/null 2>&1; then ok "GNU time present"
else fail "GNU /usr/bin/time missing — CPU%% and peak RSS would be recorded as zero.
    Debian/Ubuntu/Raspberry Pi OS:  sudo apt install time
    Rocky/RHEL/Fedora:              sudo dnf install time"; fi

echo
echo "── work dir ──────────────────────────────────────────────"
mkdir -p "$WORK/sionna_out"

# Two possible scenes, and which one you get changes what the numbers MEAN.
#
# The Barbados pilot scene under blender/ is derived from licence-restricted government
# data and is NOT in the public tree. When it is present (a working checkout that has run
# the pipeline, or one with the restricted data) the benchmark reproduces the published
# figures. When it is absent, we fall back to the committed open-data scene so a fresh
# clone can still run the harness end to end -- but those timings are for a DIFFERENT
# scene and must never be quoted against the paper's tables.
OPEN_SCENE="$REPO/examples/data/open_scene_mitsuba"
if [[ -d "$REPO/blender/mitsuba_scene" && -d "$REPO/blender/scene_build" ]]; then
  for d in scene_build mitsuba_scene mitsuba_scene_terrain; do
    [[ -d "$REPO/blender/$d" ]] || fail "missing $REPO/blender/$d — partial checkout?"
    cp -r "$REPO/blender/$d" "$WORK/" 2>/dev/null
  done
  SCENE_KIND="barbados-pilot"
  ok "prepared $WORK from the Barbados pilot scene (no Blender needed: it is pre-exported)"
elif [[ -d "$OPEN_SCENE" ]]; then
  OPEN_MANIFEST="$REPO/examples/data/newton-open_scene_manifest.json"
  [[ -f "$OPEN_MANIFEST" ]] || fail "open scene present but its manifest is missing: $OPEN_MANIFEST"
  mkdir -p "$WORK/mitsuba_scene" "$WORK/mitsuba_scene_terrain" "$WORK/scene_build"
  cp -r "$OPEN_SCENE"/scene.xml "$OPEN_SCENE"/meshes "$WORK/mitsuba_scene/" 2>/dev/null
  # the terrain variant IS the default export; the flat/ subdir is the z=0 control
  if [[ -d "$OPEN_SCENE/flat" ]]; then
    cp -r "$OPEN_SCENE"/flat/scene.xml "$OPEN_SCENE"/flat/meshes "$WORK/mitsuba_scene/" 2>/dev/null
    cp -r "$OPEN_SCENE"/scene.xml "$OPEN_SCENE"/meshes "$WORK/mitsuba_scene_terrain/" 2>/dev/null
  else
    cp -r "$OPEN_SCENE"/scene.xml "$OPEN_SCENE"/meshes "$WORK/mitsuba_scene_terrain/" 2>/dev/null
  fi
  # The stages also read scene_build/ for footprints, terrain and the tower list. The open
  # manifest carries the same keys as the pilot one, so it is a drop-in.
  cp "$OPEN_MANIFEST" "$WORK/scene_build/scene_manifest.json"
  "$PYTHON" - "$OPEN_MANIFEST" "$WORK/scene_build/towers_near.json" <<'PYEOF'
import json, sys
m = json.load(open(sys.argv[1]))
json.dump(m.get("antennas", []), open(sys.argv[2], "w"), indent=1)
PYEOF
  SCENE_KIND="open-data"
  ok "prepared $WORK from the OPEN-DATA scene ($OPEN_SCENE)"
  echo "     ! The Barbados pilot scene is not in this checkout, so these timings are for a"
  echo "       different scene: 585 OpenStreetMap buildings with defaulted heights and ~31 m"
  echo "       terrain posting. Do NOT quote them against the paper's tables."
  echo "       See docs/OPEN-DATA-SCENE.md."
else
  fail "no scene found. Expected either $REPO/blender/mitsuba_scene (restricted pilot data)
    or $OPEN_SCENE (shipped open-data scene). Is this a full checkout?"
fi

if [[ -z "$BACKENDS" ]]; then
  if "$PYTHON" -c "import mitsuba as mi,sys; sys.exit(0 if any(v.startswith('cuda') for v in mi.variants()) else 1)" 2>/dev/null \
     && command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
    BACKENDS="cpu,cuda"; else BACKENDS="cpu"; fi
fi
echo "  ✓ backends: $BACKENDS   repeats: $REPEATS"

echo
echo "── running matrix ────────────────────────────────────────"
# run_bench.py names its output <host>-<arch>.json. Re-running on a machine that already
# has a committed result would overwrite it, so write somewhere new by default and tell
# the user exactly what was produced. Set OUT= to choose the path yourself.
HOST="$(uname -n)"; ARCH="$(uname -m)"
DEFAULT_OUT="$REPO/benchmarks/results/${HOST}-${ARCH}.json"
OUT="${OUT:-}"
if [[ -z "$OUT" ]]; then
  if [[ -e "$DEFAULT_OUT" ]]; then
    OUT="$REPO/benchmarks/results/${HOST}-${ARCH}-local.json"
    echo "  ! $DEFAULT_OUT already exists (a committed result)."
    echo "    Writing to $(basename "$OUT") instead so nothing is overwritten."
    echo "    Set OUT=/path/to/file.json to choose your own."
  else
    OUT="$DEFAULT_OUT"
  fi
fi
"$PYTHON" "$REPO/benchmarks/run_bench.py" \
  --work-dir "$WORK" --python "$PYTHON" --out "$OUT" \
  --repeats "$REPEATS" --backends "$BACKENDS" || fail "benchmark run failed"

echo
echo "── tables ────────────────────────────────────────────────"
"$PYTHON" "$REPO/benchmarks/make_tables.py" && ok "regenerated benchmarks/tables/"
echo
echo "Scene used   : $SCENE_KIND"
echo "Results JSON : $REPO/benchmarks/results/"
echo "Tables       : $REPO/benchmarks/tables/results.md"
echo "Method/rules : $REPO/benchmarks/METHOD.md"
