#!/usr/bin/env python3
"""
Benchmark the Sionna RT propagation stages across backends.

Turns the paper's "reproducible on commodity sovereign hardware" into numbers.
Rules are pre-registered in METHOD.md and are not negotiable after seeing results.

    python benchmarks/run_bench.py --work-dir /path/to/blender-copy --repeats 3
    python benchmarks/run_bench.py --backends cpu          # CPU-only host

Writes benchmarks/results/<host>-<arch>.json. Combine hosts with make_tables.py.
"""
from __future__ import annotations
import argparse, hashlib, json, os, platform, re, resource, shutil
import subprocess, sys, time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STAGES_DIR = REPO / "ulap-scope" / "ulap_scope" / "stages"

# (cell id, stage script, argv tail)
STAGES = [
    ("coverage_flat",    "sionna_coverage.py",       ["flat"]),
    ("coverage_terrain", "sionna_coverage.py",       ["terrain"]),
    ("analysis",         "sionna_analysis.py",       []),
    ("mmwave_sinr",      "sionna_mmwave_sinr.py",    []),
    ("terrain_ground",   "sionna_terrain_ground.py", []),
]

VARIANT_RE = re.compile(r"mitsuba variant:\s*(\S+)", re.I)

# `/usr/bin/time -v` appends ~23 lines of rusage to the child's stderr AFTER the command
# exits. Left in place it fills any tail slice completely, so a failed cell records a page
# of page-fault counters and none of the traceback - the only reason to keep stderr.
TIME_V_START = re.compile(r"^\t?Command being timed:", re.M)


def strip_time_report(stderr: str) -> str:
    """Drop the trailing GNU `time -v` block so the tail keeps the real error."""
    start = None
    for m in TIME_V_START.finditer(stderr):
        start = m.start()
    return stderr[:start].rstrip() if start is not None else stderr


# Read back from the interpreter UNDER TEST, not from the harness's own interpreter -
# --python may point somewhere else entirely, and then every version here would be a lie.
# The distribution is named `sionna-rt` but the importable module is `sionna.rt`;
# importing `sionna_rt` always fails, which is how a 1.2.2-vs-2.0.1 split between two
# hosts stayed invisible for a whole benchmark round.
_VERSION_PROBE = r"""
import json, sys
out = {"executable": sys.executable, "python": sys.version.split()[0]}
for mod, key in (("sionna.rt", "sionna_rt_version"),
                 ("mitsuba", "mitsuba_version"),
                 ("drjit", "drjit_version"),
                 ("numpy", "numpy_version"),
                 ("matplotlib", "matplotlib_version")):
    try:
        m = __import__(mod, fromlist=["__version__"])
        out[key] = getattr(m, "__version__", "?")
    except Exception as exc:
        out[key] = f"unavailable: {type(exc).__name__}"
print("FACTS " + json.dumps(out))
"""


def probe_versions(py: str) -> dict:
    env = dict(os.environ)
    env.setdefault("DRJIT_NO_RTLD_DEEPBIND", "1")
    env.setdefault("MPLBACKEND", "Agg")
    try:
        r = subprocess.run([py, "-c", _VERSION_PROBE], capture_output=True, text=True,
                           env=env, timeout=300)
        m = re.search(r"^FACTS (\{.*\})$", r.stdout or "", re.M)
        if m:
            return json.loads(m.group(1))
    except Exception:
        pass
    return {}


