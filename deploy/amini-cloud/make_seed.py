#!/usr/bin/env python3
"""Build twin-api/seed.json from the open-data scene in examples/data/.

Uses only OpenStreetMap footprints (ODbL 1.0) and the placeholder tower list,
never the licence-restricted geoportal scene in ulap-twin-ui/data.js.

    python deploy/amini-cloud/make_seed.py

Standard library only. The scene is in local metres on EPSG:32621 (UTM 21N)
around `origin`; this converts every point to WGS84 lon/lat, which is what the
three.js viewer reads.
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "examples/data/newton-open_scene_manifest.json"
METRICS = ROOT / "examples/data/newton_link_metrics.csv"
OUT = Path(__file__).resolve().parent / "twin-api/seed.json"

# WGS84 and UTM constants.
A = 6378137.0
F = 1 / 298.257223563
K0 = 0.9996
E2 = F * (2 - F)
EP2 = E2 / (1 - E2)


def utm_to_lonlat(easting: float, northing: float, zone: int, north: bool = True) -> tuple[float, float]:
    """Inverse transverse Mercator (Snyder 1987, eqs 8-12 to 8-25)."""
    x = easting - 500000.0
    y = northing if north else northing - 10000000.0
    m = y / K0
    mu = m / (A * (1 - E2 / 4 - 3 * E2**2 / 64 - 5 * E2**3 / 256))
    e1 = (1 - math.sqrt(1 - E2)) / (1 + math.sqrt(1 - E2))
    phi1 = (mu + (3 * e1 / 2 - 27 * e1**3 / 32) * math.sin(2 * mu)
            + (21 * e1**2 / 16 - 55 * e1**4 / 32) * math.sin(4 * mu)
            + (151 * e1**3 / 96) * math.sin(6 * mu)
            + (1097 * e1**4 / 512) * math.sin(8 * mu))
    s, c, t = math.sin(phi1), math.cos(phi1), math.tan(phi1)
    n1 = A / math.sqrt(1 - E2 * s * s)
    t1 = t * t
    c1 = EP2 * c * c
    r1 = A * (1 - E2) / (1 - E2 * s * s) ** 1.5
    d = x / (n1 * K0)
    lat = phi1 - (n1 * t / r1) * (
        d**2 / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1**2 - 9 * EP2) * d**4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1**2 - 252 * EP2 - 3 * c1**2) * d**6 / 720)
    lon = (d - (1 + 2 * t1 + c1) * d**3 / 6
           + (5 - 2 * c1 + 28 * t1 - 3 * c1**2 + 8 * EP2 + 24 * t1**2) * d**5 / 120) / c
    lon0 = math.radians((zone - 1) * 6 - 180 + 3)
    return math.degrees(lon0 + lon), math.degrees(lat)


def main() -> None:
    scene = json.loads(MANIFEST.read_text())
    if scene["epsg"] != 32621:
        raise SystemExit(f"expected EPSG:32621, got {scene['epsg']}")
    if "provenance" not in scene:
        raise SystemExit("refusing a scene with no provenance block: it is not the open-data scene")
    ox, oy = scene["origin"]

    def ll(x: float, y: float) -> list[float]:
        lon, lat = utm_to_lonlat(ox + x, oy + y, zone=21)
        return [round(lon, 7), round(lat, 7)]

    towers = [{
        "name": a["name"],
        "code": f"OPEN-{i + 1:02d}",
        "struct": a.get("structure", "Unknown"),
        "height": a["h"],
        "lon": ll(a["x"], a["y"])[0],
        "lat": ll(a["x"], a["y"])[1],
    } for i, a in enumerate(scene["antennas"])]

    buildings = [{
        "osm_id": b.get("osm_id"),
        "h": b["h"],
        "h_source": b.get("h_source", ""),
        "r": [ll(x, y) for x, y in b["ring"]],
    } for b in scene["buildings"]]

    with METRICS.open() as fh:
        metrics = [{k: float(v) for k, v in row.items()} for row in csv.DictReader(fh)]

    # Self-check: the centre of the scene must land on the provenance centre.
    clon, clat = scene["provenance"]["centre_lonlat"]
    got = ll(0.0, 0.0)
    err_m = math.hypot((got[0] - clon) * 111320 * math.cos(math.radians(clat)), (got[1] - clat) * 111320)
    if err_m > 5:
        raise SystemExit(f"projection check failed: centre is {err_m:.1f} m off")

    OUT.write_text(json.dumps({
        "provenance": scene["provenance"],
        "towers": towers,
        "buildings": buildings,
        "link_metrics": metrics,
    }, separators=(",", ":")) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(towers)} towers, {len(buildings)} buildings, "
          f"{len(metrics)} link metrics; centre check {err_m:.2f} m")


if __name__ == "__main__":
    main()
