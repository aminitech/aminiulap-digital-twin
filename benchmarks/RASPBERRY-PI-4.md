# Raspberry Pi 4 — measured, not extrapolated

The paper argues that a climate-vulnerable state should own its perception layer rather
than rent it. That argument is only as good as the hardware it needs. This is the run on
the smallest real machine we could put it on.

## The machine

| | |
|---|---|
| Model | Raspberry Pi 4 Model B Rev 1.5 |
| Architecture | `aarch64`, 4 × Cortex-A72 |
| Memory | 8 GB |
| OS | Debian GNU/Linux 13 (trixie) |
| Python | 3.13.5 |
| Storage | microSD |
| Solver stack | sionna-rt 2.0.1, Mitsuba 3.8.0, Dr.Jit 1.3.1, NumPy 2.5.1 |
| Backend | `llvm_ad_mono_polarized` — CPU only, `CUDA_VISIBLE_DEVICES=""` |

No GPU. No CUDA. No cloud service. No licence server. Stock wheels from PyPI installed
without compiling anything from source — Python 3.13 on `aarch64` is supported by the
whole stack as shipped.

## Results

Full deterministic propagation pipeline, single run per stage.

| Stage | Wall (s) | Peak RSS (MB) | CPU |
|---|---|---|---|
| Coverage, flat | 118.6 | 810 | 361 % |
| Coverage, terrain | 142.1 | 814 | 367 % |
| Frequency analysis | 22.2 | 505 | 180 % |
| mmWave / SINR | 13.3 | 308 | 160 % |
| Ground-following | 14.2 | 281 | 250 % |
| **Full pipeline** | **310.4** | **814** | |

Roughly **five minutes** for the complete study.

## The result that matters

`link_metrics.csv` on the Pi:

```
08afea6db1da9b0e635fef3650a23c4f
```

That is the same MD5 as the NVIDIA GB10 (`aarch64`), the NVIDIA H200 NVL (`x86_64`), and
the copy committed to this repository. The Raspberry Pi produces a **byte-identical**
numeric result to hardware costing four orders of magnitude more.

Because the file is written at two decimal places, this establishes agreement to 0.01 dB
and 0.01 ns with identical path counts — not bit-identical floating point. That
distinction is made everywhere else in this work and is made here too.

## Honest caveats

- **The Pi was thermally stressed.** It ran 68–73 °C and `vcgencmd get_throttled` returned
  `0x80000`, meaning the *soft* temperature limit had been reached at some point. No
  current-throttling bits were set during the runs, but these timings should be read as
  achievable on a passively-cooled board, not as a best case. A heatsink or fan would
  likely improve them.
- **Single run per stage.** Unlike the two-host matrix in `METHOD.md`, these are not
  medians of three. They establish feasibility and order of magnitude, not a precise
  figure to quote to two significant digits.
- **Roughly 12× slower than the GB10** on the same work (310 s vs 26.5 s for the full
  pipeline, CPU-only on both). That is the expected penalty for four Cortex-A72 cores
  against twenty server-class ARM cores, and it is the honest cost of the sovereignty
  argument: the capability is affordable, not fast.
- Peak memory was **814 MB**, essentially identical to every other machine tested. The
  workflow's footprint is fixed by the scene, not by the host.

## Reproducing this

```sh
python3 -m venv venv && ./venv/bin/pip install -r benchmarks/requirements.txt
# copy blender/{scene_build,mitsuba_scene,mitsuba_scene_terrain} into a work dir
CUDA_VISIBLE_DEVICES="" MI_DEFAULT_VARIANT=llvm_ad_mono_polarized \
ULAP_WORK_DIR=<work dir> MPLBACKEND=Agg \
  ./venv/bin/python ulap-scope/ulap_scope/stages/sionna_coverage.py flat
```

No Blender is required: the exported Mitsuba scenes are committed.

## Addendum (2026-07-30): the heaviest stage, at the raised default

After the sampling default rose to 10⁸ rays/tx, the ground-following stage became the
pipeline's dominant cost (262 s on 20 server-ARM cores; 7.6 s on the GB10 GPU). The Pi 4
completed it:

| | Wall | Peak RSS | Outcome |
|---|---|---|---|
| `sionna_terrain_ground` @ 10⁸/tx, K=57 | **4 852 s (80.9 min)** | 354 MB | rc=0, figure produced |

Run detached under `nohup` (an earlier attempt died with its SSH session), passively
cooled, 73–83 °C with the soft thermal limit intermittently active — so this is a
worst-case figure, not a tuned one. Against the GB10 GPU's 7.6 s the spread is ~640×:
that is the honest price axis between "a ministry can own it" and "an analyst can iterate
on it". Memory stayed within the same sub-GB envelope as every other machine.
