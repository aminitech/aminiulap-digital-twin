# Barbados Digital Twin — Blender GIS to Sionna RT Pipeline

**Goal:** Build a georeferenced 3D scene of a study area in Barbados (satellite
imagery + real building footprints + cell towers) in Blender, then export it to
NVIDIA **Sionna RT** to ray-trace radio propagation and produce coverage maps.

**Reference video:** *Sionna RT: Scene Creation with Blender using OpenStreetMap*
(NVIDIA) — https://www.youtube.com/watch?v=7xHLDxUaQ7c

This guide uses the **official Barbados national geoportal data** instead of OSM,
which is higher quality (real LiDAR building heights, terrain elevation, and the
national antenna register).

---

## Pipeline at a glance

1. **Blender base scene** — install BlenderGIS, import the Google Satellite basemap, zoom to the study area, bake it (this defines/clips the scene extent).
2. **Vector data prep** — clip the country-wide building + antenna shapefiles to the study area and reproject them to the scene's CRS (Web Mercator). *(Done outside Blender with the included `clip_study_area.py`.)*
3. **Import buildings** — bring the clipped footprints in and extrude them to real heights.
4. **Terrain** *(optional)* — drape elevation so the ground isn't flat.
5. **Materials** — rename materials with Sionna's `itu_` prefix so they map to ITU radio materials.
6. **Export** — write the scene to Mitsuba XML with the Mitsuba-Blender add-on.
7. **Sionna RT** — load the scene, place transmitters (the real towers), compute paths and a radio/coverage map.

---

## 0. Prerequisites

| Component | Notes |
|---|---|
| Blender 4.x | Tested on 4.4.3 |
| **BlenderGIS** add-on | https://github.com/domlysz/BlenderGIS — download the ZIP, install via *Edit → Preferences → Add-ons → Install*, enable it. Adds a **GIS** menu to the 3D viewport header. |
| **Mitsuba-Blender** add-on | https://github.com/mitsuba-renderer/mitsuba-blender — needed only for the export step. Requires the `mitsuba` Python package. |
| Python env (for data prep) | `pip install geopandas` (pulls in pyproj/shapely). Used once to clip the shapefiles. |
| **Sionna** | `pip install sionna` (this guide targets **Sionna RT 2.0.1**). Needs a CUDA GPU for realistic run times. |

**Source data** (Barbados geoportal, `geo-portal/shapefiles/`):

- `BuildingFootprints/BuildingFootprints.shp` — 130,248 building polygons, CRS **EPSG:21292** (Barbados 1938 / Barbados National Grid). Fields: `AVG_HEIGHT` (m, LiDAR), `FLOORS`, `AVG_DTM` (ground elevation, m), `MIN_DTM`, `AREA`.
- `Telecommunications/Barbados_antennes_August2023.shp` — 100 antenna sites, CRS **EPSG:4326**. Fields: `SiteName`, `Structure`, `Height` (m), `Latitude`, `Longitude`.

---

## 1. Import the Google Satellite basemap (Blender)

1. Open a new Blender file. Delete the default cube if you like (not required).
2. **Check the scene CRS.** BlenderGIS defaults to **Web Mercator (EPSG:3857)**, which is what we use throughout. (*Edit → Preferences → Add-ons → BlenderGIS* lets you inspect the predefined CRS list.)
3. In the 3D viewport header open **GIS → Web geodata → Basemap**.
   - **Source:** Google
   - **Layer:** Satellite
   - Click **OK** to enter *map view* (an interactive modal — the header shows `Map view : Zoom NN`).
4. **Navigate to your study area.**
   - Scroll to zoom, drag to pan.
   - Press **G** to search for a place by name and jump there.
   - Aim for a zoom that frames roughly your intended area (e.g. Zoom 17 ≈ a ~1–2 km window).
5. **Bake the current view.** Press **E**. BlenderGIS converts the visible tiles into a georeferenced, textured plane object named **`GOOGLE_SAT_WM`**. You are now out of map view.
   - This baked extent is effectively your **scene clip** — everything downstream is built onto this plane.
6. **Record the centre coordinate.** The map-view header showed a Web Mercator centre such as `(-6626718, 1470428)`. Keep it — you'll feed it to the clip script in Step 2.

> **Study area used in this guide:** centre `(-6626718, 1470428)` in Web Mercator ≈ **13.0936° N, 59.5288° W** (south-central Barbados). A **2 km box** around it contains **162 buildings** and the **Rising Sun** cell tower (24 m monopole, ~970 m from centre).

---

## 2. Clip and reproject the vector data (outside Blender)

The country-wide building file is far too large to import whole (130k buildings),
and it's in a **different CRS** (Barbados grid, EPSG:21292) than the scene
(Web Mercator, EPSG:3857). So we clip to the study area and reproject **once**,
using the included `clip_study_area.py`.

1. Put `clip_study_area.py` next to your `geo-portal/` folder (or edit the paths in its CONFIG block).
2. Set the CONFIG values:
   - `CENTER_MERCATOR` = the coordinate from Step 1.6 (or set `CENTER_LONLAT` instead).
   - `HALF_WIDTH_M = 1000` → a **2 km** box (use 750 for 1.5 km, 1500 for 3 km).
