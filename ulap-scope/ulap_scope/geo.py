"""
ulap_scope.geo -- pure, dependency-light geospatial + geometry helpers.

These are the mathematically meaningful pieces of the pipeline (coordinate
transforms, terrain interpolation, footprint validation, manifest schema). They
are kept free of Blender / Sionna / GDAL so they import in any environment and
are cheap to unit-test. Only numpy is required; scipy is used lazily by
`interpolate_dtm` and imported inside the function.
"""
from __future__ import annotations
from typing import Iterable, Sequence
import numpy as np

# --------------------------------------------------------------------- coords
def to_local(x, y, origin):
    """CRS coordinate -> scene-local metres (origin maps to Blender 0,0)."""
    return x - origin[0], y - origin[1]

def to_crs(x_local, y_local, origin):
    """Scene-local metres -> absolute CRS coordinate (inverse of to_local)."""
    return x_local + origin[0], y_local + origin[1]

# --------------------------------------------------------------------- terrain
def terrain_bilinear(terrain: dict, x, y):
    """Bilinear sample of the row-major AVG_DTM grid at local (x, y).

    `terrain` is the manifest 'terrain' dict: nx, ny, minx/maxx/miny/maxy, z
    (row-major, y outer). Coordinates are clamped to the grid extent. Accepts
    scalars or numpy arrays (vectorised)."""
    nx, ny = terrain["nx"], terrain["ny"]
    z = np.asarray(terrain["z"], dtype=float).reshape(ny, nx)
    x = np.asarray(x, dtype=float); y = np.asarray(y, dtype=float)
    fx = (x - terrain["minx"]) / (terrain["maxx"] - terrain["minx"]) * (nx - 1)
    fy = (y - terrain["miny"]) / (terrain["maxy"] - terrain["miny"]) * (ny - 1)
    fx = np.clip(fx, 0, nx - 1); fy = np.clip(fy, 0, ny - 1)
    ix = fx.astype(int); iy = fy.astype(int)
    ix1 = np.minimum(ix + 1, nx - 1); iy1 = np.minimum(iy + 1, ny - 1)
    tx = fx - ix; ty = fy - iy
    out = (z[iy, ix]   * (1 - tx) * (1 - ty) +
           z[iy, ix1]  * tx       * (1 - ty) +
           z[iy1, ix]  * (1 - tx) * ty +
           z[iy1, ix1] * tx       * ty)
    return float(out) if out.ndim == 0 else out

def interpolate_dtm(pts_xy, dtms, grid_x, grid_y):
    """Interpolate scattered AVG_DTM samples onto a regular grid (linear, with a
    nearest-neighbour fill outside the convex hull). Returns z[ny, nx]."""
    from scipy.interpolate import griddata
    pts = np.asarray(pts_xy, dtype=float); vals = np.asarray(dtms, dtype=float)
    GX, GY = np.meshgrid(np.asarray(grid_x), np.asarray(grid_y))
    z = griddata(pts, vals, (GX, GY), method="linear")
    znear = griddata(pts, vals, (GX, GY), method="nearest")
    return np.where(np.isfinite(z), z, znear)

# --------------------------------------------------------------- footprints
def clean_ring(ring: Sequence[Sequence[float]]):
    """Drop a closing duplicate vertex; return the ring or None if degenerate
    (fewer than 3 distinct vertices -> cannot form a face)."""
    r = list(ring)
    if len(r) >= 2 and list(r[0]) == list(r[-1]):
        r = r[:-1]
    if len(r) < 3:
        return None
    uniq = {(round(px, 6), round(py, 6)) for px, py in r}
    return r if len(uniq) >= 3 else None

def ring_is_valid(ring) -> bool:
    return clean_ring(ring) is not None

# --------------------------------------------------------------- frequencies
# ITU-R P.2040 validity windows used by Sionna's ITU materials (GHz).
ITU_FREQ_RANGES_GHZ = {
    "concrete": (1.0, 100.0), "brick": (1.0, 40.0), "glass": (0.1, 100.0),
    "metal": (1.0, 100.0), "medium_dry_ground": (1.0, 10.0),
    "wet_ground": (1.0, 10.0), "very_dry_ground": (1.0, 10.0),
}

def freq_valid_for(material: str, freq_hz: float) -> bool:
    """True if `freq_hz` is inside the ITU validity window for `material`."""
    lo, hi = ITU_FREQ_RANGES_GHZ[material]
    return lo <= freq_hz / 1e9 <= hi

# ---------------------------------------------------------------- manifest
REQUIRED_MANIFEST_KEYS = ("epsg", "origin", "basemap", "terrain", "buildings", "antennas")

def validate_manifest(m: dict) -> list[str]:
    """Return a list of problems with a scene manifest (empty == valid)."""
    errs = []
    for k in REQUIRED_MANIFEST_KEYS:
        if k not in m:
            errs.append(f"missing key: {k}")
    if errs:
        return errs
    if m["epsg"] != 21292:
        errs.append(f"epsg should be 21292, got {m['epsg']}")
    if len(m["origin"]) != 2:
        errs.append("origin must be [x, y]")
    if not m["buildings"]:
        errs.append("no buildings")
    for i, b in enumerate(m["buildings"][:50]):
        if "ring" not in b or "h" not in b:
            errs.append(f"building {i} missing ring/h"); break
    t = m["terrain"]
    if t["zmin"] > t["zmax"]:
        errs.append("terrain zmin > zmax")
    if len(t["z"]) != t["nx"] * t["ny"]:
        errs.append("terrain z length != nx*ny")
    bm = m["basemap"]
    if not (bm["maxx"] > bm["minx"] and bm["maxy"] > bm["miny"]):
        errs.append("basemap bounds not positive")
    for a in m["antennas"]:
        if not all(k in a for k in ("name", "x", "y", "h")):
            errs.append(f"antenna missing fields: {a.get('name','?')}"); break
    return errs
