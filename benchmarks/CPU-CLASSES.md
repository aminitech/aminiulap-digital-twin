# CPU classes — the sovereignty claim as a hardware ladder

The paper's claim is that the deterministic propagation pipeline runs on *commodity
sovereign hardware*, CPU-only. One anecdote (a fast ARM devbox) does not establish a
claim about a hardware class. This table measures the same fixed workload across the
CPU classes a ministry, a university lab, or a field office would actually own —
from netbook-class two-core machines to a 256-logical-core x86 server.

Raw per-run data: [`results/cpu-classes-spark-5804.json`](results/cpu-classes-spark-5804.json).
Harness: [`cpu_classes.sh`](cpu_classes.sh). Rules inherited from [`METHOD.md`](METHOD.md):
median of 3, full spread reported, Mitsuba variant read back from every run, failures
published. No cell failed and no run selected anything but `llvm_ad_mono_polarized`.

## How the ladder was built

Core-count classes are emulated on **one host** — `spark-5804`, NVIDIA GB10, 20 ARM
cores — by hard-capping each run with a cgroup scope plus CPU pinning:

```sh
systemd-run --user --scope -q -p MemoryMax=8G -- taskset -c 0-N env \
  CUDA_VISIBLE_DEVICES="" MI_DEFAULT_VARIANT=llvm_ad_mono_polarized ... \
  /usr/bin/time -v python <stage>
```

`MemoryMax=8G` matches the Raspberry Pi 4's RAM, so no capped class can quietly lean
on memory a small machine would not have (in practice it never bound: peak RSS stayed
at ~0.5–0.8 GB in every class). Each class's cap was verified to bite (`nproc` inside
the scope equals the class size) before any measurement.

The GB10 is heterogeneous — read back from `/sys` at run time, not assumed:
cpus 0–4 and 10–14 are **Cortex-A725** (max 2.81 GHz, "little"), cpus 5–9 and 15–19
are **Cortex-X925** (max 3.90 GHz, "big"). Plain classes pin cpus `0..N-1`, so the
2- and 4-core classes run on **little cores only** — deliberately conservative for
the small-machine classes. One extra class, `4big` (cpus 5–8), pins four X925 cores
to measure the big:little ratio inside the same machine.

**Fixed measured unit per class** (one stage set, stated explicitly):

- `sionna_analysis.py` — frequency sweep + multi-tower + transect; `spp = 1e6` per
  map, **unchanged since the Pi 4 run**, so it is directly comparable to that row.
- `sionna_coverage.py flat` — `samples_per_tx = 1e8`, 8 m cells: the **current
  raised default** (raised from 1e7 in commit `968b0ee`).

`sionna_terrain_ground.py` at the raised default is excluded from the ladder: it is
too slow to run three-fold on the small classes, and the ladder needs one fixed
stage set across every class. It appears nowhere in this document's numbers.

Scene: the Barbados pilot scene (576 buildings, Newton/Rising Sun/Boarded Hall/Oistins),
i.e. the same scene as every other committed benchmark — these rows may be quoted
against the paper's tables. Stack: sionna-rt 2.0.1, Mitsuba 3.8.0, Dr.Jit 1.3.1,
NumPy 2.5.1, Python 3.12.3.

## The ladder

Medians of 3, spread in brackets. All CPU-only, `llvm_ad_mono_polarized` confirmed
per run (coverage prints its variant; analysis is covered by the in-stage hard abort
plus a variant probe inside the same capped scope).

| Class | Cores (silicon) | Analysis (s) | Coverage flat @1e8 (s) | Coverage CPU util |
|---|---|---|---|---|
| Netbook class | 2 × A725 | 11.04 [10.69–11.06] | 103.99 [102.55–105.83] | 97 % |
| Single-board / entry laptop | 4 × A725 | 6.12 [6.06–6.13] | 53.15 [53.14–53.22] | 94 % |
| 4 big cores (silicon contrast) | 4 × X925 | 3.02 [3.00–3.03] | 26.12 [26.05–26.18] | 93 % |
| Mainstream laptop/desktop | 8 (5 A725 + 3 X925) | 2.84 [2.83–2.88] | 19.95 [19.89–19.98] | 90 % |
| Workstation | 16 (10 A725 + 6 X925) | 2.66 [2.61–2.67] | 11.50 [11.45–11.51] | 78 % |
| Server ARM (uncapped GB10) | 20 (10 A725 + 10 X925) | 2.61 [2.58–2.63] | 10.25 [10.13–10.31] | 64 % |

Two rows of **real foreign silicon**, from committed data — cited, not re-run:

| Real machine | Cores | Analysis (s) | Coverage flat (s) | Source |
|---|---|---|---|---|
| Raspberry Pi 4 Model B | 4 × Cortex-A72 @ 1.8 GHz | 22.2 (single run) | 118.6 — **at the old 1e7 default; not comparable to the 1e8 column** | [`RASPBERRY-PI-4.md`](RASPBERRY-PI-4.md) |
| bgi-ran-01 (x86 server) | Intel Xeon 6760P, 256 logical | 4.92 [4.914–4.95] | 4.48 [4.27–4.48] — **at 1e7; not comparable** | [`results/bgi-ran-01-x86_64-sionna201.json`](results/bgi-ran-01-x86_64-sionna201.json) |