3. Run it:
   ```bash
   pip install geopandas          # first time only
   python3 clip_study_area.py
   ```
4. Output (in `geo-portal/study_area/`), all in **EPSG:3857**:
   - `BuildingFootprints_study.shp` (+ .shx/.dbf/.prj/.cpg) — keeps `AVG_HEIGHT`, `FLOORS`, `AVG_DTM`.
   - `Antennas_study.shp` — towers in/near the box.
   - `antennas_TX.csv` — `SiteName, Structure, Height, Latitude, Longitude` for scripting Sionna transmitters.

**Why reproject to Web Mercator?** The scene and basemap are in Web Mercator, so
matching the vector CRS makes the buildings overlay the imagery exactly with no
in-Blender reprojection guesswork.

> **Accuracy caveat.** Web Mercator stretches horizontal distances by `1/cos(lat)`
> ≈ **2.6%** at 13° N. Fine for learning and for following the video. For
> physically exact path lengths, rebuild the scene in a **true-metre** CRS
> (UTM 20N / EPSG:32620, or the Barbados grid EPSG:21292) and clip to that CRS
> instead — set `TARGET_CRS` accordingly and set the same CRS as the BlenderGIS
> scene CRS before importing the basemap.

---

## 3. Import the buildings (Blender)

1. **GIS → Import → Shapefile (.shp)**, choose `study_area/BuildingFootprints_study.shp`.
2. In the **Import SHP** dialog:

   | Field | Setting | Why |
   |---|---|---|
   | **Extrusion from field** | ✅ checked → `AVG_HEIGHT` | Turns flat footprints into 3D volumes at real LiDAR heights. |
   | **Elevation source** | **None** (flat) *for now* | Basemap is a flat plane at z=0; this seats building bases on it. Switch to **Field → `AVG_DTM`** only after you add real terrain (Step 4), else buildings float ~80–110 m. |
   | **Separate objects** | ☐ unchecked | One merged mesh exports far more cleanly to Sionna. |
   | **Specify shapefile CRS** | ☐ unchecked | Already reprojected to Web Mercator; the `.prj` matches the scene. Only tick it (→ Web Mercator) if buildings land in the wrong place. |
   | **Scene georeferencing / CRS / Origin** | leave as-is | Inherited correctly from the basemap import — do not reset. |

3. Click **OK**. ~162 building blocks should drop onto the rooftops in the imagery.
4. **Verify** the overlay: switch to top view (Numpad 7), toggle wireframe/solid, confirm buildings sit on their satellite rooftops. If offset or missing → re-import with **Specify shapefile CRS = Web Mercator**.

*(Optional)* Import `Antennas_study.shp` the same way (Elevation source **None**) so
you have the tower points in-scene — handy for reading their local coordinates in Step 7.

---

## 4. Terrain (optional refinement)

Flat ground is fine for a first end-to-end run. For realistic line-of-sight over
Barbados' rolling terrain:

- **Option A — SRTM via BlenderGIS:** select `GOOGLE_SAT_WM`, then **GIS → Web geodata → Get elevation (SRTM)**. (Recent versions fetch from OpenTopography and may require a free API key set in the add-on preferences.) This subdivides and displaces the basemap into a terrain mesh.
- **Option B — use the building `AVG_DTM`:** re-import buildings with **Elevation source → Field → `AVG_DTM`** so each footprint sits at its true ground elevation, and add a ground plane/terrain to match.

After adding terrain, make sure building bases and terrain share the same vertical
datum (the geoportal `AVG_DTM` is metres above sea level).

---

## 5. Assign Sionna materials (the `itu_` rule)

Sionna maps a material to an **ITU radio material** by **name**: the Blender
material name must start with **`itu_`**. Anything else becomes a generic
`RadioMaterial` with no ITU permittivity/conductivity, so ray interactions are
not physically meaningful.

Practical assignment for this scene (in the **Material Properties** tab, rename
the material slot):

| Object | Material name | ITU type |
|---|---|---|
| Buildings | `itu_concrete` (or `itu_brick`) | concrete / brick |
| Ground / terrain | `itu_medium_dry_ground` | medium dry ground |
| Tower structures / metal | `itu_metal` | metal |
| Reservoir / water | `itu_water` | water |

Common valid names: `itu_concrete`, `itu_brick`, `itu_marble`, `itu_glass`,
`itu_wood`, `itu_metal`, `itu_very_dry_ground`, `itu_medium_dry_ground`,
`itu_wet_ground`, `itu_water`. (You can also override per object in Python after
loading: `obj.radio_material = "itu_wet_ground"` — underscores, not hyphens.)

Give every object at least one `itu_`-named material before exporting.

---

## 6. Export to Mitsuba XML

