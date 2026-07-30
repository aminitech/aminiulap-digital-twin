#!/usr/bin/env bash
# CPU-class scaling ladder for the deterministic RF pipeline.
#
# Emulates real CPU classes by core-count capping on ONE host (cgroup scope +
# taskset), so the paper's sovereignty claim carries a hardware ladder rather
# than a single anecdote:
#
#   2          "netbook class"                      (2 x Cortex-A725)
#   4          "single-board & entry laptop class"  (4 x Cortex-A725 — contrast: the REAL Pi 4 run)
#   4big:5-8   "4 big cores"                        (4 x Cortex-X925 — in-host silicon contrast)
#   8          "mainstream laptop/desktop class"    (5 x A725 + 3 x X925)
#   16         "workstation class"                  (10 x A725 + 6 x X925)
#   20         uncapped — this host's own class (server ARM)
#
# GB10 core layout (read back at run time, recorded in the JSON): cpus 0-4 and
# 10-14 are Cortex-A725 (max 2.81 GHz), cpus 5-9 and 15-19 are Cortex-X925
# (max 3.9 GHz). Plain-number classes pin cpus 0..N-1, so the 2- and 4-core
# classes land on LITTLE cores only — deliberately conservative for the
# small-machine classes. "name:cpulist" classes pin an explicit list.
#
# Measured unit per class (fixed, stated explicitly):
#   sionna_analysis.py            (spp=1e6 per map — unchanged since the Pi 4 run)
#   sionna_coverage.py flat       (samples_per_tx=1e8, 8 m cells — the CURRENT raised default)
# terrain_ground at 1e8 is deliberately excluded: too slow to ladder on the
# small classes, and the ladder needs one fixed stage set.
#
# Rules inherited from benchmarks/METHOD.md: 3 repeats, median + full spread,
# variant READ BACK per run (never assumed), failures published as failures.
#
#   MI_DEFAULT_VARIANT=llvm_ad_mono_polarized  CUDA_VISIBLE_DEVICES=""
#   PYTHON=<sionna interpreter> ULAP_WORK_DIR=<scene work dir> bash benchmarks/cpu_classes.sh
#
# The ladder can be run in slices (e.g. one class per invocation, to fit a
# session timeout): set RUNS_TSV to a persistent path and every invocation
# appends to it; the JSON written at the end of each invocation aggregates
# everything measured so far.
#
# The caps emulate CORE COUNT only. Every capped run still sees the GB10's
# caches, memory bandwidth and per-core IPC. That is core-count emulation,
# not silicon emulation — CPU-CLASSES.md carries the honest framing.
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"; export PYTHON
WORK="${ULAP_WORK_DIR:?set ULAP_WORK_DIR to a work dir containing mitsuba_scene/ + scene_build/}"
REPEATS="${REPEATS:-3}"
CLASSES="${CLASSES:-2 4 4big:5-8 8 16 20}"
OUT="${OUT:-$REPO/benchmarks/results/cpu-classes-$(uname -n).json}"
STAGES_DIR="$REPO/ulap-scope/ulap_scope/stages"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Accumulator: where per-run rows and failure logs persist across invocations.
RUNS_TSV="${RUNS_TSV:-$TMP/runs.tsv}"
KEEP_DIR="${RUNS_TSV%.tsv}-faillogs"
mkdir -p "$(dirname "$RUNS_TSV")" "$KEEP_DIR"
touch "$RUNS_TSV"

fail () { echo "  x $*" >&2; exit 1; }

command -v "$PYTHON" >/dev/null || fail "no interpreter at '$PYTHON'"
/usr/bin/time -f "%e" true >/dev/null 2>&1 || fail "GNU /usr/bin/time missing (apt install time)"
command -v taskset >/dev/null || fail "taskset missing"
[[ -d "$WORK/mitsuba_scene" && -d "$WORK/scene_build" ]] || fail "ULAP_WORK_DIR=$WORK lacks mitsuba_scene/ + scene_build/"
NPROC="$(nproc)"

# systemd-run --user scope gives a MemoryMax cgroup fence (8G = the Pi 4's RAM,
# so no capped class can quietly lean on memory a small machine would not have).
# Fall back to bare taskset if the user manager is unavailable.
SDR=(systemd-run --user --scope -q -p MemoryMax=8G --)
if ! "${SDR[@]}" true 2>/dev/null; then
  echo "  ! systemd-run --user unavailable; falling back to bare taskset (no MemoryMax fence)"
  SDR=()
fi

# The backend contract: CPU-only, LLVM variant, hard-enforced by the stages.
RUN_ENV=(env ULAP_WORK_DIR="$WORK" ULAP_PROJECT_ROOT="$REPO" MPLBACKEND=Agg
         DRJIT_NO_RTLD_DEEPBIND=1 CUDA_VISIBLE_DEVICES=""
         MI_DEFAULT_VARIANT=llvm_ad_mono_polarized)