def host_facts(py: str | None = None) -> dict:
    """Everything a reader needs to know which machine produced these numbers."""
    facts = {
        "host": platform.node(),
        "arch": platform.machine(),
        "python": platform.python_version(),
        "cores_logical": os.cpu_count(),
    }
    try:  # CPU model — /proc/cpuinfo layout differs between arm64 and x86_64
        txt = Path("/proc/cpuinfo").read_text()
        for key in ("model name", "Model", "Hardware", "CPU part"):
            m = re.search(rf"^{key}\s*:\s*(.+)$", txt, re.M)
            if m:
                facts["cpu"] = m.group(1).strip()
                break
    except Exception:
        pass
    try:
        mem = Path("/proc/meminfo").read_text()
        m = re.search(r"^MemTotal:\s+(\d+) kB", mem, re.M)
        if m:
            facts["ram_gb"] = round(int(m.group(1)) / 1024 / 1024, 1)
    except Exception:
        pass
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,compute_cap", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=30)
        if out.returncode == 0 and out.stdout.strip():
            facts["gpu"] = out.stdout.strip().splitlines()[0].strip()
    except Exception:
        facts["gpu"] = None
    probed = probe_versions(py or sys.executable)
    if probed:
        facts["interpreter"] = probed.pop("executable", py)
        facts["python"] = probed.pop("python", facts["python"])
        facts.update(probed)
    else:
        facts["interpreter"] = py or sys.executable
    return facts


def md5(p: Path) -> str:
    h = hashlib.md5(usedforsecurity=False)  # content fingerprint, not a signature
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot(out_dir: Path) -> dict:
    if not out_dir.is_dir():
        return {}
    return {p.name: md5(p) for p in sorted(out_dir.iterdir()) if p.is_file()}


def run_cell(py: str, script: Path, argv: list[str], env: dict,
             work_dir: Path) -> dict:
    """One measured execution. Wall from the monotonic clock, CPU/RSS from rusage."""
    out_dir = work_dir / "sionna_out"
    out_dir.mkdir(parents=True, exist_ok=True)
    before = snapshot(out_dir)

    # /usr/bin/time -v gives a per-invocation peak RSS. getrusage(RUSAGE_CHILDREN)
    # would report a high-water mark across every child this process has ever
    # reaped, so it cannot answer "how much memory did THIS stage need".
    gnu_time = "/usr/bin/time" if Path("/usr/bin/time").exists() else None
    cmd = [py, str(script), *argv]
    if gnu_time:
        cmd = [gnu_time, "-v", *cmd]

    t0 = time.monotonic()
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=str(REPO))
    wall = time.monotonic() - t0

    stderr = proc.stderr or ""
    def _tv(label, cast=float, default=None):
        m = re.search(rf"{re.escape(label)}:\s*([0-9.:]+)", stderr)
        if not m:
            return default
        val = m.group(1)
        if ":" in val:  # h:mm:ss or m:ss elapsed format
            parts = [float(x) for x in val.split(":")]
            sec = 0.0
            for p in parts:
                sec = sec * 60 + p
            return sec
        try:
            return cast(val)
        except ValueError:
            return default

    user = _tv("User time (seconds)", default=0.0)
    sys_ = _tv("System time (seconds)", default=0.0)
    rss_kb = _tv("Maximum resident set size (kbytes)", default=0.0)
    max_rss_mb = round((rss_kb or 0) / 1024, 1)

    stdout = proc.stdout or ""
    vm = VARIANT_RE.search(stdout)
    after = snapshot(out_dir)
    produced = {k: v for k, v in after.items() if before.get(k) != v}

    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "wall_s": round(wall, 3),
        "user_s": round(user, 3),
        "sys_s": round(sys_, 3),
        "cpu_pct": round((user + sys_) / wall * 100, 1) if wall > 0 else None,
        "max_rss_mb": max_rss_mb,
        "variant": vm.group(1) if vm else None,
        "outputs": produced,
        "stderr_tail": strip_time_report(stderr)[-1600:] if proc.returncode != 0 else "",
    }



def probe_variant(py: str, env: dict) -> str | None:
    """Rule 2: three of the five stages never print their variant. Ask the
    interpreter directly, under the SAME env, rather than assuming."""
    code = ("import os;os.environ.setdefault('DRJIT_NO_RTLD_DEEPBIND','1');"
            "import sionna.rt, mitsuba as mi;print('VARIANT',mi.variant())")
    try:
        r = subprocess.run([py, "-c", code], capture_output=True, text=True,
                           env=env, timeout=300)
        m = re.search(r"VARIANT\s+(\S+)", r.stdout or "")
        return m.group(1) if m else None
    except Exception:
        return None

