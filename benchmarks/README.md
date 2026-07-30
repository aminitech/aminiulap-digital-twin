# Benchmarks

The paper claims the propagation pipeline is *"reproducible on commodity sovereign
hardware"* and that *"the solve uses the Mitsuba LLVM backend on CPU; CUDA is not
required."* This directory turns those two adjectives into numbers on two machines of
different architecture, and publishes what did not work as loudly as what did.

| File | What it is |
|---|---|
| `METHOD.md` | The pre-registration. Metrics and rules fixed **before** measurement. Binding. |
| `run_bench.py` | The harness. Runs the 5 x {cpu, cuda} x 3 matrix and writes one JSON per host+environment. |
| `results/*.json` | Raw measurements, one file per host+environment. Do not edit the measured fields. |
| `make_tables.py` | Combines every JSON in `results/` into Markdown + LaTeX tables. |
| `tables/` | Generated output. Regenerate, never hand-edit. |

---

## Run it — one command

```sh
bash benchmarks/run.sh
```

That is the whole thing. It checks the prerequisites that would otherwise fail *silently*,
prepares a work dir from the committed Mitsuba scenes, auto-detects whether a GPU is
usable, runs the matrix, and regenerates the tables.

```sh
bash benchmarks/run.sh --backends cpu     # no GPU present
bash benchmarks/run.sh --repeats 1        # quick feasibility check
PYTHON=./venv/bin/python bash benchmarks/run.sh
OUT=/tmp/mine.json bash benchmarks/run.sh # choose the output file
```

Setup, if you have not already:

```sh
python3 -m venv venv && ./venv/bin/pip install -r benchmarks/requirements.txt
sudo apt install time     # or: sudo dnf install time
```

**Three things it protects you from**, each of which cost us real time to discover:

- **A missing GNU `time`** makes the harness record CPU% and peak RSS as zero rather than
  failing. `run.sh` refuses to start without it.
- **Sionna tries the CUDA variants first**, so a run you believe is CPU-only will silently
  execute on a GPU if one is visible. The harness reads the variant back from every run and
  marks a mismatch invalid rather than relabelling it.
- **Re-running on a machine that already has a committed result** would overwrite it.
  `run.sh` detects this and writes to `<host>-<arch>-local.json` instead, telling you so.

You do **not** need Blender, and you do **not** need the licence-restricted Barbados
layers: the exported Mitsuba scenes are committed.

## Host inventory

| Host | Arch | CPU | Logical cores | RAM | GPU | Role |
|---|---|---|---|---|---|---|
| `spark-5804` | aarch64 | NVIDIA GB10 Grace (`/proc/cpuinfo` reports only `CPU part: 0xd87`) | 20 | 121.7 GB | NVIDIA GB10, cc 12.1 | The sovereign box the paper is about. Limuru, Kenya. |
| `bgi-ran-01` | x86_64 | Intel Xeon 6760P | 256 | 503.0 GB | NVIDIA H200 NVL, cc 9.0 | Cross-architecture control. Shared, live, not quiesced. |

Solver stack for the primary matrix, identical on both hosts and equal to the version
`ulap-scope/pyproject.toml` pins and the paper cites:
**sionna-rt 2.0.1**, mitsuba 3.8.0, drjit 1.3.1, matplotlib 3.11.1, numpy 2.5.1.
Python is 3.12.3 on spark-5804 and 3.12.13 on bgi-ran-01 — the one residual difference.

Interpreters, recorded so this is never ambiguous again (`host_facts.interpreter`, and
mirrored into `annotations.interpreter`):

| Run set | Interpreter | sionna-rt |
|---|---|---|
| `spark-5804-aarch64-sionna201.json` (primary) | `/home/$USER/.claude/jobs/d53ee842/tmp/venv-rt/bin/python` | 2.0.1 |
| `bgi-ran-01-x86_64-sionna201.json` (primary) | `/home/$USER/ulap-twin-verify/venv/bin/python` | 2.0.1 |
| `spark-5804-aarch64.json` (run 1) | not recorded; fingerprinted as a 2.0.1 environment — see below | 2.0.1 |
| `spark-5804-aarch64-fresh.json` | `/usr/bin/python3` (user-site) | 1.2.2 |
| `bgi-ran-01-x86_64-sionna122.json` | `/home/$USER/ulap-twin-verify/venv-s122/bin/python` | 1.2.2 |
| `bgi-ran-01-x86_64-llvmpath.json` | `/home/$USER/ulap-twin-verify/venv/bin/python` | 2.0.1 |
| `bgi-ran-01-x86_64.json` | `/home/$USER/ulap-twin-verify/venv/bin/python` | 2.0.1 |