echo "── host ──────────────────────────────────────────────────"
"$PYTHON" - <<'PY' || fail "sionna-rt not importable under \$PYTHON"
import sionna.rt as rt, mitsuba as mi, drjit, numpy, sys, platform
print(f"  {platform.node()} {platform.machine()}  python {sys.version.split()[0]}")
print(f"  sionna-rt {rt.__version__}  mitsuba {mi.__version__}  drjit {drjit.__version__}  numpy {numpy.__version__}")
PY
echo "  logical cores: $NPROC   classes: $CLASSES   repeats: $REPEATS"
echo

count_cpus () {  # "5-8" or "0,2,4-6" -> how many cpus that list names
  python3 - "$1" <<'PY'
import sys
s=set()
for part in sys.argv[1].split(','):
    a=part.split('-'); s.update(range(int(a[0]), int(a[-1])+1))
print(len(s))
PY
}

for CLS in $CLASSES; do
  if [[ "$CLS" == *:* ]]; then
    NAME="${CLS%%:*}"; CPUS="${CLS#*:}"; N="$(count_cpus "$CPUS")"
  else
    NAME="$CLS"; N="$CLS"; CPUS="0-$((N-1))"
  fi
  (( N <= NPROC )) || { echo "  ! skipping class $CLS (> $NPROC cores)"; continue; }
  CAP=("${SDR[@]}" taskset -c "$CPUS" "${RUN_ENV[@]}")

  # Rule 2 (METHOD.md): read the variant back from the interpreter UNDER THE
  # SAME capped env — sionna_analysis does not print its variant; the stage's
  # own hard-abort plus this probe together cover it.
  PROBED="$("${CAP[@]}" "$PYTHON" -c \
    "import os;os.environ.setdefault('DRJIT_NO_RTLD_DEEPBIND','1');import sionna.rt,mitsuba as mi;print('VARIANT',mi.variant())" \
    2>/dev/null | sed -n 's/^VARIANT //p')"
  # and confirm the cap actually bites:
  SEEN_CORES="$("${CAP[@]}" nproc)"
  echo "[class $NAME] taskset $CPUS  nproc-in-scope=$SEEN_CORES  probed variant: ${PROBED:-NONE}"
  [[ "$SEEN_CORES" == "$N" ]] || fail "cap did not bite: asked $N cores ($CPUS), scope sees $SEEN_CORES"

  for STAGE in analysis coverage_flat; do
    case "$STAGE" in
      analysis)      SCRIPT="$STAGES_DIR/sionna_analysis.py"; ARGS=() ;;
      coverage_flat) SCRIPT="$STAGES_DIR/sionna_coverage.py"; ARGS=(flat) ;;
    esac
    for R in $(seq 0 $((REPEATS-1))); do
      LOG="$TMP/${NAME}-${STAGE}-r${R}.log"
      START=$(date +%s.%N)
      "${CAP[@]}" /usr/bin/time -v "$PYTHON" "$SCRIPT" "${ARGS[@]}" >"$LOG" 2>&1
      RC=$?
      END=$(date +%s.%N)
      WALL=$(awk "BEGIN{printf \"%.2f\", $END-$START}")
      USERS=$(sed -n 's/.*User time (seconds): //p' "$LOG" | tail -1)
      SYSS=$(sed -n 's/.*System time (seconds): //p' "$LOG" | tail -1)
      RSSKB=$(sed -n 's/.*Maximum resident set size (kbytes): //p' "$LOG" | tail -1)
      # variant read back from the run's own stdout where the stage prints it
      VAR=$(sed -n 's/^mitsuba variant: //p' "$LOG" | tail -1)
      VSRC="stage-stdout"
      if [[ -z "$VAR" ]]; then VAR="$PROBED"; VSRC="probe"; fi
      printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$NAME" "$N" "$CPUS" "$STAGE" "$R" "$RC" "$WALL" "${USERS:-0}" "${SYSS:-0}" \
        "${RSSKB:-0}" "$VAR" "$VSRC" >> "$RUNS_TSV"
      STATUS=ok; [[ $RC -ne 0 ]] && { STATUS="FAIL rc=$RC"; cp "$LOG" "$KEEP_DIR/${NAME}-${STAGE}-r${R}.log"; }
      echo "  $NAME $STAGE r$R  wall ${WALL}s  user ${USERS:-?}s  rss $(( ${RSSKB:-0} / 1024 ))MB  ${VAR:-NONE}(${VSRC})  $STATUS"
    done
  done
done

# ── assemble JSON (medians + spread, host facts, failures kept) ─────────────
python3 - "$RUNS_TSV" "$OUT" "$KEEP_DIR" "$NPROC" <<'PY'
import json, os, platform, re, statistics, subprocess, sys
from pathlib import Path
tsv, out, keep_dir, nproc = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])

CLASS_LABELS = {
    "2":    "netbook class",
    "4":    "single-board & entry laptop class",
    "4big": "4 big cores (Cortex-X925) — in-host silicon contrast",
    "8":    "mainstream laptop/desktop class",
    "16":   "workstation class",
    "20":   "uncapped (server ARM — this host's own class)",
}

facts = {"host": platform.node(), "arch": platform.machine(),
         "kernel": platform.release(), "cores_logical": nproc}
