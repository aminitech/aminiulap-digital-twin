"""
ulap_demo.scene -- load the sample twin and turn it into arrays you can compute on.

The scene manifest is what ``ulap-scope preprocess`` writes: everything in
**scene-local metres** (add ``origin`` to get EPSG:21292 Barbados National Grid),
a row-major terrain grid, one entry per building footprint with its LiDAR height,
and the towers.

The one non-obvious piece here is :meth:`Scene.height_raster`, which burns the
576 footprints into a raster of "how high is the world at this pixel". Ray
tracers do this with real geometry; for a fast analytical model a raster is
enough, and rasterising it ourselves keeps the demo free of GDAL/shapely.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


def _data_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "data"


# --------------------------------------------------------------------- towers
@dataclass(frozen=True)
class Tower:
    """A transmit site. ``x``/``y`` are scene-local metres, ``h`` is the antenna
    height *above local ground*, ``ground_z`` the terrain height under it."""

    name: str
    x: float
    y: float
    h: float
    ground_z: float = 0.0
    structure: str = "Monopole"
    in_scene: bool = True

    @property
    def z(self) -> float:
        """Absolute antenna height (metres above the terrain datum)."""
        return self.ground_z + self.h

    @property
    def slug(self) -> str:
        return self.name.lower().replace(" ", "_")


# ---------------------------------------------------------------------- scene
@dataclass
class Scene:
    """A loaded digital twin: terrain grid, building footprints, towers."""

    name: str
    epsg: int
    origin: tuple[float, float]
    terrain: dict
    buildings: list[dict]
    towers: list[Tower]
    provenance: dict = field(default_factory=dict, repr=False)
    source_path: Path | None = None
    _rasters: dict = field(default_factory=dict, repr=False)

    # -- basic geometry ----------------------------------------------------
    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """(minx, maxx, miny, maxy) of the terrain grid, in local metres."""
        t = self.terrain
        return (t["minx"], t["maxx"], t["miny"], t["maxy"])

    @property
    def extent(self) -> list[float]:
        """Bounds in matplotlib ``imshow(extent=...)`` order."""
        minx, maxx, miny, maxy = self.bounds
        return [minx, maxx, miny, maxy]

    @property
    def size_m(self) -> tuple[float, float]:
        minx, maxx, miny, maxy = self.bounds
        return (maxx - minx, maxy - miny)

    def to_crs(self, x, y):
        """Scene-local metres -> absolute CRS coordinate (EPSG:``self.epsg``)."""
        return np.asarray(x) + self.origin[0], np.asarray(y) + self.origin[1]

    def towers_in_scene(self) -> list[Tower]:
        return [t for t in self.towers if t.in_scene]

    def tower(self, name: str) -> Tower:
        key = name.lower().replace(" ", "_")
        for t in self.towers:
            if t.slug == key:
                return t
        raise KeyError(f"no tower named {name!r} (have: {[t.name for t in self.towers]})")

    # -- terrain -----------------------------------------------------------
    @property
    def terrain_z_grid(self) -> np.ndarray:
        """Terrain heights as ``z[ny, nx]`` (row-major, y increasing with row)."""
        t = self.terrain
        return np.asarray(t["z"], dtype=float).reshape(t["ny"], t["nx"])

    def terrain_z(self, x, y):
        """Bilinear terrain height at local (x, y). Vectorised; clamps to grid.

        Delegates to :func:`ulap_scope.geo.terrain_bilinear` when the pipeline
        package is importable, so the demo and the pipeline can never disagree
        about what the ground is doing."""
        try:
            from ulap_scope.geo import terrain_bilinear
        except ImportError:
            return _terrain_bilinear_fallback(self.terrain, x, y)
        return terrain_bilinear(self.terrain, x, y)

    # -- buildings ---------------------------------------------------------
    def building_rings(self) -> list[np.ndarray]:
        return [np.asarray(b["ring"], dtype=float) for b in self.buildings]

    def building_heights(self) -> np.ndarray:
        return np.array([b["h"] for b in self.buildings], dtype=float)

    def height_raster(self, cell_m: float = 5.0) -> "HeightRaster":
        """Rasterise terrain + building extrusions at ``cell_m`` resolution.

        Cached per resolution: the first call for a given cell size does the
        polygon fill, later calls are free."""
        key = round(float(cell_m), 3)
        if key not in self._rasters:
            self._rasters[key] = _build_height_raster(self, key)
        return self._rasters[key]

    # -- sampling grid -----------------------------------------------------
    def grid(self, cell_m: float = 10.0):
        """Regular sample grid over the scene: ``(X, Y, extent)``.

        ``X``/``Y`` are 2-D arrays shaped (ny, nx) with y increasing along rows,
        matching ``imshow(..., origin='lower')``."""
        minx, maxx, miny, maxy = self.bounds
        xs = np.arange(minx + cell_m / 2, maxx, cell_m)
        ys = np.arange(miny + cell_m / 2, maxy, cell_m)
        X, Y = np.meshgrid(xs, ys)
        extent = [xs[0] - cell_m / 2, xs[-1] + cell_m / 2,
                  ys[0] - cell_m / 2, ys[-1] + cell_m / 2]
        return X, Y, extent

    def summary(self) -> str:
        h = self.building_heights()
        w, d = self.size_m
        t = self.terrain
        return (
            f"{self.name}: {w:.0f} x {d:.0f} m study box, EPSG:{self.epsg}\n"
            f"  buildings : {len(self.buildings)}  "
            f"(height {h.min():.1f}-{h.max():.1f} m, mean {h.mean():.1f} m)\n"
            f"  terrain   : {t['nx']}x{t['ny']} grid, "
            f"{t['zmin']:.1f}-{t['zmax']:.1f} m ({t['zmax'] - t['zmin']:.0f} m of relief)\n"
            f"  towers    : " + ", ".join(
                f"{tw.name} ({tw.h:.0f} m{'' if tw.in_scene else ', outside box'})"
                for tw in self.towers)
            + f"\n  source    : {self.source_path}"
        )

    def sources(self) -> str:
        """Human-readable provenance: where every layer in this scene came from
        and under what licence. A manifest written by the pipeline itself has no
        provenance block, so this reports the file path instead."""
        p = self.provenance
        if not p:
            return (f"{self.name}: no provenance block recorded — this manifest "
                    f"came from {self.source_path}")
        out = [f"{p.get('name', self.name)} — built by {p.get('generator', '?')}"]
        for layer in ("buildings", "terrain", "towers"):
            info = p.get(layer)
            if not info:
                continue
            out.append(f"  {layer:<10} {info.get('source', '?')}")
            for key in ("licence", "note", "height_note"):
                if info.get(key):
                    out.append(f"  {'':<10} {key.replace('_', ' ')}: {info[key]}")
        return "\n".join(out)


@dataclass
class HeightRaster:
    """Top-of-world height per pixel, plus the ground underneath it.

    ``ground`` is terrain only; ``top`` is terrain + building extrusion. Both are
    (ny, nx) with y increasing along rows."""

    ground: np.ndarray
    top: np.ndarray
    minx: float
    miny: float
    cell_m: float

    @property
    def building_height(self) -> np.ndarray:
        """Extrusion height above ground per pixel (0 where there is no building)."""
        return self.top - self.ground

    def sample_top(self, x, y) -> np.ndarray:
        """Nearest-neighbour lookup of the top surface. Out-of-bounds clamps."""
        return self._sample(self.top, x, y)

    def sample_ground(self, x, y) -> np.ndarray:
        return self._sample(self.ground, x, y)

    def _sample(self, arr: np.ndarray, x, y) -> np.ndarray:
        ny, nx = arr.shape
        ix = np.clip(((np.asarray(x) - self.minx) / self.cell_m).astype(int), 0, nx - 1)
        iy = np.clip(((np.asarray(y) - self.miny) / self.cell_m).astype(int), 0, ny - 1)
        return arr[iy, ix]

    @property
    def extent(self) -> list[float]:
        ny, nx = self.top.shape
        return [self.minx, self.minx + nx * self.cell_m,
                self.miny, self.miny + ny * self.cell_m]


# ------------------------------------------------------------------ rasterise
def _fill_polygon(mask_shape, ring_px) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    """Even-odd scanline fill of one polygon given in pixel coordinates.

    Returns a boolean mask over the polygon's bounding box plus that box, so we
    never allocate a full-scene array per building."""
    ny, nx = mask_shape
    xs, ys = ring_px[:, 0], ring_px[:, 1]
    x0 = max(int(np.floor(xs.min())), 0)
    x1 = min(int(np.ceil(xs.max())) + 1, nx)
    y0 = max(int(np.floor(ys.min())), 0)
    y1 = min(int(np.ceil(ys.max())) + 1, ny)
    if x1 <= x0 or y1 <= y0:
        return np.zeros((0, 0), bool), (0, 0, 0, 0)

    sub = np.zeros((y1 - y0, x1 - x0), bool)
    n = len(ring_px)
    # Scanline through pixel centres; a pixel is inside when an odd number of
    # edges lie to its left. Standard even-odd rule, vectorised per row.
    cols = np.arange(x0, x1) + 0.5
    for row in range(y0, y1):
        yc = row + 0.5
        xints = []
        for i in range(n):
            xa, ya = ring_px[i]
            xb, yb = ring_px[(i + 1) % n]
            if (ya > yc) != (yb > yc):          # edge straddles this scanline
                t = (yc - ya) / (yb - ya)
                xints.append(xa + t * (xb - xa))
        if not xints:
            continue
        xints = np.sort(np.asarray(xints))
        inside = np.searchsorted(xints, cols, side="right") % 2 == 1
        sub[row - y0] = inside
    return sub, (x0, x1, y0, y1)


def _build_height_raster(scene: Scene, cell_m: float) -> HeightRaster:
    minx, maxx, miny, maxy = scene.bounds
    nx = max(int(np.ceil((maxx - minx) / cell_m)), 1)
    ny = max(int(np.ceil((maxy - miny) / cell_m)), 1)

    xs = minx + (np.arange(nx) + 0.5) * cell_m
    ys = miny + (np.arange(ny) + 0.5) * cell_m
    X, Y = np.meshgrid(xs, ys)
    ground = np.asarray(scene.terrain_z(X, Y), dtype=float)
    top = ground.copy()

    for b in scene.buildings:
        ring = np.asarray(b["ring"], dtype=float)
        ring_px = np.column_stack([(ring[:, 0] - minx) / cell_m,
                                   (ring[:, 1] - miny) / cell_m])
        sub, (x0, x1, y0, y1) = _fill_polygon((ny, nx), ring_px)
        if sub.size == 0 or not sub.any():
            # Footprint smaller than a pixel: stamp its centroid so small
            # buildings do not silently vanish at coarse resolutions.
            cx = int(np.clip(ring_px[:, 0].mean(), 0, nx - 1))
            cy = int(np.clip(ring_px[:, 1].mean(), 0, ny - 1))
            top[cy, cx] = max(top[cy, cx], ground[cy, cx] + float(b["h"]))
            continue
        block = top[y0:y1, x0:x1]
        cand = ground[y0:y1, x0:x1] + float(b["h"])
        block[sub] = np.maximum(block[sub], cand[sub])   # taller building wins
        top[y0:y1, x0:x1] = block

    return HeightRaster(ground=ground, top=top, minx=minx, miny=miny, cell_m=cell_m)


def _terrain_bilinear_fallback(terrain: dict, x, y):
    """Copy of ulap_scope.geo.terrain_bilinear for when the pipeline package
    isn't on the path (keeps the demos runnable from a bare checkout)."""
    nx, ny = terrain["nx"], terrain["ny"]
    z = np.asarray(terrain["z"], dtype=float).reshape(ny, nx)
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    fx = (x - terrain["minx"]) / (terrain["maxx"] - terrain["minx"]) * (nx - 1)
    fy = (y - terrain["miny"]) / (terrain["maxy"] - terrain["miny"]) * (ny - 1)
    fx = np.clip(fx, 0, nx - 1)
    fy = np.clip(fy, 0, ny - 1)
    ix = fx.astype(int)
    iy = fy.astype(int)
    ix1 = np.minimum(ix + 1, nx - 1)
    iy1 = np.minimum(iy + 1, ny - 1)
    tx = fx - ix
    ty = fy - iy
    out = (z[iy, ix] * (1 - tx) * (1 - ty) + z[iy, ix1] * tx * (1 - ty)
           + z[iy1, ix] * (1 - tx) * ty + z[iy1, ix1] * tx * ty)
    return float(out) if out.ndim == 0 else out