**Which interpreter produced spark run 1.** The harness revision that wrote
`spark-5804-aarch64.json` did not record it, and an earlier annotation of that file
guessed 1.2.2. That guess was wrong. Seven repeat-stable artefacts —
`coverage_pathgain_db.png`, `link_metrics.png`, `multitower_bestserver_handover.png`,
`sweep_frequency.png`, `mmwave_concrete_coverage.png`, `sinr_map.png`,
`coverage_pathgain_db_terrain_groundfollow.png` — match the 2.0.1 run byte for byte and
differ from the 1.2.2 run. Run 1 was a sionna-rt 2.0.1 environment, almost certainly
`/home/$USER/.claude/jobs/d53ee842/tmp/venv-rt/bin/python`.

Scene inputs were verified byte-identical across hosts before any run
(`md5sum` over all 9 files of `blender/{scene_build,mitsuba_scene,mitsuba_scene_terrain}`),
as were the five stage scripts.

---

## How to run the harness

The harness needs a *work dir*: a copy of the scene inputs plus an **empty**
`sionna_out/`. Start it empty — `run_bench.py` records output checksums as a diff
against whatever was already there, so a dirty work dir silently loses checksums.

```bash
W=/tmp/scdt-bench
rm -rf $W && mkdir -p $W/sionna_out
cp -r blender/scene_build blender/mitsuba_scene blender/mitsuba_scene_terrain $W/

python3 benchmarks/run_bench.py \
  --work-dir $W --python /usr/bin/python3 \
  --repeats 3 --backends cpu,cuda \
  --out benchmarks/results/<host>-<arch>.json
```

`--python` must point at an interpreter with `sionna.rt`, `mitsuba` and `drjit`
importable. The harness reads back the Mitsuba variant each cell actually selected and
flags any `cpu`-labelled run that did not land on `llvm_*`.

### Running it on a second host

```bash
scp benchmarks/run_bench.py benchmarks/METHOD.md <host>:<repo>/benchmarks/
ssh -o BatchMode=yes -o ConnectTimeout=30 <host> 'bash -s' < your-run-script.sh
scp <host>:'<repo>/benchmarks/results/*.json' benchmarks/results/
```

Two things the harness needs on the remote host:

* **GNU `time`** at `/usr/bin/time`. Without it `cpu_pct` and `max_rss_mb` are silently
  recorded as 0. Rocky Linux 9 does not ship it by default (`dnf install time`).
* **A findable `libLLVM.so`** if you want the CPU backend — see the finding below.

### Post-hoc annotations

Each `results/*.json` carries an `annotations` block that `run_bench.py` does **not**
write: `env_label`, `primary`, `stack` (library versions read from the interpreter that
ran the cell), `drjit_libllvm_path`, `order`, and free-text `notes`. `make_tables.py`
uses these to label and order the columns and to decide which run sets form the primary
matrix. They are hand-written metadata; the measured fields are untouched. If you
re-run a host, re-add its annotation block.

## How to regenerate the tables

```bash
python3 benchmarks/make_tables.py            # writes benchmarks/tables/
python3 benchmarks/make_tables.py --stdout   # and prints the Markdown
```

Reads every `results/*.json`. Output:

* `tables/results.md` — all five tables plus provenance, human-readable.
* `tables/hosts.tex`, `wall_clock.tex`, `resources.tex`, `environments.tex`,
  `determinism.tex`, `replication.tex`, `version_wall.tex`, `version_artifacts.tex` —
  booktabs `table*` environments, drop-in for IEEEtran (`\usepackage{booktabs}`).

---

## Findings

### 1. The CPU-only claim holds — on both architectures, once the LLVM library is findable

Whole 5-stage pipeline at the pinned version (sionna-rt 2.0.1), sum of per-stage medians:

