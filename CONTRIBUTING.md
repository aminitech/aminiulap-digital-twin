# Contributing to Ulap Digital Twin

Thanks for helping build reproducible RF digital twins! ((♥))

## Ground rules

- Be kind — we follow the [Code of Conduct](CODE_OF_CONDUCT.md).
- **Spec first.** Behaviour changes start as an [OpenSpec](openspec/) change
  proposal under `openspec/changes/<change-id>/` (proposal + spec deltas + tasks).
  Small fixes and docs don't need one.
- **Reproducibility is the product.** Anything that affects results — solver
  params, materials, CRS, band plan — must be recorded in config/`study.toml`,
  not hard-coded in a stage script.

## Where things live

Code contributions land in [`ulap-scope/`](ulap-scope/) — the installable
package. `BlenderGIS/` and `mitsuba-blender/` are vendored upstream add-ons:
don't patch them here; upstream your fix and bump the vendored copy.

## Dev setup

```bash
cd ulap-scope
pip install -e .[test]
pytest                  # fast suite — should pass everywhere, no GIS deps
```

Running the full pipeline needs the three interpreters (prep / Blender / Sionna)
described in [`ulap-scope/README.md`](ulap-scope/README.md); the pinned conda
envs are in `environment-prep.yml` and `environment-rt.yml`.

## Pull requests

1. Branch from `main`; keep PRs focused on one change.
2. Add or update tests — the fast suite must stay green on Python 3.10–3.12
   without Blender/Sionna installed (mark anything heavier with `-m rt`).
3. If your change alters a rendered result, regenerate the relevant figure and
   update `docs/renders/` + the figure index so the README previews stay honest.
4. Update the matching spec in `openspec/specs/` when behaviour changes.
5. Describe *what changed in the physics/geometry* in the PR body, not just the
   code — e.g. "adds foliage loss, mmWave medians drop ~8 dB".

## Reporting issues

Include the `study.toml` (or `ulap-scope info` output), the stage that failed,
your platform, and — for result anomalies — the figure and the number you
expected. Radio bugs are geometry bugs more often than solver bugs: a
`persp_paths.png` render is worth a thousand words.

## Data

Don't commit large binaries (blend autosaves, GeoTIFF mosaics, raw tiles) —
`.gitignore` covers the usual suspects. Curated, README-referenced renders go in
`docs/renders/`. Respect the license/terms of any geospatial source you add, and
prefer open layers (OSM, Copernicus, ESA WorldCover) with the source recorded in
`study.toml`.