1. Enable the **Mitsuba-Blender** add-on (install the `mitsuba` pip package into Blender's Python if prompted).
2. **File → Export → Mitsuba (.xml)**.
3. In the export options:
   - Keep Blender's **Z-up** convention (Up = **Z**, Forward = **Y**) — Sionna expects Z-up.
   - Enable exporting IDs/materials so your `itu_` names survive into the XML.
   - Export unit = metres.
4. This writes `scene.xml` plus a `meshes/` folder (and textures). Keep them together.

The XML BSDF for an ITU material looks like:
```xml
<bsdf type="itu-radio-material" id="mat-itu_concrete">
    <string name="type" value="concrete"/>
</bsdf>
```
The Mitsuba-Blender exporter + Sionna's loader handle this from the `itu_`-named
material; you normally don't hand-edit the XML.

---

## 7. Load in Sionna RT and compute coverage

Targets **Sionna RT 2.0.1**. Place the transmitter at your real tower
(**Rising Sun**, 24 m). Easiest way to get the TX position in scene-local metres:
in Blender, select the imported Rising Sun antenna point and read its **X, Y** from
the N-panel (item tab); use the tower height for **Z**.

```python
import sionna.rt
from sionna.rt import (load_scene, PlanarArray, Transmitter, Receiver,
                       PathSolver, RadioMapSolver)

# 1. Load the exported scene
scene = load_scene("path/to/scene.xml")   # your Mitsuba export
scene.frequency = 3.5e9                     # e.g. 3.5 GHz (5G mid-band)

# 2. Antenna arrays (single element to start)
scene.tx_array = PlanarArray(num_rows=1, num_cols=1,
                             vertical_spacing=0.5, horizontal_spacing=0.5,
                             pattern="tr38901", polarization="V")
scene.rx_array = PlanarArray(num_rows=1, num_cols=1,
                             vertical_spacing=0.5, horizontal_spacing=0.5,
                             pattern="dipole", polarization="V")

# 3. Transmitter = the Rising Sun monopole.
#    Replace [x, y] with the antenna's scene-local coords from Blender (N-panel);
#    z = tower height (24 m) above its ground point.
tx = Transmitter(name="rising_sun", position=[X, Y, 24.0], display_radius=3)
scene.add(tx)

# (optional) a probe receiver
rx = Receiver(name="rx", position=[X + 200, Y + 50, 1.5], display_radius=2)
scene.add(rx)

# 4. Propagation paths (LoS + a few reflections)
p_solver = PathSolver()
paths = p_solver(scene=scene, max_depth=5, los=True,
                 specular_reflection=True, diffuse_reflection=False,
                 refraction=True, synthetic_array=False, seed=41)

# 5. Coverage / radio map over the whole scene
rm_solver = RadioMapSolver()
rm = rm_solver(scene=scene, max_depth=5, cell_size=[5, 5],
               samples_per_tx=10**6)

# 6. Visualise (opens/renders the scene with the radio map overlaid)
scene.render(camera="preview", radio_map=rm)   # or scene.preview(...) in a notebook
```

Tune from here: sweep `scene.frequency`, raise `max_depth` for more reflections,
add all nearby towers as transmitters (from `antennas_TX.csv`), shrink `cell_size`
for a finer map, and read path gains / delay spread from `paths`.

---

## Appendix A — Study-area reference

| Item | Value |
|---|---|
| Centre (Web Mercator, EPSG:3857) | `-6626718, 1470428` |
| Centre (lon, lat) | `-59.5288, 13.0936` |
| Box size | 2 km (half-width 1000 m) |
| Buildings in box | 162 (heights 1.8–7.8 m; terrain 80.7–110.0 m) |
| Scene CRS | Web Mercator (EPSG:3857) |

**Nearby towers (transmitter candidates):**

| Site | Structure | Height (m) | ~Dist from centre |
|---|---|---|---|
| Rising Sun | Monopole | 24 | 970 m |
| Newton | Monopole | 30 | 1611 m |
| Boarded Hall | Cell-on-Wheels | 15 | 2328 m |

## Appendix B — CRS reference

| Layer | Native CRS | Notes |
|---|---|---|
| Google Satellite basemap | EPSG:3857 (Web Mercator) | Blender scene CRS |
| BuildingFootprints | EPSG:21292 (Barbados 1938 Grid) | reprojected to 3857 in Step 2 |
| Antennas | EPSG:4326 (WGS84 lat/lon) | reprojected to 3857 in Step 2 |

## Appendix C — Troubleshooting

- **Buildings don't appear / wrong location:** re-import with *Specify shapefile CRS = Web Mercator*; confirm the `.prj` is present next to the `.shp`.
- **Buildings float above the ground:** you set Elevation source to a field/geometry with real elevations but the ground is flat. Use **None** for flat ground, or add terrain (Step 4).
- **Everything is tiny/huge:** check the Blender scene unit scale and the BlenderGIS "Map scale" (should be 1).
- **Sionna: "radio-material not found":** a material wasn't `itu_`-named, or an object has no material. Name every material `itu_*` before export.
- **Sionna scene loads but is black/empty in preview:** check the Mitsuba export used Z-up and metres, and that meshes exported alongside the XML.

---

*Sources: NVIDIA Sionna RT 2.0.1 docs (Introduction tutorial, radio materials),
NVLabs/sionna discussion #905 on Blender material naming, and the Barbados
national geoportal shapefiles.*