| | CPU (Mitsuba LLVM) | CUDA |
|---|---|---|
| spark-5804 (GB10, 20 cores) | 26.5 s | 13.8 s |
| bgi-ran-01 (Xeon 6760P, 256 cores) | 19.1 s | 16.6 s |

Peak RSS never exceeded 1.25 GB on any cell, on either host, on either backend. The
pipeline is a laptop-class memory workload; the sovereignty claim is not memory-bound.

The GPU advantage is modest and stage-dependent. On spark-5804 CUDA is 2.5x faster on
the flat coverage solve and 2.8x on terrain, but only 1.08-1.25x on the three light
stages. On bgi-ran-01 CUDA is 1.17x / 1.08x on the two coverage solves. **These stages
are small enough that process start-up and JIT dominate**, which is also why the H200
does not beat the GB10 on the CUDA column — this is not a GPU throughput measurement and
should not be quoted as one.

### 2. The H200 host could not run the CPU backend as found — and that is a packaging bug, not an architecture limit

All five `cpu`-labelled cells in `results/bgi-ran-01-x86_64.json` **failed** — 15 of 15
runs, `rc=1` in under 0.2 s each — with:

```
ImportError: jit_init_thread_state(): the LLVM backend is inactive because the LLVM
shared library ("libLLVM.so") could not be found! Set the DRJIT_LIBLLVM_PATH
environment variable to specify its path.
```

Cause: Rocky Linux 9 ships `/lib64/libLLVM.so.20.1` and `/usr/lib64/libLLVM-20.so` but
no unversioned `libLLVM.so` — and `libLLVM.so` is the exact name drjit `dlopen`s. The
LLVM runtime is present; only the name drjit looks for is absent.

Two things worth stating plainly:

* `sionna/rt/__init__.py` calls `mi.set_variant("cuda_ad_mono_polarized",
  "llvm_ad_mono_polarized")` — **CUDA first**. On this host, a run that did not force
  `CUDA_VISIBLE_DEVICES=""` would have silently executed on the GPU while being called
  a CPU run. METHOD.md rule 2 is what turned a silent mislabel into a visible failure.
* The fix is one environment variable, no rebuild:
  `DRJIT_LIBLLVM_PATH=/lib64/libLLVM.so.20.1`. With it set, all five CPU cells pass and
  select `llvm_ad_mono_polarized` — this is exactly the difference between
  `results/bgi-ran-01-x86_64.json` and the primary
  `results/bgi-ran-01-x86_64-sionna201.json`, same venv, same host.

Both the failed and the fixed run sets are published. The failed one is table T3 row
`bgi / 2.0.1 as-found`, not a footnote.

### 3. Solver version: 2.0.1 is the primary; 1.2.2 is kept as a sensitivity arm

The primary matrix is measured at **sionna-rt 2.0.1** — what `ulap-scope/pyproject.toml`
pins and what the paper cites. An earlier round of this work matched the two hosts
*downward* to 1.2.2 because that is what the spark system interpreter happens to carry;
that was a methodological error and has been corrected. The 1.2.2 pair is retained as
table T6.

Does 2.0.1 change any conclusion versus 1.2.2? **No conclusion changes; two numbers move.**

* **Wall clock (T6a).** The two ray-traced coverage solves are unmoved on both hosts and
  both backends: 0.97x-1.04x, inside the run-to-run spread. Three light stages on
  spark-5804 CPU are slower under 2.0.1 — `sionna_analysis` 1.15x, `sionna_terrain_ground`
  1.15x, `sionna_mmwave_sinr` 1.31x — but spark was carrying live-service load in the
  10-18 range for both runs and the `mmwave_sinr` spread under 2.0.1 (2.00-2.80 s) nearly
  touches the 1.2.2 spread (1.94-2.00 s). Read as "no clear regression on the solves,
  possible small regression on the light stages, host load not controlled" — not as a
  measured slowdown.
* **Outputs (T6b).** 8 of 13 artefacts change bytes across the version step,
  deterministically and on both hosts. So the two versions are *not* interchangeable for
  artefact-level reproducibility — which is precisely why the paper must benchmark the
  version it cites.
