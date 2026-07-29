# 🚗 Drive test — handover replay

Animates a receiver driving through the twin, tracking which tower serves it and
what the link budget looks like at every step.

```bash
python examples/apps/drive_test/drive_test.py
```

Writes two files next to wherever you run it:

- `drive_test.gif` — the animation: coverage backdrop + route on the left, live
  RSRP per tower with handover markers on the right;
- `drive_test.csv` — one row per sample: position, serving tower, best-server
  RSRP, SINR, and the RSRP from *every* tower.

That CSV is the actual deliverable. It is the harness you validate handover
thresholds against: hysteresis, time-to-trigger, ping-pong rate.

## Options

```bash
python drive_test.py --freq-ghz 1.8       # low band — fewer handovers, deeper reach
python drive_test.py --frames 90 --fps 15 # smoother animation
python drive_test.py --rx-height-m 10     # rooftop CPE instead of a handset
python drive_test.py --no-terrain         # ablate the terrain and re-run
python drive_test.py --cell-m 5           # finer coverage backdrop (slower)
python drive_test.py --out ~/Desktop/drive.gif --csv ~/Desktop/drive.csv
```

`--help` lists them all. A 60-frame run takes a few seconds.

## Reading the output

Handovers are the dashed red lines. Expect **ping-pong** — several handovers
within a few hundred metres — wherever the route runs along a cell boundary with
both sites nearly equal. That is exactly the pathology a real network suppresses
with hysteresis and a time-to-trigger timer, and this replay is where you'd tune
those before touching a live site.

## Relation to the ray-traced version

This is the analytical counterpart of the pilot's
[`docs/renders/moving_rx.gif`](../../../docs/renders/moving_rx.gif), which
`ulap-scope animate` produces with full Sionna RT multipath. Same route, same
towers, same idea — this one runs in seconds on any laptop, and cannot tell you
anything about delay spread or fast fading.
