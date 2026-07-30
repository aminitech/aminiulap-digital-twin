# Data availability statement

This repository ships **code, not data**. Every geospatial layer the pipeline
consumes is fetched or supplied by you at run time. This keeps the clone small,
avoids redistributing data we may not have the right to redistribute, and makes
the provenance of each layer explicit.

## Where the pipeline looks for data

The pipeline resolves its data root from environment variables (see
`ulap-scope/ulap_scope/config.py`):

```bash
export ULAP_PROJECT_ROOT=/path/to/ulap-digital-twin   # repo root
export ULAP_DATA_DIR=/path/to/geoportal-shapefiles    # defaults to $ULAP_PROJECT_ROOT/bbd-geo-portal
```

Point `ULAP_DATA_DIR` at a directory laid out as described in
[Expected layout](#expected-layout) below.

## Three categories

| Category | What it means | Layers |
|---|---|---|
| **Shipped** | Committed to this repository | No raw geospatial data. But see [Derived products](#derived-products--pending-disclosure-review) — the `blender/` build outputs are geoportal-*derived* and are still tracked. |
| **Fetched at run time** | Downloaded by a pipeline stage or by you, from a public source | Basemap imagery, DEM, land cover, OSM extracts |
| **Supplied by you** | You must obtain it from the source authority; we cannot redistribute it | Barbados Geoportal layers |

## Fetched at run time

| Source | Layer | Licence | How |
|---|---|---|---|
| ESRI ArcGIS World Imagery | Basemap tiles | Esri terms of use | `ulap-scope basemap` stage |
| Copernicus GLO-30 | 30 m DEM | Free, full and open | Manual download, or the study wizard recommends it |
| ESA WorldCover | 10 m land cover | CC BY 4.0 | Manual download |
| OpenStreetMap / Geofabrik | Building footprints (fallback) | ODbL 1.0 | Manual download |
| OpenStreetMap via Overpass | `examples/data/open_scene_mitsuba/` building meshes — **shipped in this repo** | ODbL 1.0, share-alike, attribution required | Committed; regenerate with `export_mitsuba_direct.py` |
| AWS Terrain Tiles | `examples/data/open_scene_mitsuba/` terrain meshes — **shipped in this repo** | Public domain | Committed |
| OpenCellID | Cell tower positions | CC BY-SA 4.0 | Manual download |

## Supplied by you: Barbados Geoportal

Source: **Lands and Surveys Department, Government of Barbados**.

These layers are **not redistributed in this repository**. The pipeline's
reference study for Barbados requires the layers below. Obtain them from the
Barbados Geoportal directly and place them under `$ULAP_DATA_DIR`.

> **Redistribution status: under review.** Whether any of these layers may be
> republished by us, and at what resolution or with which attributes removed, is
> the subject of a formal Government of Barbados disclosure review. Until that
> review closes, treat every layer here as *not redistributable by third
> parties*. Attribution to the Lands and Surveys Department is required in all
> cases.

### Layers used by the reference study

Only the first two are required to run the pipeline end to end. The rest are
used for the wider twin and for the vulnerability analysis.

| Group | Layer | Required | Sensitivity |
|---|---|---|---|
| Buildings | `BuildingFootprints` | Yes | Standard |
| Telecommunications | `Barbados_antennes_August2023` | Yes | Standard |
| Transport | `Main_roads` | No | Standard |
| Transport | `Bridges` | No | Elevated — transport chokepoints |
| Transport | `Ports_landing_facilities` | No | Elevated — border infrastructure |
| Development | `Major_capital_projects` | No | Standard |
| Water supply | `Drinking_water_network` | No | **High — critical infrastructure** |
| Water supply | `watermains` | No | **High — critical infrastructure** |
| Water supply | `Desalination_plants` | No | **High — critical infrastructure** |
| Water supply | `Reservoirs_capacity` | No | **High — critical infrastructure** |
| Water supply | `Dams` | No | **High — critical infrastructure** |
| Water supply | `Communal_wells`, `Individual_wells` | No | **High — critical infrastructure** |
| Water supply | `Repumping_stations` | No | **High — critical infrastructure** |
| Wastewater | `Wasterwater_plants` *(sic, upstream spelling)* | No | **High — critical infrastructure** |
| Vulnerability | `Population_vulnerability` | No | **High — parish-resolution vulnerability** |
| Vulnerability | `Environmental_vulnerability` | No | **High — parish-resolution vulnerability** |
| Vulnerability | `Equipment_vulnerability` | No | **High — parish-resolution vulnerability** |
| Vulnerability | `Global_vulnerability` | No | **High — parish-resolution vulnerability** |

### Expected layout

```
$ULAP_DATA_DIR/
  shapefiles/
    BuildingFootprints/BuildingFootprints.shp
    Telecommunications/Barbados_antennes_August2023.shp
    Transports/{Main_roads,Bridges,Ports_landing_facilities}.shp
    Major_projects/Major_capital_projects.shp
    Water_management_infrastructures/{Dams,Reservoirs_capacity,...}.shp
    Wastewater_infrastructures/Wasterwater_plants.shp
    Wastewater_infrastructures/WaterMains/watermains.shp
    Vulnerability_maps/{Population,Environmental,Equipment,Global}_vulnerability.shp
  study_area/                 # generated by `ulap-scope clip`
  study_area_web_mercator/    # generated by `ulap-scope clip`
```

Run `scripts/check_data.sh` to verify your layout before running the pipeline.

## Derived products — pending disclosure review

Shipping no raw shapefiles does not by itself settle what may be published.
These artefacts are **derived from** the Barbados Geoportal layers and are
subject to the same disclosure review:

| Artefact | What it contains | Status |
|---|---|---|
| `examples/data/newton_scene_manifest.json` | 576 building footprint polygons (`ring`) with LiDAR-derived heights (`h`) and DTM samples, for the 2 km pilot box | **Removed from the working tree.** Geometry originated from the geoportal `BuildingFootprints` layer, not from OpenStreetMap. Still present in the history of commit `b97ab41` — see below. |
| `blender/scene_build/scene_manifest.json` | The same 576 rings, `"epsg": 21292` (Barbados National Grid), no `provenance` block | **Untracked.** Regenerate with `ulap-scope preprocess`. |
| `blender/scene_build/towers_near.json` | Tower registry for the pilot | **Untracked.** Regenerate with `ulap-scope preprocess`. |
| `blender/mitsuba_scene*/meshes/*.ply` | The building footprints as extruded 3-D meshes — the same geometry in another format | **Untracked.** Regenerate with `ulap-scope export`. |
| `blender/ulap-bbd-memorial-twin*.blend` (3 files) | Full Blender scenes containing the extruded twin | **Untracked.** Regenerate with `ulap-scope build`. |
| `blender/sionna_out/*` | The ray-traced figure set, duplicated in `docs/renders/` | **Untracked.** Regenerate with `ulap-scope coverage` / `analysis`. |
| `docs/renders/*` | Curated copies of the same figures, referenced by the README | **Under review.** Building geometry is visible in the renders; these remain tracked because the README depends on them. |
| `ulap-twin-ui/data.js` | The same 576 footprints as lon/lat rings with LiDAR heights, plus both towers with their operator codes (147 kB) | **Retained by decision.** Kept tracked deliberately — the three.js viewer is inert without it. Same review scope as `docs/renders/`. |

**Closed.** `blender/` is a working directory, not source: everything the
pipeline writes there is regenerable *and* geoportal-derived, so none of it is
tracked any more. Only the pipeline notes and two `__file__`-relative render
helpers remain. `.gitignore` carries the rule under the public-release guard, so
a stray `git add` cannot put them back.

The tracked tree no longer contains **any** absolute developer path. The two
leaking scripts (`blender/preprocess_scene.py`, `blender/fetch_basemap.py`) were
stale duplicates of the portable copies in `ulap-scope/ulap_scope/stages/` and
are gone; the one leaking image (`docs/renders/blender_perspective.png`, which
carried the `.blend` path in a PNG `tEXt` chunk written by Blender) was re-saved
with all metadata stripped and pixels unchanged.

> ⚠️ **Still open: history.** Untracking removes these from the *tip*, not from
> past commits. `blender/scene_build/scene_manifest.json` and the rest have been
> in the repository since the initial commit `14fd043` and are on several pushed
> branches. If the review requires them to be unrecoverable, the history must be
> rewritten and force-pushed — see the history note below.

The open-data replacement path is now the **default**. The examples ship
`examples/data/newton-open_scene_manifest.json`, built by
`examples/data/fetch_open_scene.py` from OpenStreetMap footprints (ODbL 1.0) and
AWS Terrain Tiles, carrying an explicit `provenance` block. That script rebuilds
an equivalent scene anywhere on earth:

```bash
python examples/data/fetch_open_scene.py    # pilot area, fully open sources
python examples/data/fetch_open_scene.py --lon 36.8219 --lat -1.2921 --name nairobi
```

It is candid about the trade: OSM has almost no building heights (a per-type
default table fills in, recorded per building as `h_source`) and open terrain is
~30 m posting against a LiDAR DTM.

Anyone who *has* the geoportal layers can still get full fidelity, but only by
**opting in**. `ulap_demo.load_scene()` resolves in this order:

1. an explicit `manifest_path` argument;
2. `$ULAP_SCENE`;
3. the bundled open-data sample.

The pipeline's own output at `blender/scene_build/scene_manifest.json` is
deliberately **not** in that list. Auto-selecting it would make the demos behave
differently depending on whose checkout they run in, and would quietly load a
licence-restricted scene for anyone whose clone happens to contain one. Opting in
is one environment variable, and `ulap_demo.pipeline_scene_hint()` prints the
exact command when a pipeline manifest is present:

```bash
export ULAP_SCENE=/path/to/blender/scene_build/scene_manifest.json
```

Nothing licence-restricted has to be committed for the demos to work, and nothing
licence-restricted is loaded unless you ask for it by name.

A manifest with **no `provenance` block** came from the real pipeline rather than
from that script; one with a `provenance` block is open data. The examples test
suite enforces the boundary: `test_no_geoportal_derived_scene_is_committed` fails
if any scene in the Barbados National Grid (EPSG:21292) reappears under
`examples/data/`.

> **History note.** Untracking a file removes it from the tip, not from the
> commits that already contain it. Two separate exposures exist:
>
> - `examples/data/newton_scene_manifest.json` and `newton_towers.json` —
>   committed in `b97ab41` and pushed, before the open-data replacement landed;
> - everything under `blender/` listed above — present since the **initial
>   commit `14fd043`**, so it is on the tip of **every** remote branch:
>   `main`, `publish/squashed`, `feat/scdt-paper-release`,
>   `feat/contributing-guidelines`, `andersonext/dso-66-security-scan` and
>   `update-dependabot-config`. PR #4 merged it to `main` on 2026-07-29.
>
> ⚠️ **Squashing does not fix this, and `publish/squashed` proves it.** That
> branch is already a single fresh commit with no prior history, and it still
> contains `blender/scene_build/scene_manifest.json`, `towers_near.json`,
> `mitsuba_scene/meshes/Buildings.ply`, the three `.blend` scenes, **and all
> eight developer-path leaks**. Rewriting history only removes what is *in the
> past*; these files are in the **working tree**, so they survive any squash. The
> untracking described above is the fix — a squash or rewrite is only needed
> afterwards, to reach the copies already in past commits.
>
> The second exposure is the harder one: because it reaches back to the root
> commit, a rewrite touches the entire history, not a recent slice. If the
> disclosure review requires these to be unrecoverable:
>
> ```bash
> git filter-repo --invert-paths \
>   --path examples/data/newton_scene_manifest.json \
>   --path examples/data/newton_towers.json \
>   --path blender/scene_build --path blender/mitsuba_scene \
>   --path blender/mitsuba_scene_terrain --path blender/sionna_out \
>   --path-glob 'blender/*.blend'
> ```
>
> followed by a coordinated force-push and a re-clone by every collaborator.
> That is destructive and shared-branch, so it is a maintainer decision, not an
> automatic one.
>
> **Order matters:** untrack first (done), then rebuild `publish/squashed` from
> the cleaned tree. A squash taken before the untracking — which is what the
> current `publish/squashed` is — carries the problem forward intact.

> **Wider than `examples/`.** The same pilot geometry is tracked in more places,
> and has been since the **initial commit `14fd043`** (present on
> `feat/scdt-paper-release`, `feat/contributing-guidelines` and
> `andersonext/dso-66-security-scan`):
>
> | Path | What it carries |
> |---|---|
> | `blender/scene_build/scene_manifest.json` | the same 576 footprints + LiDAR heights + DTM grid, no `provenance` block |
> | `blender/scene_build/towers_near.json` | the four pilot sites with positions and heights |
> | `blender/mitsuba_scene*/meshes/Buildings.ply` | the same footprints as extruded mesh geometry |
> | `blender/*.blend` | full Blender scenes containing the building geometry |
> | `blender/sionna_out/*` | the ray-traced figure set (duplicated in `docs/renders/`) |
>
> Removing the `examples/` copy does not settle the question for these. Whatever
> the review decides has to be applied across all of them, and the scrub in
> `eb9890b` did not cover them.

## Deliberately excluded

The following are **not** in this repository and will not be added:

- **Precise geometry or hazard return-period attributes for security-sensitive
  assets.** Named critical assets are excluded from any published derivative
  pending the government disclosure review.
- **`Pipe-Bursts-PhD-Barbados.pdf`** — a third-party doctoral thesis previously
  present in the working tree. We have no redistribution right to it. Obtain it
  from its author or publisher.
- **Any layer supplied under a bilateral arrangement** rather than from the
  public geoportal.


## Verification path for holders of the restricted data

The Barbados Geoportal layers cannot be redistributed, so a public clone cannot reproduce
the paper's Barbados numbers — but an institution that already holds the export can verify
this work end to end. `claims/restricted_artefact_checksums.json` records the MD5 of every
restricted-derived artefact in the pipeline (scene manifest, tower list, both Mitsuba
scenes, and the numeric output). Regenerate them from your own copy of the export with
`ulap-scope preprocess / build / export` and the checksums must match; then
`claims/verify_claims.py --rerun` must pass. If both hold, you have reproduced the paper
from sovereign data without either side transmitting it.

## Reproducibility note

Because the Barbados layers cannot be redistributed here, a third party cannot
reproduce the Barbados-specific figures byte-for-byte without obtaining those
layers. The pipeline itself is fully reproducible on **any** study area: run
`ulap-scope init` to define a new study anywhere in the world using the open
sources listed above. See the README's reproduction path.

## Third-party data licence assessment (ODbL share-alike)

Recorded so the redistribution boundary is a reviewed decision, not an accident.

- **What is distributed:** `examples/data/open_scene_mitsuba/meshes/Buildings.ply`
  (and the flat variant) — building geometry derived from OpenStreetMap, therefore a
  *derived database* under **ODbL 1.0** (share-alike). Terrain height samples derive
  from AWS Terrain Tiles (public domain per Mapzen/AWS terms). Everything else in the
  scene (materials, XML, exporter) is original code under Apache-2.0.
- **The boundary:** ODbL's share-alike applies to the *data files*, not to the source
  code that reads them, and not to produced works (rendered maps/figures) provided
  attribution is given. The repository is a *collective work*: Apache-2.0 covers the
  code; the two `.ply` derived databases remain under ODbL 1.0, stated in `NOTICE`.
  A consumer redistributing the repository must keep the NOTICE attribution and pass
  the ODbL terms along **for those files only** — this is the same boundary every
  OSM-derived extract (Geofabrik et al.) ships under.
- **Alternative considered:** not committing the meshes and fetching at build time
  (`export_mitsuba_direct.py` regenerates them byte-identically from the manifest —
  a test enforces this). Committing was chosen deliberately: a fresh clone must run
  the ray tracer with no network access, and the byte-identical-regeneration test
  keeps the committed artefact honest. The fetch-at-build path remains available to
  any downstream consumer who prefers not to redistribute ODbL data.
- **Reviewed:** G. Gichuru, 2026-07-30, against ODbL 1.0 §4.4–4.6 and the OSMF
  Community Guidelines on produced works vs derived databases. Revisit if the scene
  gains sources beyond OSM + AWS Terrain Tiles.
