# 📡 Coverage Explorer

An interactive RF planning sandbox for the Newton / Rising Sun pilot twin.

```bash
pip install -r examples/requirements.txt
streamlit run examples/apps/coverage_explorer/app.py
```

Opens at <http://localhost:8501>.

## What you can turn

| Control | Why it's interesting |
|---|---|
| **Band** (0.7 – 60 GHz) | Watch the λ² penalty, then watch the *cell edge* fall faster than the median. |
| **TX power / antenna gain** | Raises RSRP everywhere — and leaves SINR almost untouched. Power does not fix an interference-limited edge. |
| **Receiver height** | 1.5 m (handset) vs 10 m (rooftop CPE) vs 30 m (drone). This is a planning decision, not a detail. |
| **Terrain / buildings** | Switch the geometry off and see what it was worth. Terrain alone can *help* — the towers sit on high ground. |
| **Ground reflection** | `average` for maps, `coherent` to see the true two-ray fringes (and how badly a 10 m grid aliases them). |
| **Candidate site** | Drop a third tower anywhere. Coverage improves; median SINR usually gets worse. That is the lesson. |

Each tab also reports the numbers a planner argues about: median and 5th-percentile
RSRP, served area in km², best-server share per site, and coverage/SINR CDFs. The
RSRP grid downloads as CSV.

## What it is not

A ray tracer. The maps come from the analytical model in
[`ulap_demo/propagation.py`](../../ulap_demo/propagation.py): free space + two-ray
ground reflection + dominant-obstacle knife-edge diffraction. There is no
multi-bounce reflection, no material-specific transmission, no scattering, and no
delay domain. Deeply shadowed pixels are pessimistic — real environments recover
via reflections this model never traces, which is why diffraction loss is capped
(see `max_diffraction_db`).

For real numbers on this scene, see [`docs/renders/`](../../../docs/renders/); to
ray-trace your own, run `ulap-scope coverage`.

## Troubleshooting

- **`ModuleNotFoundError: streamlit`** — `pip install streamlit`.
- **Slow at 5 m resolution** — that is a 422 × 412 grid × N towers; the sidebar's
  grid-resolution control exists for this reason. Results are cached, so only the
  control you actually moved triggers a resolve.
- **Port in use** — `streamlit run ... --server.port 8600`.
