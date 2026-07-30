#!/usr/bin/env python3
"""
preprocess_scene.py -- turn the clipped shapefiles + basemap into a Blender-ready
manifest, in scene-local metres relative to the .blend's EPSG:21292 origin.

Run with the geopandas python (conda base):
    ulap-scope preprocess          # or: $ULAP_PREP_PY -m ulap_scope.cli preprocess

Produces blender/scene_build/scene_manifest.json and GOOGLE_SAT_BNG.tif.
Includes a terrain grid interpolated from the building AVG_DTM (geoportal ground
elevation) so the scene can be built flat OR draped over real terrain.
"""
import json, os, shutil, subprocess

from ulap_scope.gdal_utils import gdal_tool, run_gdal
import numpy as np
import geopandas as gpd
from shapely.geometry import MultiPolygon
from scipy.interpolate import griddata

ROOT = os.environ.get("ULAP_PROJECT_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SA   = f"{ROOT}/bbd-geo-portal/study_area"
BUILD= f"{ROOT}/blender/scene_build"
os.makedirs(BUILD, exist_ok=True)


OX, OY = 32735.32016057213, 64854.73663833553   # scene origin in EPSG:21292 (from .blend)
EPSG = 21292

# ---- 1. basemap 3857 -> 21292 ----
src_tif = f"{ROOT}/blender/GOOGLE_SAT_WM.tif"
tmp_tif = f"{BUILD}/_basemap_3857.tif"
out_tif = f"{BUILD}/GOOGLE_SAT_BNG.tif"
run_gdal([gdal_tool("gdal_translate"),"-a_srs","EPSG:3857","-q",src_tif,tmp_tif])
run_gdal([gdal_tool("gdalwarp"),"-t_srs","EPSG:21292","-r","cubic","-overwrite","-q",
                "-dstalpha",tmp_tif,out_tif])
info = json.loads(run_gdal([gdal_tool("gdalinfo"),"-json",out_tif]).stdout)
cc = info["cornerCoordinates"]; W,H = info["size"]
xs = [cc["upperLeft"][0],cc["lowerRight"][0]]; ys=[cc["upperLeft"][1],cc["lowerRight"][1]]
basemap = {"tif":out_tif,"px_w":W,"px_h":H,
           "minx":min(xs)-OX,"maxx":max(xs)-OX,"miny":min(ys)-OY,"maxy":max(ys)-OY}

# ---- 2. buildings (rings, height, ground elevation) ----
b = gpd.read_file(f"{SA}/BuildingFootprints_study.shp")
def rings(geom):
    polys = geom.geoms if isinstance(geom,MultiPolygon) else [geom]
    return [[[x-OX,y-OY] for (x,y) in p.exterior.coords] for p in polys]
buildings=[]; cxs=[]; cys=[]; dtms=[]
for _,row in b.iterrows():
    h=row.get("AVG_HEIGHT"); h=float(h) if h and h>0 else 3.0
    dtm=row.get("AVG_DTM"); dtm=float(dtm) if dtm is not None else 0.0
    c=row.geometry.centroid
    for r in rings(row.geometry):
        buildings.append({"ring":r,"h":round(h,2),"dtm":round(dtm,2)})
    cxs.append(c.x-OX); cys.append(c.y-OY); dtms.append(dtm)

# ---- 3. terrain grid: interpolate AVG_DTM over the full extent ----
allx=[p[0] for bb in buildings for p in bb["ring"]]+[basemap["minx"],basemap["maxx"]]
ally=[p[1] for bb in buildings for p in bb["ring"]]+[basemap["miny"],basemap["maxy"]]
M=70
gx=np.linspace(min(allx),max(allx),M); gy=np.linspace(min(ally),max(ally),M)
GX,GY=np.meshgrid(gx,gy)
pts=np.column_stack([cxs,cys])
Z=griddata(pts,np.array(dtms),(GX,GY),method="linear")
Znear=griddata(pts,np.array(dtms),(GX,GY),method="nearest")
Z=np.where(np.isfinite(Z),Z,Znear)               # fill outside convex hull
terrain={"nx":M,"ny":M,"minx":float(gx[0]),"maxx":float(gx[-1]),
         "miny":float(gy[0]),"maxy":float(gy[-1]),
         "z":[round(float(v),2) for v in Z.ravel()],   # row-major, y outer
         "zmin":round(float(Z.min()),2),"zmax":round(float(Z.max()),2)}

def sample_terrain(x,y):
    return float(griddata(pts,np.array(dtms),(x,y),method="linear") or
                 griddata(pts,np.array(dtms),(x,y),method="nearest"))

# ---- 4. antennas (+ ground elevation under each tower) ----
a = gpd.read_file(f"{SA}/Antennas_study.shp")
antennas=[]
for _,row in a.iterrows():
    g=row.geometry; ax,ay=g.x-OX,g.y-OY
    gz=griddata(pts,np.array(dtms),(ax,ay),method="nearest")
    antennas.append({"name":str(row.get("SiteName","tower")),"x":ax,"y":ay,
                     "h":float(row.get("Height",20) or 20),
                     "ground_z":round(float(gz),2),
                     "structure":str(row.get("Structure",""))})

# A corrupt manifest silently poisons every downstream stage, so the write is
# guarded three ways: refuse obviously-empty results, keep the previous manifest
# as .bak, and land the new one atomically (temp file + os.replace) so a crash
# mid-write can never leave a half-written manifest behind.
if not buildings or not antennas:
    raise SystemExit(f"refusing to write manifest: buildings={len(buildings)} "
                     f"antennas={len(antennas)} — upstream data looks broken")
_mani_path = f"{BUILD}/scene_manifest.json"
_tmp_path = _mani_path + ".tmp"
with open(_tmp_path, "w") as _mf:
    json.dump({"epsg":EPSG,"origin":[OX,OY],"basemap":basemap,"terrain":terrain,
               "buildings":buildings,"antennas":antennas}, _mf)
with open(_tmp_path) as _mf:
    json.load(_mf)
try:
    shutil.copy2(_mani_path, _mani_path + ".bak")
except FileNotFoundError:
    pass  # first run: nothing to back up
os.replace(_tmp_path, _mani_path)
print(f"buildings:{len(buildings)}  terrain DTM {terrain['zmin']}..{terrain['zmax']} m  "
      f"({terrain['zmax']-terrain['zmin']:.1f} m relief)")
for an in antennas:
    print(f"  {an['name']:12s} ground_z={an['ground_z']} + h={an['h']}  -> tx_z={an['ground_z']+an['h']:.1f}")
print("wrote scene_manifest.json")
