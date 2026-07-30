# The open-data scene

A Mitsuba/Sionna RT scene of the Newton study area, built **entirely from openly
licensed data**, committed to this repository so that the ray-tracing path can be
run from a fresh clone.

It exists to close the gap recorded in [`VALIDATION.md`](VALIDATION.md), section
*"Reproducibility, stated honestly"*: the exported Barbados scenes were removed
during the pre-publication scrub because they derive from licence-restricted
government data, which left `benchmarks/run.sh` and the `rt`-marked tests needing
a scene the repository does not carry. This scene is that scene.

It is **not** a replacement for the Barbados scene, and its numbers are **not**
comparable to the Barbados numbers. See [Limitations](#limitations) — please read
that section before quoting anything from a run on this scene.

---

## What is committed

```
examples/data/open_scene_mitsuba/
├── scene.xml                    terrain variant (the default)
├── meshes/
│   ├── Terrain.ply              70 × 70 height mesh, true elevations
│   └── Buildings.ply            585 extruded OSM footprints, seated on terrain
└── flat/
    ├── scene.xml                flat variant (control: ground at z = 0)
    └── meshes/
        ├── Ground.ply           two triangles at z = 0
        └── Buildings.ply        the same footprints, 0 → h
```

| | terrain | flat |
|---|---|---|
| ground | 4 900 verts / 9 522 tris | 4 verts / 2 tris |
| buildings | 6 776 verts / 11 212 tris | 6 776 verts / 11 212 tris |
| x extent | −1 083.2 → 1 072.6 m | same |
| y extent | −1 092.8 → 1 061.6 m | same |
| z extent | 60.13 → 117.45 m (true elevation) | 0.00 → 8.00 m |
| size on disk | 402 KiB | 224 KiB |

**Total committed: 626 KiB (641 298 bytes) across 6 files.** That is small enough to carry
without comment. It stays small because there are no textures (see below) and
because the terrain grid is the manifest's own 70 × 70 posting rather than a
resampled surface — the input data does not support anything finer, so inventing
a denser mesh would only cost bytes.

### Conventions

* **Z-up, metres, scene-local coordinates** — Sionna's convention. Local
  `(0, 0)` is EPSG:32621 (UTM 21 N) easting **225 235.904 m**, northing
  **1 448 257.229 m**; the manifest already stores coordinates with that origin
  subtracted, and the georeference is repeated as a comment in each `scene.xml`.
* **Materials are named, not painted.** Buildings carry `mat-itu_concrete`,
  ground carries `mat-itu_medium_dry_ground` — the same names the Barbados
  exports use, so the assumptions baked into the Sionna stages still hold.
  Sionna converts any BSDF whose id begins `mat-itu_` into an
  `itu-radio-material` and discards the visual BSDF underneath.
* **No textures.** The basemap imagery in the original pipeline is not something
  we can redistribute, and the solver never reads it — an ITU radio material is
  defined by its permittivity and conductivity, not its colour.
* **Buildings are closed solids.** Every edge is shared by exactly two faces and
  the normals face outward (verified in `test_buildings_are_closed_solids`). An
  open box would let rays leak inside and reflect off interior surfaces.

---

## Regenerating it

The scene is a pure function of `examples/data/newton-open_scene_manifest.json`.
From the repository root, with any Python ≥ 3.10 — **no Blender, no third-party
packages, standard library only**:

```sh
cd ulap-scope
python -m ulap_scope.stages.export_mitsuba_direct \
    ../examples/data/newton-open_scene_manifest.json \
    ../examples/data/open_scene_mitsuba --mode terrain

python -m ulap_scope.stages.export_mitsuba_direct \
    ../examples/data/newton-open_scene_manifest.json \
    ../examples/data/open_scene_mitsuba/flat --mode flat
```

The output is byte-identical to what is committed; `test_scene_regenerates_byte_identical`
asserts exactly that, so the committed scene cannot silently drift from the code
that claims to produce it.

The exporter — [`ulap-scope/ulap_scope/stages/export_mitsuba_direct.py`](../ulap-scope/ulap_scope/stages/export_mitsuba_direct.py)
— deliberately does **not** use the existing `export_mitsuba.py`, which runs
inside Blender via `bpy` and the mitsuba-blender add-on. Extruding polygons and
meshing a height grid does not need a 3-D suite, and requiring one would put a
~1 GB dependency between a stranger and a reproducible result.

### Regenerating the manifest itself

The manifest is likewise reproducible, though it needs network access and the
`prep` extras (`geopandas`, `pyproj`, …):

```sh
python examples/data/fetch_open_scene.py \
    --lon -59.533908 --lat 13.088121 --half-width 1000 --name newton-open \
    -o examples/data/newton-open_scene_manifest.json
```

Re-fetching will **not** give you a byte-identical manifest: OpenStreetMap is
edited continuously, so the building count and geometry drift over time. The
committed manifest is the fixed input; treat a re-fetch as a new scene.

---

## Verifying it

```sh
cd ulap-scope
<python with sionna-rt==2.0.1> -m pytest -m rt tests/test_open_scene_rt.py -q
```

`tests/test_open_scene_rt.py` checks that the shipped scene loads, that both
`itu_` materials are recognised as `ITURadioMaterial`, that the bounding box is
in sensible local metres (a scene exported in degrees, in feet, or Y-up fails
here rather than quietly producing wrong physics), that the building mesh is a
closed solid, that the export is byte-reproducible, and that a `RadioMapSolver`
returns finite, non-empty coverage.

### A measurement from an actual solve

Not "it loads" — solved. Sionna RT 2.0.1, 3.5 GHz, `max_depth=5`,
`cell_size=(20, 20)`, 10⁶ samples per transmitter, both manifest antennas,
`tr38901` TX / `dipole` RX:

| variant | receiver plane | lit cells | median path gain | p5 | p95 |
|---|---|---|---|---|---|
| flat | z = 1.5 m | 10 320 / 11 664 (88.5 %) | **−113.7 dB** | −126.2 dB | −89.6 dB |
| terrain | z = 118.5 m | 10 338 / 11 664 (88.6 %) | **−115.0 dB** | −131.7 dB | −89.6 dB |

Buildings are doing real work rather than sitting in the file. Removing the
`Buildings` shape from the flat scene and re-solving, the per-cell path gain over
the 10 275 cells lit in both runs is on average **1.64 dB lower with the
buildings present**; the 5th percentile of that per-cell difference is −13.8 dB
and the most shadowed cell is −57.1 dB. Building presence also removes 344 cells
from coverage entirely (10 664 lit without, 10 320 with).

---

## Sources, licences and attribution

| Layer | Source | Licence |
|---|---|---|
| 585 building footprints | OpenStreetMap, via the Overpass API | **ODbL 1.0** |
| 70 × 70 terrain grid | AWS Terrain Tiles (`terrarium`, zoom 14) | open data; underlying SRTM / GMTED / 3DEP are **public domain** |
| transmitter positions | template shipped with `fetch_open_scene.py` | placeholders, not a data source |

**Attribution is required, not optional.** ODbL 1.0 is a share-alike licence.
Anything you publish that is made from this scene — a figure, a coverage map, a
derived dataset — must credit **© OpenStreetMap contributors** and point at
<https://www.openstreetmap.org/copyright>. If you redistribute a *derived
database* (not merely a rendered image of one), ODbL also requires you to offer
it under ODbL. The building meshes in this directory are such a derived
database; they are distributed here under ODbL 1.0 for that reason, separately
from the Apache-2.0 licence covering this repository's code.

The AWS Terrain Tiles are an aggregation of public-domain sources and impose no
attribution requirement, but crediting *AWS Terrain Tiles / SRTM, GMTED, 3DEP*
is the courteous and conventional thing to do.

Full provenance for every layer, including the exact bounding box and fetch
parameters, lives in the `provenance` block of the manifest.

---

## Limitations

These are real. Do not soften them when quoting results from this scene.

**Every building height is a guess.** All 585 footprints carry
`h_source = "default:*"` — not one of them has an OSM `height` or
`building:levels` tag. Heights come from a per-type default table
(`DEFAULT_HEIGHTS_M` in `fetch_open_scene.py`): `yes` → 4.5 m, `house` → 4.5 m,
`industrial` → 8 m, and so on, defaulting to 4.5 m. The resulting range is
4.0–8.0 m with a mean of 4.53 m. The Barbados scene's heights came from LiDAR.
This is the single largest fidelity difference between the two, and it acts
directly on diffraction and rooftop propagation.

**The terrain is ~30 m posting, not a LiDAR DTM.** AWS Terrain Tiles at zoom 14
resampled onto a 70 × 70 grid over 2 km — roughly 31 m between samples. It
captures the gross shape of the ground (60.07–116.99 m here) and nothing
smaller. Ridge crests are rounded, cuttings and embankments are absent.

**There is no open tower registry.** The two transmitters in the manifest are
**placeholders** from an editable template. Their coordinates, heights and
structure types are illustrative. Any absolute coverage number is therefore a
statement about those placeholder positions, not about a real network.

**OSM completeness is unknown and uneven.** Some areas are mapped
building-by-building; others have only major structures, or none. A missing
building is a missing obstruction. The count reproduces what OSM held on the
fetch date and nothing more.

**A flat plane over non-flat ground.** A Sionna radio map is a single horizontal
plane. On the terrain variant there is no plane that sits 1.5 m above ground
everywhere: put it at `zmin + 1.5` and it is buried under the hills (only 25.8 %
of cells receive energy — the rest are inside the terrain mesh, and that number
is an artefact of the geometry, not a coverage result); put it above the highest
ground and it is ~57 m up in the valleys. The measurement above uses the latter
and says so. Ground-following sampling is what `sionna_terrain_ground.py` is for.

**No vegetation, no vehicles, no interiors, no clutter.** Buildings are
homogeneous `itu_concrete` prisms with flat roofs; ground is uniform
`itu_medium_dry_ground`. Pitched roofs, balconies, walls, trees and material
variation are all absent.

**Buildings sit on the lowest ground under their footprint.** On a slope the
manifest gives one height per building, so the exporter seats each prism on the
minimum terrain sample beneath it and extrudes to `base + h`. Nothing floats,
but a building on a steep slope is partly buried, and its roof is `h` above the
*downhill* corner rather than above mean ground.

### On comparability

**Results computed on this scene are not comparable to the Barbados results and
must not be quoted as such.** Different building heights (defaults vs LiDAR),
different terrain (~30 m open data vs LiDAR DTM), different footprint set (585
OSM vs 576 government), different transmitter positions (placeholders vs
surveyed). Any agreement between the two would be coincidence, and any
disagreement would tell you nothing about either.

What this scene *is* good for: exercising the ray-tracing path end to end,
benchmarking solver performance on comparable geometry, regression-testing the
stages, and giving a stranger something to run. Those are the claims it
supports.
