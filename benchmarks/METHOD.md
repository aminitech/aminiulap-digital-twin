# Benchmark and comparison method

**Metrics and rules are fixed here BEFORE any measurement is taken.** This file is the
pre-registration. If a result later looks inconvenient, the rule does not change — the result
gets reported.

## Why this exists

The paper claims the propagation pipeline is *"reproducible on commodity sovereign hardware"* and
that *"the solve uses the Mitsuba LLVM backend on CPU; CUDA is not required."* Those are the
load-bearing sovereignty claims of the whole architecture, and as written they carry **no numbers**:
no wall-clock, no memory, no core count, no named machine. This harness turns the adjective into a
measurement.

It also supplies the baseline comparison the paper does not currently have. The propagation results
are reported without comparison to any external model, measurement campaign, or prior published
dataset — only internal flat-versus-terrain ablations.

## What is measured

Per run:

| Field | Meaning |
|---|---|
| `wall_s` | Elapsed wall-clock, monotonic clock, process start to exit |
| `user_s` / `sys_s` | Child CPU time from `getrusage(RUSAGE_CHILDREN)` deltas |
| `cpu_pct` | `(user_s + sys_s) / wall_s * 100` — parallel efficiency, not a speed |
| `max_rss_mb` | Peak resident set of the child process tree |
| `variant` | The Mitsuba variant the solver **actually selected**, read back from the run, not assumed |
| `outputs` | Every produced file with its MD5 |

## Rules fixed in advance

1. **Repeats.** Every cell runs 3 times. Report median wall-clock and the full spread. A single
   timing is not a measurement.
2. **The variant is read, never assumed.** Sionna silently selects CUDA when it is available. A run
   labelled "CPU" must show `llvm_*` in its own output or it is discarded and re-run, not relabelled.
3. **Cold vs warm is declared.** The first repeat of each cell follows a fresh interpreter; JIT and
   kernel-cache effects are reported rather than averaged away.
4. **Checksums decide correctness, not eyeballs.** A backend or host only "agrees" if the output
   checksum matches. Where checksums differ, the numeric delta is reported — not hand-waved as
   "floating point".
5. **Failures are published.** Any cell that errors, falls back, or cannot run is reported as a
   failed cell with its error, not silently omitted from the table.
6. **No cherry-picking of configurations.** The matrix is declared below and run in full. A cell may
   not be dropped because its result is awkward.
7. **The cheap model is allowed to win.** In the comparison work, cases where the analytical model
   matches the ray tracer at a fraction of the cost are reported as findings in their own right,
   not buried.

## The matrix

- **Hosts:** `spark-5804` (NVIDIA GB10, aarch64) · `bgi-ran-01` (NVIDIA H200 NVL, x86_64)
- **Backends:** Mitsuba LLVM (CPU, `CUDA_VISIBLE_DEVICES=""`) · CUDA
- **Stages:** `sionna_coverage` (flat), `sionna_coverage` (terrain), `sionna_analysis`,
  `sionna_mmwave_sinr`, `sionna_terrain_ground`
- **Repeats:** 3

## Comparison studies

| ID | Question | Honest failure mode it must expose |
|---|---|---|
| C1 | How closely does the shipped analytical model (free-space + two-ray + knife-edge) track deterministic ray tracing on the Newton transect? | Where the analytical model is *blind* — notably multipath delay spread, which it cannot represent at all |
| C2 | Is deterministic ray tracing actually an upgrade on the stochastic TR 38.901 planning surface, as the paper claims? | If the two agree within noise on median path gain, the "upgrade" claim is weaker than stated |
| C3 | What does terrain and ground-following actually change, numerically? | If the ground-following map differs little from the horizontal plane, the nine-plane machinery is not earning its complexity |

Metrics for C1/C2, fixed now: RMS error in dB, mean signed bias in dB, fitted path-loss exponent
`n` and its delta, Pearson correlation, and the fraction of the compute cost. For C3: median and
p10/p90 path gain per variant, and the fraction of cells whose best server changes.