# ---------------------------------------------------------------------- I/O
#: The bundled scene, built entirely from open data by
#: ``examples/data/fetch_open_scene.py`` (OSM footprints + AWS terrain tiles).
#: No licence-restricted geospatial layer is committed to this repository --
#: see ``DATA.md``.
SAMPLE_SCENE = "newton-open_scene_manifest.json"

#: Environment variable a user can point at their own manifest.
SCENE_ENV_VAR = "ULAP_SCENE"


#: Where ``ulap-scope preprocess`` writes a study's manifest.
PIPELINE_SCENE = Path(__file__).resolve().parents[2] / "blender" / "scene_build" / "scene_manifest.json"


def resolve_scene_path(manifest_path: str | Path | None = None) -> Path:
    """Work out which scene to load, in priority order:

    1. an explicit ``manifest_path`` argument;
    2. ``$ULAP_SCENE``;
    3. the bundled open-data sample.

    Note what is deliberately *not* in that list: the pipeline's own output at
    ``blender/scene_build/scene_manifest.json``. Auto-selecting it would make the
    demos behave differently depending on whose checkout they run in, and would
    quietly run a licence-restricted scene (see ``DATA.md``) for anyone whose
    clone happens to contain one. Opting in is one environment variable --
    :func:`pipeline_scene_hint` prints it when a pipeline manifest is present."""
    import os

    if manifest_path:
        p = Path(manifest_path).expanduser()
        if not p.exists():
            raise FileNotFoundError(f"scene manifest not found: {p}")
        return p

    env = os.environ.get(SCENE_ENV_VAR)
    if env:
        p = Path(env).expanduser()
        if not p.exists():
            raise FileNotFoundError(f"{SCENE_ENV_VAR} points at a missing file: {p}")
        return p

    return _data_dir() / SAMPLE_SCENE