* **`link_metrics.csv` is identical across the version change**, on both hosts and both
  backends. The numeric result survives 1.2.2 -> 2.0.1, aarch64 -> x86_64 and LLVM ->
  CUDA — a stronger statement than the previous round could make.

### 4. Determinism: the numeric artefact reproduces, the rendered artefacts do not

* `link_metrics.csv` — the only numeric output — is **byte-identical across both
  architectures, both backends and both solver versions**. Caveat, stated because it
  matters: the stage writes `f"{g:.2f}"`, so this proves agreement to 0.01 dB in path
  gain, 0.01 ns in delay spread and exact integer path counts. It does **not** prove
  bit-identical floating-point arithmetic.
* Every PNG differs across hosts and across backends. Per METHOD.md rule 4 the delta is
  quantified rather than waved off as "floating point" — for `sionna_coverage flat`:

  | Comparison | `coverage_map.png` | `coverage_pathgain_db.png` | `scene_render.png` |
  |---|---|---|---|
  | spark CPU vs spark CUDA | 0.38% px, mean 0.006/255 | 0.18% px, mean 0.003/255 | 0.01% px, mean 0.0002/255 |
  | bgi CPU vs bgi CUDA | 0.40% px, mean 0.007/255 | 0.17% px, mean 0.003/255 | 0.01% px, mean 0.0004/255 |
  | spark CPU vs bgi CPU | 0.67% px, mean 0.014/255 | 0.23% px, mean 0.005/255 | 2.41% px, mean 0.038/255 |
  | spark CUDA vs bgi CUDA | 0.67% px, mean 0.014/255 | 0.16% px, mean 0.004/255 | 2.41% px, mean 0.038/255 |

  Sub-percent of pixels differ (2.4% for the ray-traced perspective render), mean
  absolute difference under 0.04 of 255. Peak differences reach 224/255 on isolated
  pixels — colormap boundaries and glyph anti-aliasing, not a different propagation
  result. (Measured on the 1.2.2 pair; the version step changes bytes, not this
  conclusion.)

* **CUDA is not repeat-stable.** Within a single benchmark invocation, CUDA re-runs of
  the same stage produced different PNGs on both hosts (table T4): 7 of 13 artefacts on
  spark, 4 of 13 on bgi. CPU was repeat-stable in every cell on bgi and in every cell on
  spark except `coverage_pathgain_db_terrain.png`, which flip-flopped between two values
  across three repeats.
* **The CPU backend is also stable across separate invocations** (table T5). Comparing
  the primary spark run against run 1 — same host, same 2.0.1 stack, different
  invocation — every CPU artefact matches except that same
  `coverage_pathgain_db_terrain.png` (`link_metrics.csv` is unrecorded in run 1, so it
  reads `?` rather than a match); on bgi every CPU artefact matches. CUDA is the
  unstable backend, both within and across invocations.

  *Correction to an earlier draft of this file:* a previous version claimed
  cross-invocation instability was widespread even on CPU. That comparison was against
  the 1.2.2 run set, so it was measuring the **version** change, not invocation
  nondeterminism. With the correct same-stack partner the CPU backend is reproducible.

### 5. Caveats on the timings

* `spark-5804` carried load average 10.5-17.9 on 20 logical cores across its runs; it
  hosts live services and was not quiesced. `bgi-ran-01` sat at ~0.9 on 256 cores but
  holds a vLLM instance pinning ~95 GB of the H200's 143 GB. Neither host is a clean
  bench.
* `cpu_pct` is parallel efficiency, not speed. bgi-ran-01 reaches 5048% (50 cores busy)
  and still only beats spark's 982% (10 cores busy) by 1.9x on the flat solve.
* The three light stages (`analysis`, `mmwave_sinr`, `terrain_ground`) are *faster* on
  the 20-core GB10 than on the 256-core Xeon. Spinning up a 256-wide drjit thread pool
  costs more than these stages gain from it.
* `spark-5804-aarch64.json` (run 1) reports `variant: null` for three stages: it predates
  the harness's variant probe. Under METHOD.md rule 2 an unverified CPU variant is not a
  verified CPU run, so `make_tables.py` marks those three cells INVALID rather than
  assuming they were LLVM. It is kept as the cross-invocation partner of the primary, not
  as a timing row.

