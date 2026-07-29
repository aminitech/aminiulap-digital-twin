#!/usr/bin/env python3
"""
Build a demo scene from **open, redistributable** data — anywhere on earth.

    python fetch_open_scene.py                                  # the pilot study area
    python fetch_open_scene.py --lon 36.8219 --lat -1.2921 --name nairobi-cbd
    python fetch_open_scene.py --half-width 1500 --cell-m 20 -o my_scene.json

Sources, all public and redistributable with attribution:

  buildings  OpenStreetMap via the Overpass API            (ODbL 1.0)
  terrain    AWS Terrain Tiles, "terrarium" encoding       (public domain / open;
             built from SRTM, 3DEP, GMTED and friends — no API key needed)
  towers     a two-tower *template* you edit — see --towers

The output is a `scene_manifest.json` in the same shape the real pipeline writes
(`ulap-scope preprocess`), so the notebooks and apps consume it unchanged.

## What open data costs you

OSM has excellent footprint geometry and almost **no building heights** — this
script assigns them from `height`/`building:levels` tags where they exist and from
a per-type default table where they don't. The pilot study used national LiDAR
heights. Open terrain is ~30 m posting versus a LiDAR DTM. Neither substitution is
free, and a study built this way should say so: the manifest records exactly which
source and which heuristic produced every number, under `provenance`.

Requires: numpy, pillow (both come with matplotlib). Standard library otherwise.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
TERRAIN_TILE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
USER_AGENT = "ulap-digital-twin examples/fetch_open_scene (https://github.com/aminitech)"

#: Fallback heights [m] when OSM carries no height or level count. Deliberately
#: conservative: over-tall buildings manufacture shadowing that isn't there.
DEFAULT_HEIGHTS_M = {
    "house": 4.5, "detached": 5.0, "residential": 6.0, "apartments": 12.0,
    "bungalow": 3.5, "hut": 2.5, "shed": 2.5, "garage": 2.5, "garages": 3.0,
    "farm_auxiliary": 4.0, "barn": 6.0, "greenhouse": 3.0, "roof": 3.0,
    "commercial": 7.0, "retail": 6.0, "industrial": 8.0, "warehouse": 8.0,
    "school": 7.0, "hospital": 12.0, "church": 9.0, "chapel": 7.0,
    "hotel": 15.0, "office": 15.0, "civic": 9.0, "public": 9.0,
    "construction": 4.0, "yes": 4.5,
}
DEFAULT_HEIGHT_M = 4.5
METRES_PER_LEVEL = 3.0


# --------------------------------------------------------------------- geodesy
def utm_zone_epsg(lon: float, lat: float) -> tuple[int, int]:
    """(zone, EPSG) of the UTM zone containing lon/lat."""
    zone = min(max(int((lon + 180.0) // 6.0) + 1, 1), 60)
    return zone, (32600 if lat >= 0 else 32700) + zone


def lonlat_to_utm(lon, lat, zone: int, northern: bool):
    """WGS-84 lon/lat -> UTM easting/northing (Krüger series, WGS-84 ellipsoid).

    Accurate to well under a metre inside a zone, which is a thousand times
    better than anything else in this pipeline. Vectorised over numpy arrays."""
    lon = np.asarray(lon, dtype=float)
    lat = np.asarray(lat, dtype=float)
    a, f = 6378137.0, 1 / 298.257223563
    k0, e = 0.9996, math.sqrt(f * (2 - f))
    n = f / (2 - f)
    n2, n3, n4 = n * n, n ** 3, n ** 4
    A = a / (1 + n) * (1 + n2 / 4 + n4 / 64)
    alpha = [n / 2 - 2 * n2 / 3 + 5 * n3 / 16,
             13 * n2 / 48 - 3 * n3 / 5,
             61 * n3 / 240]

    lon0 = math.radians(zone * 6 - 183)
    phi, lam = np.radians(lat), np.radians(lon) - lon0

    t = np.sinh(np.arctanh(np.sin(phi))
                - (2 * math.sqrt(n) / (1 + n))
                * np.arctanh(2 * math.sqrt(n) / (1 + n) * np.sin(phi)))
    xi = np.arctan2(t, np.cos(lam))
    eta = np.arctanh(np.sin(lam) / np.hypot(1, t))

    E = eta + sum(alpha[j] * np.cos(2 * (j + 1) * xi) * np.sinh(2 * (j + 1) * eta)
                  for j in range(3))
    N = xi + sum(alpha[j] * np.sin(2 * (j + 1) * xi) * np.cosh(2 * (j + 1) * eta)
                 for j in range(3))
    easting = k0 * A * E + 500_000.0
    northing = k0 * A * N + (0.0 if northern else 10_000_000.0)
    return easting, northing


def bbox_deg(lon: float, lat: float, half_width_m: float):
    """(min_lon, min_lat, max_lon, max_lat) of a square around lon/lat."""
    dlat = half_width_m / 111_320.0
    dlon = half_width_m / (111_320.0 * max(math.cos(math.radians(lat)), 1e-9))
    return (lon - dlon, lat - dlat, lon + dlon, lat + dlat)


# ------------------------------------------------------------------ buildings
class CertificateError(RuntimeError):
    """Raised with actionable advice when TLS verification fails locally."""


def _ssl_context():
    """An SSL context that can actually verify certificates.

    A python.org install on macOS ships no CA bundle until you run
    ``Install Certificates.command``, so plain ``urlopen`` fails on every HTTPS
    request with CERTIFICATE_VERIFY_FAILED. If ``certifi`` is importable we use
    its bundle, which fixes it without the user touching anything."""
    try:
        import certifi
    except ImportError:
        return None                      # fall back to the system default
    return ssl.create_default_context(cafile=certifi.where())


_SSL_ADVICE = (
    "TLS certificate verification failed, which is a local trust-store problem, "
    "not a problem with the server.\n"
    "  macOS + python.org Python: run "
    "'/Applications/Python 3.x/Install Certificates.command'\n"
    "  any platform:              pip install certifi   (this script will then use it)\n"
    "  or skip the network entirely: export the area from https://overpass-turbo.eu "
    "and pass it with --osm-json"
)


def _http(url: str, data: bytes | None = None, timeout: int = 180) -> bytes:
    req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as r:
            return r.read()
    except urllib.error.URLError as exc:
        if isinstance(getattr(exc, "reason", None), ssl.SSLCertVerificationError):
            raise CertificateError(_SSL_ADVICE) from exc
        raise


def fetch_osm_buildings(bbox, timeout: int = 180, attempts: int = 3) -> list[dict]:
    """Every closed building way in the bbox, with its geometry and tags.

    Overpass is a free, shared, heavily-loaded service: it answers a busy moment
    with 429/504, and a missing or generic User-Agent with 406. So we identify
    ourselves properly, try each mirror, and back off between rounds rather than
    hammering it."""
    min_lon, min_lat, max_lon, max_lat = bbox
    query = (f"[out:json][timeout:{timeout}];"
             f'way["building"]({min_lat},{min_lon},{max_lat},{max_lon});'
             f"out geom;")
    last_err = None
    for attempt in range(1, attempts + 1):
        for url in OVERPASS_URLS:
            try:
                print(f"  querying {url} (attempt {attempt}/{attempts}) ...")
                raw = _http(url, data=query.encode(), timeout=timeout + 30)
                return json.loads(raw).get("elements", [])
            except CertificateError:
                raise            # retrying a local trust-store problem is pointless
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError,
                    ConnectionError) as exc:
                print(f"  ! {type(exc).__name__}: {exc}")
                last_err = exc
        if attempt < attempts:
            wait = 15 * attempt
            print(f"  every mirror busy — waiting {wait}s before retrying")
            time.sleep(wait)
    raise RuntimeError(
        f"every Overpass mirror failed after {attempts} rounds; last error: {last_err}. "
        "Overpass rate-limits by IP — wait a few minutes and try again, or export "
        "the area from https://overpass-turbo.eu and pass it with --osm-json.")


def building_height_m(tags: dict) -> tuple[float, str]:
    """Height for one OSM building, plus how we got it (for the provenance log)."""
    raw = tags.get("height") or tags.get("building:height")
    if raw:
        try:                                  # "12", "12 m", "12.5"
            return float(str(raw).split()[0].replace("m", "").strip()), "osm:height"
        except ValueError:
            pass
    levels = tags.get("building:levels")
    if levels:
        try:
            return float(str(levels).split(";")[0]) * METRES_PER_LEVEL, "osm:levels"
        except ValueError:
            pass
    kind = tags.get("building", "yes")
    return DEFAULT_HEIGHTS_M.get(kind, DEFAULT_HEIGHT_M), f"default:{kind}"


# -------------------------------------------------------------------- terrain
def _tile_xy(lon, lat, z: int):
    """Web-Mercator tile coordinates (fractional) for lon/lat. Vectorised."""
    lat_r = np.radians(np.asarray(lat, dtype=float))
    lon = np.asarray(lon, dtype=float)
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    y = (1 - np.log(np.tan(lat_r) + 1 / np.cos(lat_r)) / np.pi) / 2 * n
    return x, y


def fetch_terrain_grid(bbox, nx: int, ny: int, zoom: int = 13):
    """Sample AWS terrain tiles onto an nx*ny lon/lat grid. Returns z[ny, nx].

    Terrarium encoding: elevation = (R*256 + G + B/256) - 32768 metres."""
    from PIL import Image

    min_lon, min_lat, max_lon, max_lat = bbox
    lons = np.linspace(min_lon, max_lon, nx)
    lats = np.linspace(min_lat, max_lat, ny)
    LON, LAT = np.meshgrid(lons, lats)

    fx, fy = _tile_xy(LON, LAT, zoom)
    tx, ty = np.floor(fx).astype(int), np.floor(fy).astype(int)
    px = np.clip(((fx - tx) * 256).astype(int), 0, 255)
    py = np.clip(((fy - ty) * 256).astype(int), 0, 255)

    z = np.zeros((ny, nx), dtype=float)
    needed = sorted(set(zip(tx.ravel().tolist(), ty.ravel().tolist())))
    print(f"  {len(needed)} terrain tile(s) at zoom {zoom}")
    for i, (X, Y) in enumerate(needed, 1):
        url = TERRAIN_TILE_URL.format(z=zoom, x=X, y=Y)
        img = np.asarray(Image.open(io.BytesIO(_http(url, timeout=60))).convert("RGB"),
                         dtype=float)
        elev = img[:, :, 0] * 256 + img[:, :, 1] + img[:, :, 2] / 256 - 32768
        m = (tx == X) & (ty == Y)
        z[m] = elev[py[m], px[m]]
        print(f"    [{i}/{len(needed)}] {X}/{Y}  "
              f"{elev.min():.0f}–{elev.max():.0f} m", end="\r")
    print()
    return z


# --------------------------------------------------------------------- towers
#: PLACEHOLDER, not data. A real tower registry is per-study information you
#: supply (your own sites, or a public source such as OpenCellID, CC BY-SA 4.0).
#: These two are an editable template roughly matching the pilot's geometry -- a
#: 30 m and a 24 m monopole, diagonally opposed. Override with --towers, or edit
#: towers.template.json.
#:
#: Positions are given as ``offset_frac``, a fraction of the study half-width,
#: so the template lands sensibly inside the box at *any* --half-width. (Fixed
#: metre offsets would fall outside a smaller study area and leave the scene with
#: no serving site at all.) At the default half-width of 1000 m these reproduce
#: the pilot's two sites exactly.
TOWER_TEMPLATE = [
    {"name": "Newton", "offset_frac": [-0.19, -0.81], "h": 30.0, "structure": "Monopole"},
    {"name": "Rising Sun", "offset_frac": [0.97, -0.13], "h": 24.0, "structure": "Monopole"},
]


def build_manifest(name, lon, lat, half_width_m, zoom, towers_file=None,
                   terrain_n=70, osm_json=None):
    bbox = bbox_deg(lon, lat, half_width_m)
    zone, epsg = utm_zone_epsg(lon, lat)
    northern = lat >= 0
    ox, oy = lonlat_to_utm(lon, lat, zone, northern)
    origin = [float(ox), float(oy)]
    print(f"study    : {name} @ ({lon}, {lat}), ±{half_width_m:.0f} m")
    print(f"projection: UTM zone {zone}{'N' if northern else 'S'} (EPSG:{epsg})")
    print(f"origin   : {origin[0]:.1f}, {origin[1]:.1f}")

    def to_local(lons, lats):
        e, n = lonlat_to_utm(lons, lats, zone, northern)
        return e - origin[0], n - origin[1]

    print("\nbuildings (OpenStreetMap / Overpass):")
    if osm_json:
        print(f"  reading {osm_json}")
        elements = json.loads(Path(osm_json).read_text()).get("elements", [])
    else:
        elements = fetch_osm_buildings(bbox)
    buildings, sources = [], {}
    for el in elements:
        geom = el.get("geometry") or []
        if len(geom) < 4:
            continue
        lons = np.array([p["lon"] for p in geom])
        lats = np.array([p["lat"] for p in geom])
        xs, ys = to_local(lons, lats)
        ring = [[float(a), float(b)] for a, b in zip(xs, ys)]
        if ring[0] == ring[-1]:
            ring = ring[:-1]
        if len(ring) < 3:
            continue
        h, how = building_height_m(el.get("tags", {}))
        sources[how.split(":")[0]] = sources.get(how.split(":")[0], 0) + 1
        buildings.append({"ring": ring, "h": round(float(h), 2),
                          "osm_id": el.get("id"), "h_source": how})
    print(f"  {len(buildings)} footprints  (heights: "
          f"{', '.join(f'{k}={v}' for k, v in sorted(sources.items()))})")

    print("\nterrain (AWS Terrain Tiles):")
    zgrid = fetch_terrain_grid(bbox, terrain_n, terrain_n, zoom=zoom)
    corner_x, corner_y = to_local(np.array([bbox[0], bbox[2]]),
                                  np.array([bbox[1], bbox[3]]))
    minx, maxx = float(corner_x[0]), float(corner_x[1])
    miny, maxy = float(corner_y[0]), float(corner_y[1])
    print(f"  {terrain_n}x{terrain_n} grid, {zgrid.min():.1f}–{zgrid.max():.1f} m "
          f"({zgrid.max() - zgrid.min():.0f} m of relief)")

    terrain = {"nx": terrain_n, "ny": terrain_n, "minx": minx, "maxx": maxx,
               "miny": miny, "maxy": maxy, "zmin": float(zgrid.min()),
               "zmax": float(zgrid.max()),
               "z": [round(float(v), 2) for v in zgrid.ravel()]}

    # -- towers ------------------------------------------------------------
    if towers_file:
        template = json.loads(Path(towers_file).read_text())
    else:
        template = TOWER_TEMPLATE
    antennas = []
    for t in template:
        if "name" not in t or "h" not in t:      # skip _comment / doc entries
            continue
        if "offset_frac" in t:                   # fraction of the half-width
            tx = float(t["offset_frac"][0]) * half_width_m
            ty = float(t["offset_frac"][1]) * half_width_m
        elif "offset_m" in t:                    # absolute metres from the centre
            tx, ty = float(t["offset_m"][0]), float(t["offset_m"][1])
        else:                                    # explicit lon/lat
            ex, ey = to_local(np.array([t["lon"]]), np.array([t["lat"]]))
            tx, ty = float(ex[0]), float(ey[0])
        fx = (tx - minx) / (maxx - minx) * (terrain_n - 1)
        fy = (ty - miny) / (maxy - miny) * (terrain_n - 1)
        gz = float(zgrid[int(np.clip(fy, 0, terrain_n - 1)),
                         int(np.clip(fx, 0, terrain_n - 1))])
        antennas.append({"name": t["name"], "x": tx, "y": ty, "h": float(t["h"]),
                         "ground_z": round(gz, 2),
                         "structure": t.get("structure", "Monopole"),
                         "in_scene": bool(minx <= tx <= maxx and miny <= ty <= maxy)})
    listed = ", ".join(
        "{name} ({h:.0f} m{outside})".format(outside="" if a["in_scene"] else ", OUTSIDE box", **a)
        for a in antennas)
    print(f"\ntowers   : {listed}")
    if not any(a["in_scene"] for a in antennas):
        print("  ! WARNING: every site is outside the study box, so the scene has no\n"
              "    serving transmitter. Move them inside with --towers (offset_frac is a\n"
              "    fraction of the half-width), or widen the box with --half-width.")

    return {
        "epsg": epsg,
        "origin": origin,
        "basemap": {"tif": "", "px_w": 0, "px_h": 0, "minx": minx, "maxx": maxx,
                    "miny": miny, "maxy": maxy, "full_extent": True},
        "terrain": terrain,
        "buildings": buildings,
        "antennas": antennas,
        "provenance": {
            "name": name,
            "generator": "examples/data/fetch_open_scene.py",
            "centre_lonlat": [lon, lat],
            "half_width_m": half_width_m,
            "bbox_wgs84": list(bbox),
            "buildings": {
                "source": "OpenStreetMap via Overpass API",
                "licence": "ODbL 1.0 — © OpenStreetMap contributors",
                "url": "https://www.openstreetmap.org/copyright",
                "height_sources": sources,
                "height_note": ("OSM rarely carries building heights. Where no "
                                "height/building:levels tag exists, a per-type "
                                "default is used — see DEFAULT_HEIGHTS_M. Each "
                                "building records its own h_source."),
            },
            "terrain": {
                "source": "AWS Terrain Tiles (terrarium), zoom %d" % zoom,
                "licence": "open data; underlying SRTM/3DEP/GMTED are public domain",
                "url": "https://registry.opendata.aws/terrain-tiles/",
                "note": "~30 m posting resampled to the study grid; not a LiDAR DTM.",
            },
            "towers": {
                "source": "editable template shipped with this script"
                          if not towers_file else f"user file: {towers_file}",
                "note": "PLACEHOLDER — replace with your own site list.",
            },
        },
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lon", type=float, default=-59.533908, help="study centre longitude")
    ap.add_argument("--lat", type=float, default=13.088121, help="study centre latitude")
    ap.add_argument("--half-width", type=float, default=1000.0,
                    help="half-width of the square study box [m]")
    ap.add_argument("--name", default="newton-open")
    ap.add_argument("--zoom", type=int, default=14,
                    help="terrain tile zoom (12-15); 14 is ~10 m per pixel at the "
                         "equator, which is finer than the study grid")
    ap.add_argument("--terrain-n", type=int, default=70, help="terrain grid side")
    ap.add_argument("--towers", default=None,
                    help="JSON list of sites; each {name, h, and either "
                         "offset_m:[x,y] or lon/lat}")
    ap.add_argument("--osm-json", default=None,
                    help="skip Overpass and read a saved Overpass JSON export "
                         "(from https://overpass-turbo.eu) — useful when the "
                         "public API is rate-limiting you")
    ap.add_argument("-o", "--output", default=None,
                    help="default: <name>_scene_manifest.json next to this script")
    args = ap.parse_args(argv)

    try:
        manifest = build_manifest(args.name, args.lon, args.lat, args.half_width,
                                  args.zoom, args.towers, args.terrain_n, args.osm_json)
    except CertificateError as exc:
        print(f"\nerror: {exc}", file=sys.stderr)
        return 2

    out = Path(args.output) if args.output else Path(__file__).parent / \
        f"{args.name}_scene_manifest.json"
    out.write_text(json.dumps(manifest, separators=(",", ":")))
    print(f"\nwrote {out}  ({out.stat().st_size / 1024:.0f} kB)")
    print("\nattribution required when you publish anything made from this scene:")
    print("  buildings © OpenStreetMap contributors (ODbL 1.0)")
    print("  terrain   AWS Terrain Tiles / SRTM, GMTED, 3DEP")
    return 0


if __name__ == "__main__":
    sys.exit(main())