Peak RSS was 0.49–0.56 GB (analysis) and 0.78–0.80 GB (coverage) in **every** class,
capped or not — the footprint is fixed by the scene, not the host, exactly as the
Pi 4 document found.

**Correctness under capping:** the `link_metrics.csv` produced by the capped runs has
MD5 `08afea6db1da9b0e635fef3650a23c4f` — byte-identical to the committed result and to
the Pi 4, GB10 and H200 copies. Capping cores changes speed only, never the answer.

## Scaling efficiency — where wall-clock stops being CPU-bound

**Coverage (the parallel stage).** Utilisation falls smoothly: 97 % on 2 cores,
90 % on 8, 78 % on 16, 64 % on 20. Normalising for silicon (one X925 ≈ 2.03 A725,
measured below), speedup per unit of compute capacity relative to the 2-core row is
0.98 at 4 cores, 0.98 at 4big, 0.94 at 8, 0.81 at 16, 0.67 at 20. A two-point Amdahl
fit (2-core and 20-core rows) gives a serial floor of roughly **3–4 s** — scene load,
Python/JIT start-up and plotting — against ~200 A725-core-seconds of parallel solve.
On small machines the stage is essentially perfectly CPU-bound; past ~16 cores the
serial floor is already a third of the wall-clock.

**Analysis (the latency-shaped stage) saturates at ~3.5 cores' worth.** Its CPU
utilisation never exceeds ~360 % regardless of cores offered; going 8 → 20 cores buys
8 % (2.84 s → 2.61 s). The sharpest evidence is the real x86 server: **256 logical
Xeon cores take 4.92 s — slower than four capped X925 cores at 3.02 s.** Once a
machine has ~8 competent cores, this stage is bound by per-core speed and JIT
latency, not core count. Buying more cores does not buy this pipeline speed;
buying better cores does.

## Cores vs silicon — the contrast that matters

The 4-core capped GB10 row and the real Pi 4 have the **same core count**. The gap is
silicon quality alone:

| | Real Pi 4 (4 × A72 @ 1.8) | Capped GB10 (4 × A725 @ 2.81) | Ratio |
|---|---|---|---|
| Analysis (identical settings) | 22.2 s | 6.12 s | **3.6×** |
| Coverage flat @1e7 (identical settings)¹ | 118.6 s | 33.43 s [33.33–33.97] | **3.5×** |

¹ The Pi's coverage number predates the sample raise, so this row was measured with an
explicitly-labelled **extra** run outside the fixed ladder: same 4 little cores, same
cgroup + taskset harness, `ULAP_RM_SAMPLES_PER_TX=1e7`, 3 repeats. Both the variant
(`llvm_ad_mono_polarized`) and the sample count (`samples_per_tx=1e+07`) were read
back from the stage's own stdout in all three runs.

Two independent stages agree: **~3.6× from one ARM little-core generation to another
at identical core count** (1.56× of it clock, the rest IPC, caches and memory system).
Inside the GB10 itself, four X925 big cores beat four A725 little cores by a uniform
**2.03×** on both stages (clock accounts for 1.39×). And the full span of the ladder —
real Pi 4 to real 256-core Xeon to uncapped GB10 — shows the whole game is core
quality plus *enough* cores, not core count: the Pi is 8.5× slower than the GB10 on
analysis, while the 256-core Xeon *loses* to it.

For the sovereignty argument this is the useful shape: the pipeline degrades
**smoothly and predictably** down the hardware ladder. Every class produced the
identical result; the only thing money buys is minutes.

## The laptop row that did not happen

An Apple M2 MacBook (`100.93.245.6`, tailnet) was probed for a real laptop-class row.
`ssh -o BatchMode=yes` reached the host but **publickey auth was denied for all three
keys available on this box** (`id_ed25519`, `id_ed25519_bgi`, `id_rsa`), and an agent
session cannot answer an interactive password prompt. One host-key exchange plus a
sweep of all three identities, then recorded here as **not reachable** per the
pre-registered failure rule. No laptop-class real-silicon
row exists in this round; the 8-core capped row is the nearest emulated stand-in.

## What this does NOT show

- **Emulated caps are core-count emulation, not silicon emulation.** Every capped run
  still enjoyed the GB10's system-level cache, LPDDR5X bandwidth, NVMe storage and
  cooling. A real 2-core netbook has less of *everything*, not just cores — the real
  Pi 4 rows are 3.5–3.6× slower than the same-core-count cap for exactly this reason.
  The capped rows are lower bounds on class hardware of GB10-grade silicon, not
  predictions for any specific cheap machine.
- **The mixed-silicon rows (8, 16 cores) are not pure count-scaling points.** Pinning
  is little-cores-first, so those classes mix A725 and X925; the capacity-normalised
  efficiency figures above use the measured 2.03× big:little ratio to correct for it,
  and that correction is a model, not a measurement.
- **The 8 GB memory fence never bound** (peak RSS ≤ 0.8 GB), so it demonstrates
  nothing beyond "the workload fits in a Pi's RAM" — which the real Pi already proved.
- **The Pi 4 row is a single run on a thermally-stressed board** (its own document
  says so); the Xeon coverage row and Pi coverage row are at the old 1e7 default and
  must not be read against the 1e8 column.
- **One scene, one workload.** The ladder fixes the Barbados pilot scene and two
  stages; a much larger scene could shift the serial/parallel split and the memory
  floor.