---

## Reproducing the pixel deltas

Not produced by `make_tables.py` — it is a one-off measurement over four single-stage
runs (one per host per backend) into four fresh work dirs. To repeat it, run
`ulap-scope/ulap_scope/stages/sionna_coverage.py flat` once per backend per host with
`ULAP_WORK_DIR` pointing at a fresh dir (`CUDA_VISIBLE_DEVICES=""` and
`MI_DEFAULT_VARIANT=llvm_ad_mono_polarized` for the CPU leg), collect the PNGs, then:

```python
import numpy as np, matplotlib.image as mpimg
A = np.asarray(mpimg.imread(a), dtype=np.float64)
B = np.asarray(mpimg.imread(b), dtype=np.float64)
d = np.abs(A - B)
print(f"{(d > 0).sum() / d.size * 100:.3f}% px, max {d.max()*255:.0f}/255, "
      f"mean {d.mean()*255:.5f}/255")
```

---

## Known harness limitations

Two of the four found in the previous round have now been **fixed in `run_bench.py`**
with the coordinator's explicit permission. `METHOD.md` is unchanged.

**Fixed.**

1. **`host_facts()` never recorded the solver version.** It imported `sionna_rt`; the
   distribution is named `sionna-rt` but the *module* is `sionna.rt`, so the import
   always failed and the field was silently omitted — which is how a 1.2.2-vs-2.0.1 split
   between the two hosts went unnoticed for a whole round. It now probes `sionna.rt`,
   `mitsuba`, `drjit`, `numpy` and `matplotlib` **in the interpreter under test**
   (`--python`, which may not be the harness's own interpreter) via `probe_versions()`,
   and records `host_facts.interpreter` — the absolute `sys.executable` — alongside them.
2. **`stderr_tail` was flooded by GNU `time -v`.** It kept the last 800 characters of
   stderr, which `time -v`'s ~23-line rusage report fills completely, so every failed cell
   recorded page-fault counters and none of the traceback. `strip_time_report()` now cuts
   the trailing `time -v` block before truncating, and the slice was widened to 1600
   characters. The rusage parsing still reads the untouched stderr, so `cpu_pct` and
   `max_rss_mb` are unaffected.

Verified: `strip_time_report()` on a synthetic traceback+`time -v` string returns only the
traceback; `probe_versions()` returns 2.0.1 for the venv-rt interpreter and 1.2.2 for
`/usr/bin/python3`; both 2.0.1 run sets carry `interpreter` and `sionna_rt_version` in
`host_facts` with no hand-editing.

**Still open, reported not fixed.**

3. **`outputs` is a diff, not a checksum set.** It records only files whose MD5 changed
   relative to the work dir's prior state, so a dirty work dir silently drops artefacts
   from the record (this is why `link_metrics.csv` is absent from every run in
   `spark-5804-aarch64.json`). `make_tables.py` compensates by replaying the diffs in
   execution order, but the harness could just snapshot absolutely. Left alone because
   changing it would invalidate the comparability of the run sets already collected.
4. **No GNU `time` means silent zeros.** `cpu_pct` and `max_rss_mb` fall back to 0.0
   rather than `None`, so a host without `/usr/bin/time` produces a table of plausible
   zeros instead of "not measured".

## What was changed on the hosts

For the record, since `bgi-ran-01` runs live services:

* `sudo dnf -y install time` (GNU time 1.9) — a 29 kB binary at `/usr/bin/time`, no
  service touched.
* Created `~/ulap-twin-verify/venv-s122`, a new venv pinned to the 1.2.2 sensitivity
  stack. Nothing existing was modified; the pre-existing `~/ulap-twin-verify/venv`
  (sionna-rt 2.0.1), which produced the primary bgi row, is untouched.
* Created scratch work dirs under `~/ulap-twin-verify/` (`rtbench`, `rtbench122`,
  `rtbench201`, `imgcmp-cpu`, `imgcmp-cuda`) and copied `run_bench.py` / `METHOD.md` into
  `~/ulap-twin-verify/amini-ulap-digital-twin/benchmarks/`.
* No service was restarted, stopped, or reconfigured. Peak GPU use by these runs was a
  few hundred MB against ~47 GB free.