def pipeline_scene_hint() -> str:
    """One line telling you how to swap in your own pipeline output, or "" when
    there is none to swap in."""
    if not PIPELINE_SCENE.exists():
        return ""
    return (f"note: a pipeline scene exists at {PIPELINE_SCENE}\n"
            f"      use it with:  export {SCENE_ENV_VAR}='{PIPELINE_SCENE}'")


def load_scene(manifest_path: str | Path | None = None,
               towers_path: str | Path | None = None,
               name: str | None = None) -> Scene:
    """Load a scene manifest. See :func:`resolve_scene_path` for what gets picked
    when you pass nothing.

    ``towers_path`` optionally overrides the site list with a JSON array of
    ``{name, x, y, h, ground_z}`` objects -- the manifest's own ``antennas`` are
    used otherwise."""
    path = resolve_scene_path(manifest_path)
    m = json.loads(path.read_text())

    towers: list[Tower] = []
    if towers_path:
        entries = json.loads(Path(towers_path).read_text())
    else:
        entries = m.get("antennas", [])
    for t in entries:
        towers.append(Tower(name=t["name"], x=float(t["x"]), y=float(t["y"]),
                            h=float(t["h"]), ground_z=float(t.get("ground_z", 0.0)),
                            structure=t.get("structure", "Monopole"),
                            in_scene=bool(t.get("in_scene", True))))

    if name is None:
        name = (m.get("provenance", {}).get("name")
                or path.stem.replace("_scene_manifest", ""))

    return Scene(name=name, epsg=int(m["epsg"]), origin=tuple(m["origin"]),
                 terrain=m["terrain"], buildings=m["buildings"], towers=towers,
                 provenance=m.get("provenance", {}), source_path=path)


def load_link_metrics(path: str | Path | None = None) -> dict[str, np.ndarray]:
    """Real Sionna RT output along the Rising Sun radial: distance, path gain,
    RMS delay spread, path count. Columns come back as numpy arrays."""
    path = Path(path or _data_dir() / "newton_link_metrics.csv")
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    return {k: np.array([float(r[k]) for r in rows]) for k in rows[0]}