try:
    txt = Path("/proc/cpuinfo").read_text()
    m = re.search(r"^(?:model name|CPU part)\s*:\s*(.+)$", txt, re.M)
    if m: facts["cpu"] = m.group(1).strip()
    facts["ram_gb"] = round(int(re.search(r"^MemTotal:\s+(\d+) kB",
        Path("/proc/meminfo").read_text(), re.M).group(1)) / 1048576, 1)
except Exception: pass
# per-cpu max frequency -> big/little topology, read back rather than asserted
topo = {}
try:
    for c in range(nproc):
        khz = int(Path(f"/sys/devices/system/cpu/cpu{c}/cpufreq/cpuinfo_max_freq").read_text())
        topo.setdefault(f"{khz/1e6:.2f} GHz", []).append(c)
    facts["cpu_topology_max_freq"] = {k: ",".join(map(str, v)) for k, v in topo.items()}
except Exception: pass
py = os.environ.get("PYTHON", "python3")
probe = subprocess.run([py, "-c",
    "import sionna.rt as r,mitsuba as m,drjit as d,numpy as n,sys;"
    "print(sys.version.split()[0],r.__version__,m.__version__,d.__version__,n.__version__)"],
    capture_output=True, text=True, env={**os.environ, "DRJIT_NO_RTLD_DEEPBIND": "1",
                                         "MPLBACKEND": "Agg"})
if probe.returncode == 0 and probe.stdout.split():
    v = probe.stdout.split()
    facts.update(python=v[0], sionna_rt=v[1], mitsuba=v[2], drjit=v[3], numpy=v[4])
facts["interpreter"] = py

rows = {}
for line in Path(tsv).read_text().splitlines():
    name, n, cpus, stage, rep, rc, wall, user, syss, rsskb, var, vsrc = line.split("\t")
    rows.setdefault((name, int(n), cpus, stage), []).append({
        "repeat": int(rep), "ok": rc == "0", "returncode": int(rc),
        "wall_s": float(wall), "user_s": float(user), "sys_s": float(syss),
        "cpu_pct": round((float(user)+float(syss))/float(wall)*100, 1) if float(wall) else None,
        "max_rss_mb": round(float(rsskb)/1024, 1),
        "variant": var or None, "variant_source": vsrc})

order = {k: i for i, k in enumerate(CLASS_LABELS)}
cells = []
for (name, n, cpus, stage), runs in sorted(rows.items(),
        key=lambda kv: (order.get(kv[0][0], 99), kv[0][3])):
    runs.sort(key=lambda r: r["repeat"])
    ok = [r["wall_s"] for r in runs if r["ok"]]
    cell = {"class": name, "label": CLASS_LABELS.get(name, f"{n}-core cap"),
            "cores": n, "cpulist": cpus, "capped": n < nproc or cpus != f"0-{nproc-1}",
            "stage": stage, "runs": runs}
    if ok:
        cell["wall_median_s"] = round(statistics.median(ok), 2)
        cell["wall_spread_s"] = [min(ok), max(ok)]
    fails = [r for r in runs if not r["ok"]]
    if fails:
        cell["failed_runs"] = len(fails)
        tails = []
        for f in fails:
            p = Path(keep_dir) / f"{name}-{stage}-r{f['repeat']}.log"
            if p.exists(): tails.append(p.read_text()[-1200:])
        cell["failure_tails"] = tails
    cells.append(cell)

doc = {
  "what": "CPU-class scaling ladder: core-count caps (cgroup scope + taskset, MemoryMax=8G) on one host",
  "settings": {"stage_set": ["sionna_analysis.py (spp=1e6 per map)",
                             "sionna_coverage.py flat (samples_per_tx=1e8, 8 m cells — current raised default)"],
               "backend": "llvm_ad_mono_polarized (CPU), CUDA_VISIBLE_DEVICES=''",
               "repeats_per_cell": max((len(c["runs"]) for c in cells), default=0),
               "memory_fence": "MemoryMax=8G (matches the Pi 4's RAM)",
               "core_pinning": "plain classes pin cpus 0..N-1 (little cores first on this host); 4big pins cpus 5-8 (Cortex-X925)"},
  "caveat": "Core-count emulation only: capped runs keep the GB10's caches, memory bandwidth and per-core IPC. Not silicon emulation.",
  "host_facts": facts,
  "cells": cells,
  "external_reference_rows": [
    {"class": "single-board (REAL silicon)", "host": "Raspberry Pi 4 Model B",
     "cpu": "4 x Cortex-A72 @ 1.8 GHz", "source": "benchmarks/RASPBERRY-PI-4.md",
     "note": "analysis 22.2 s directly comparable (same settings, single run); its coverage numbers predate the 1e7->1e8 sample raise"},
    {"class": "big x86 server (REAL silicon)", "host": "bgi-ran-01",
     "cpu": "Intel Xeon 6760P, 256 logical", "source": "benchmarks/results/bgi-ran-01-x86_64-sionna201.json",
     "note": "analysis medians directly comparable; its coverage_flat rows predate the 1e7->1e8 sample raise"}],
}
Path(out).write_text(json.dumps(doc, indent=2))
print(f"\nwrote {out}")
PY
