#!/usr/bin/env python3
"""
fetch_basemap.py -- build a FULL-EXTENT satellite basemap for the scene.

The original Blender bake only covered ~2085x1184 m. This fetches ESRI World
Imagery tiles (publicly accessible) covering the whole 2 km building extent,
mosaics them, and reprojects to EPSG:21292 so the ground plane can be textured
edge-to-edge.

Run with conda base python (pyproj + PIL):
    ulap-scope basemap             # or: $ULAP_PREP_PY -m ulap_scope.cli basemap

Output: blender/scene_build/GOOGLE_SAT_BNG.tif (overwrites, full extent) and
updates basemap bounds in scene_manifest.json.
"""
import os, json, math, io, time, shutil, urllib.request, subprocess
from PIL import Image
from pyproj import Transformer

ROOT = os.environ.get("ULAP_PROJECT_ROOT", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUILD = f"{ROOT}/blender/scene_build"
ZOOM  = 18
TILE_URL = ("https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Imagery/MapServer/tile/{z}/{y}/{x}")
MERC = 20037508.342789244

def _run_gdal(cmd):
    """Run a GDAL CLI with actionable context on failure instead of a raw traceback."""
    try:
        return subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        raise SystemExit(f"fetch_basemap: {cmd[0]} failed (rc={e.returncode}) on "
                         f"{' '.join(cmd[1:])}\nstderr: {(e.stderr or '').strip()[-800:]}")


def _gdal(tool):
    """Resolve a GDAL CLI tool from $ULAP_GDAL_BIN or PATH (portable across OSes)."""
    override = os.environ.get("ULAP_GDAL_BIN")
    path = os.path.join(override, tool) if override else shutil.which(tool)
    if not path:
        raise SystemExit(
            f"{tool} not found. Install GDAL (on PATH) or set ULAP_GDAL_BIN to "
            "the directory containing the GDAL binaries."
        )
    return path

with open(f"{BUILD}/scene_manifest.json") as _mf:
    mani = json.load(_mf)
OX, OY = mani["origin"]

# ---- 1. full extent in local metres -> absolute 21292 -> lon/lat ----
xs = [p[0] for b in mani["buildings"] for p in b["ring"]]
ys = [p[1] for b in mani["buildings"] for p in b["ring"]]
pad = 80.0
minx = min(xs)-pad+OX; maxx = max(xs)+pad+OX
miny = min(ys)-pad+OY; maxy = max(ys)+pad+OY
to_ll = Transformer.from_crs(21292, 4326, always_xy=True)
corners = [to_ll.transform(x, y) for x in (minx, maxx) for y in (miny, maxy)]
lons = [c[0] for c in corners]; lats = [c[1] for c in corners]
lon0, lon1 = min(lons), max(lons); lat0, lat1 = min(lats), max(lats)
print(f"lon [{lon0:.5f},{lon1:.5f}] lat [{lat0:.5f},{lat1:.5f}]")

def deg2tile(lon, lat, z):
    n = 2**z
    xt = (lon+180.0)/360.0*n
    yt = (1.0 - math.log(math.tan(math.radians(lat))+1/math.cos(math.radians(lat)))/math.pi)/2.0*n
    return xt, yt
x0f, y0f = deg2tile(lon0, lat1, ZOOM)   # NW
x1f, y1f = deg2tile(lon1, lat0, ZOOM)   # SE
xt0, xt1 = int(math.floor(x0f)), int(math.floor(x1f))
yt0, yt1 = int(math.floor(y0f)), int(math.floor(y1f))
nx, ny = xt1-xt0+1, yt1-yt0+1
print(f"zoom {ZOOM}: {nx}x{ny} = {nx*ny} tiles")

# ---- 2. fetch + mosaic ----
mosaic = Image.new("RGB", (nx*256, ny*256))
def get(z, x, y, tries=3):
    url = TILE_URL.format(z=z, x=x, y=y)
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 digital-twin"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return Image.open(io.BytesIO(r.read())).convert("RGB")
        except Exception as e:
            if k == tries-1: print("  tile miss", x, y, e); return Image.new("RGB",(256,256),(40,40,40))
            time.sleep(0.6)
n_ok = 0
for j, yt in enumerate(range(yt0, yt1+1)):
    for i, xt in enumerate(range(xt0, xt1+1)):
        mosaic.paste(get(ZOOM, xt, yt), (i*256, j*256)); n_ok += 1
print(f"fetched {n_ok} tiles -> mosaic {mosaic.size}")
mos_png = f"{BUILD}/_mosaic_3857.png"; mosaic.save(mos_png)

# ---- 3. web-mercator bounds of the mosaic (tile edges) ----
def tile_merc_x(xt, z): return -MERC + xt/(2**z)*2*MERC
def tile_merc_y(yt, z): return  MERC - yt/(2**z)*2*MERC
ulx = tile_merc_x(xt0, ZOOM);   uly = tile_merc_y(yt0, ZOOM)
lrx = tile_merc_x(xt1+1, ZOOM); lry = tile_merc_y(yt1+1, ZOOM)

# ---- 4. georeference (3857) then warp to 21292 ----
tif3857 = f"{BUILD}/_mosaic_3857.tif"
out_tif = f"{BUILD}/GOOGLE_SAT_BNG.tif"
_run_gdal([_gdal("gdal_translate"),"-q","-a_srs","EPSG:3857",
           "-a_ullr",str(ulx),str(uly),str(lrx),str(lry),mos_png,tif3857])
_run_gdal([_gdal("gdalwarp"),"-q","-t_srs","EPSG:21292","-r","cubic",
           "-overwrite","-dstalpha",tif3857,out_tif])
info = json.loads(_run_gdal([_gdal("gdalinfo"),"-json",out_tif]).stdout)
cc = info["cornerCoordinates"]; W,H = info["size"]
bxs=[cc["upperLeft"][0],cc["lowerRight"][0]]; bys=[cc["upperLeft"][1],cc["lowerRight"][1]]
mani["basemap"] = {"tif":out_tif,"px_w":W,"px_h":H,
                   "minx":min(bxs)-OX,"maxx":max(bxs)-OX,
                   "miny":min(bys)-OY,"maxy":max(bys)-OY,"full_extent":True}
# same guarded write as preprocess_scene: temp file, validate, .bak, atomic replace
_mani_path = f"{BUILD}/scene_manifest.json"
_tmp_path = _mani_path + ".tmp"
with open(_tmp_path, "w") as _mf:
    json.dump(mani, _mf)
with open(_tmp_path) as _mf:
    json.load(_mf)
try:
    shutil.copy2(_mani_path, _mani_path + ".bak")
except FileNotFoundError:
    pass  # first run, or manifest removed since the read: nothing to back up
os.replace(_tmp_path, _mani_path)
print(f"wrote {out_tif}  ({W}x{H})  local bounds "
      f"x[{mani['basemap']['minx']:.0f},{mani['basemap']['maxx']:.0f}] "
      f"y[{mani['basemap']['miny']:.0f},{mani['basemap']['maxy']:.0f}]")
print("updated scene_manifest.json basemap -> full extent")