def backend_env(kind: str, work_dir: Path) -> dict:
    env = dict(os.environ)
    env["ULAP_WORK_DIR"] = str(work_dir)
    env["ULAP_PROJECT_ROOT"] = str(REPO)
    env["MPLBACKEND"] = "Agg"
    env["DRJIT_NO_RTLD_DEEPBIND"] = "1"
    if kind == "cpu":
        # Rule 2: force it, then verify from the run's own output.
        env["CUDA_VISIBLE_DEVICES"] = ""
        env["MI_DEFAULT_VARIANT"] = "llvm_ad_mono_polarized"
    else:
        env.pop("CUDA_VISIBLE_DEVICES", None)
        env.pop("MI_DEFAULT_VARIANT", None)
    return env


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-dir", required=True,
                    help="copy of blender/ containing scene_build + mitsuba_scene*")
    ap.add_argument("--python", default=sys.executable,
                    help="interpreter with sionna-rt installed")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--backends", default="cpu,cuda")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    work_dir = Path(args.work_dir).resolve()
    for need in ("scene_build", "mitsuba_scene"):
        if not (work_dir / need).is_dir():
            sys.exit(f"work-dir is missing {need}/ — copy it from blender/ first")

    facts = host_facts(args.python)
    results = {"host_facts": facts, "repeats": args.repeats, "cells": []}
    backends = [b.strip() for b in args.backends.split(",") if b.strip()]

    print(f"host   : {facts.get('host')} ({facts.get('arch')})")
    print(f"cpu    : {facts.get('cpu')}  x{facts.get('cores_logical')} logical")
    print(f"gpu    : {facts.get('gpu')}")
    print(f"stages : {len(STAGES)}  backends: {backends}  repeats: {args.repeats}\n")

    for backend in backends:
        env = backend_env(backend, work_dir)
        probed = probe_variant(args.python, env)
        print(f"  [{backend}] probed variant: {probed}")
        for cell_id, script_name, argv in STAGES:
            script = STAGES_DIR / script_name
            if not script.exists():
                print(f"  ! missing stage script {script_name} — reporting as failed cell")
                results["cells"].append({"backend": backend, "stage": cell_id,
                                         "runs": [], "error": "stage script not found"})
                continue
            runs = []
            for i in range(args.repeats):
                rec = run_cell(args.python, script, argv, env, work_dir)
                rec["repeat"] = i
                if not rec.get("variant"):
                    rec["variant"] = probed
                    rec["variant_source"] = "probe"
                else:
                    rec["variant_source"] = "stage-stdout"
                rec["cold"] = (i == 0)
                runs.append(rec)
                status = "ok" if rec["ok"] else f"FAIL rc={rec['returncode']}"
                print(f"  {backend:5s} {cell_id:17s} r{i}  "
                      f"{rec['wall_s']:8.2f}s  cpu {str(rec['cpu_pct']):>7}%  "
                      f"rss {rec['max_rss_mb']:7.0f}MB  {rec['variant']}  {status}")
            results["cells"].append({"backend": backend, "stage": cell_id, "runs": runs})

    # Rule 2 enforcement: a cpu-labelled run that did not select an llvm variant is invalid.
    for cell in results["cells"]:
        if cell.get("backend") == "cpu":
            for r in cell.get("runs", []):
                v = r.get("variant")
                if v and not v.startswith("llvm"):
                    r["invalid_backend_label"] = True

    out = Path(args.out) if args.out else (
        REPO / "benchmarks" / "results" /
        f"{facts.get('host','unknown')}-{facts.get('arch','unknown')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
