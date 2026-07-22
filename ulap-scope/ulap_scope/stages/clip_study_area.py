#!/usr/bin/env python3
"""
clip_study_area.py
------------------
Reusable helper for the Barbados digital-twin / Sionna RT pipeline.

Clips the national BuildingFootprints + antenna shapefiles to a study-area
box around a chosen centre, and outputs them in the Barbados 1938 / British
West Indies Grid (EPSG:21292) -- a true-metre projected CRS -- for accurate
distances in the Sionna RT scene. (Set TARGET_CRS = 3857 to instead match a
Web Mercator BlenderGIS Google-Satellite basemap.)

Requires: geopandas, pyproj, shapely   (pip install geopandas)

Usage (edit the CONFIG block, then run):
    python3 clip_study_area.py
"""
import os
import geopandas as gpd
from pyproj import Transformer

# ----------------------------- CONFIG -----------------------------
# Study-area centre = Newton Burial Site, Barbados.
# Values match the BlenderGIS scene custom properties (Web Mercator / EPSG:3857).
CENTER_MERCATOR = (-6627166, 1469728)   # (x, y) EPSG:3857  -- from Blender map view (crs x / crs y)
CENTER_LONLAT   = None                  # e.g. (-59.533, 13.087); leave None to use Mercator
HALF_WIDTH_M    = 1000                   # half box size in metres (1000 => 2 km box)

# Paths are resolved relative to the repo root (the parent of this script's
# blender/ folder), so the script runs correctly from any working directory.
REPO_ROOT = os.environ.get("ULAP_PROJECT_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUILDINGS_SHP = os.path.join(REPO_ROOT, "bbd-geo-portal/shapefiles/BuildingFootprints/BuildingFootprints.shp")
ANTENNAS_SHP  = os.path.join(REPO_ROOT, "bbd-geo-portal/shapefiles/Telecommunications/Barbados_antennes_August2023.shp")
OUT_DIR       = os.path.join(REPO_ROOT, "bbd-geo-portal/study_area")

TARGET_CRS = 21292                       # Barbados 1938 / British West Indies Grid (true metres)
ANTENNA_MARGIN_M = 800                    # also capture towers just outside the box
# ------------------------------------------------------------------

os.makedirs(OUT_DIR, exist_ok=True)

# Resolve the centre in the buildings' native CRS so the box is in true metres.
b_native_crs = gpd.read_file(BUILDINGS_SHP, rows=1).crs        # e.g. EPSG:21292
if CENTER_LONLAT:
    cx, cy = Transformer.from_crs(4326, b_native_crs, always_xy=True).transform(*CENTER_LONLAT)
else:
    cx, cy = Transformer.from_crs(3857, b_native_crs, always_xy=True).transform(*CENTER_MERCATOR)

hw = HALF_WIDTH_M
box = (cx - hw, cy - hw, cx + hw, cy + hw)

# --- Buildings: clip in native CRS, keep useful fields, reproject to target ---
b = gpd.read_file(BUILDINGS_SHP, bbox=box)
keep = [c for c in ["OBJECTID", "AVG_HEIGHT", "FLOORS", "AVG_DTM", "MIN_DTM", "AREA", "geometry"]
        if c in b.columns]
b = b[keep].to_crs(TARGET_CRS)
b.to_file(f"{OUT_DIR}/BuildingFootprints_study.shp")
print(f"buildings: {len(b)} clipped -> EPSG:{TARGET_CRS}")

# --- Antennas: filter to box + margin, reproject, plus a lat/lon CSV for Sionna ---
a = gpd.read_file(ANTENNAS_SHP).to_crs(b_native_crs)
m = hw + ANTENNA_MARGIN_M
sel = a.cx[cx - m:cx + m, cy - m:cy + m].copy().to_crs(TARGET_CRS)
sel.to_file(f"{OUT_DIR}/Antennas_study.shp")

csv = gpd.read_file(ANTENNAS_SHP)
cols = [c for c in ["SiteName", "Structure", "Height", "Latitude", "Longitude"] if c in csv.columns]
csv[csv.index.isin(a.cx[cx - m:cx + m, cy - m:cy + m].index)][cols] \
    .to_csv(f"{OUT_DIR}/antennas_TX.csv", index=False)
print(f"antennas: {len(sel)} in area -> {OUT_DIR}/antennas_TX.csv")
print("done ->", OUT_DIR)
