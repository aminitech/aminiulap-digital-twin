#!/usr/bin/env python3
"""
export_mitsuba_direct.py -- manifest -> Mitsuba/Sionna scene, without Blender.

The original export path (``export_mitsuba.py``) runs *inside* Blender: it
imports ``bpy``, drives the mitsuba-blender add-on, and therefore needs a
Blender install plus a ``.blend`` built by ``build_scene.py``. That is a heavy
dependency for what is, geometrically, a very simple job: extrude some polygons,
mesh a height grid, write two PLYs and an XML.

This module does that job directly from a scene manifest, with nothing but the
standard library. It is what makes the open-data scene reproducible from a
fresh clone::

    python -m ulap_scope.stages.export_mitsuba_direct \\
        examples/data/newton-open_scene_manifest.json \\
        examples/data/open_scene_mitsuba --mode terrain

Conventions (get these wrong and the scene loads but the physics is nonsense):

* **Z-up, metres, scene-local coordinates.** The manifest already stores local
  coordinates -- CRS easting/northing minus ``origin`` -- so vertices are
  written straight through. ``origin`` is echoed into the XML as a comment so
  the georeference is never lost.
* **Materials are named, not painted.** Sionna converts any BSDF whose id starts
  with ``mat-itu_`` / ``itu_`` into an ``itu-radio-material``; the visual BSDF
  underneath is discarded. Buildings get ``itu_concrete``, ground gets
  ``itu_medium_dry_ground``, matching the exported Barbados scenes so the
  downstream stages' material assumptions still hold.
* **No textures.** The basemap is imagery we may not have the right to
  redistribute, and the solver does not read it.

Two ground modes, as the Blender pipeline has:

``terrain``
    Ground is a mesh of the manifest's height grid (true elevations, e.g.
    60-117 m for the Newton scene). Each building is seated on the *lowest*
    terrain sample under its footprint, so nothing floats on a slope, and
    extruded to ``base + h``.
``flat``
    Ground is a single plane at z = 0 and buildings run 0 -> h. Cheaper, and
    the right control when you want terrain removed as a variable.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path
from typing import Iterable, Sequence

# --------------------------------------------------------------------------
# materials: the id is load-bearing, the rgb is only for a human looking at it
# --------------------------------------------------------------------------
MAT_BUILDING = "itu_concrete"
MAT_GROUND = "itu_medium_dry_ground"

_MAT_RGB = {
    MAT_BUILDING: (0.62, 0.60, 0.57),
    MAT_GROUND: (0.38, 0.40, 0.32),
}

# ground plane is grown past the building extent so no footprint hangs off it
GROUND_MARGIN_M = 60.0

Vec3 = tuple[float, float, float]
Tri = tuple[int, int, int]


# ------------------------------------------------------------------ terrain
def terrain_z(terrain: dict, x: float, y: float) -> float:
    """Bilinear sample of the manifest height grid, clamped at the edges.

    The grid is stored flat, row-major, ``z[iy * nx + ix]`` with iy indexing
    northing -- the same layout ``build_scene.py`` reads.
    """
    nx, ny = int(terrain["nx"]), int(terrain["ny"])
    minx, maxx = float(terrain["minx"]), float(terrain["maxx"])
    miny, maxy = float(terrain["miny"]), float(terrain["maxy"])
    z = terrain["z"]

    fx = (x - minx) / (maxx - minx) * (nx - 1)
    fy = (y - miny) / (maxy - miny) * (ny - 1)
    fx = min(max(fx, 0.0), nx - 1.0)
    fy = min(max(fy, 0.0), ny - 1.0)

    ix, iy = int(fx), int(fy)
    ix1, iy1 = min(ix + 1, nx - 1), min(iy + 1, ny - 1)
    tx, ty = fx - ix, fy - iy

    z00 = z[iy * nx + ix]
    z10 = z[iy * nx + ix1]
    z01 = z[iy1 * nx + ix]
    z11 = z[iy1 * nx + ix1]
    return (z00 * (1 - tx) * (1 - ty) + z10 * tx * (1 - ty)
            + z01 * (1 - tx) * ty + z11 * tx * ty)


def ground_mesh(manifest: dict, mode: str,
                margin: float = GROUND_MARGIN_M) -> tuple[list[Vec3], list[Tri]]:
    """Ground surface covering every footprint plus a margin.

    ``terrain`` gives an (n x n) height mesh at the manifest grid's resolution;
    ``flat`` gives the same extent as two triangles at z = 0.
    """
    terrain = manifest["terrain"]
    xs = [p[0] for b in manifest["buildings"] for p in b["ring"]]
    ys = [p[1] for b in manifest["buildings"] for p in b["ring"]]
    minx = min([*xs, float(terrain["minx"])]) - margin
    maxx = max([*xs, float(terrain["maxx"])]) + margin
    miny = min([*ys, float(terrain["miny"])]) - margin
    maxy = max([*ys, float(terrain["maxy"])]) + margin

    if mode == "flat":
        verts: list[Vec3] = [(minx, miny, 0.0), (maxx, miny, 0.0),
                             (maxx, maxy, 0.0), (minx, maxy, 0.0)]
        return verts, [(0, 1, 2), (0, 2, 3)]

    n = int(terrain["nx"])
    gx = [minx + (maxx - minx) * i / (n - 1) for i in range(n)]
    gy = [miny + (maxy - miny) * j / (n - 1) for j in range(n)]
    verts = [(gx[i], gy[j], terrain_z(terrain, gx[i], gy[j]))
             for j in range(n) for i in range(n)]

    faces: list[Tri] = []
    for j in range(n - 1):
        for i in range(n - 1):
            a = j * n + i
            b = j * n + i + 1
            c = (j + 1) * n + i + 1
            d = (j + 1) * n + i
            # CCW seen from +Z -> normals point up
            faces.append((a, b, c))
            faces.append((a, c, d))
    return verts, faces


# ------------------------------------------------------------- polygon utils
def _signed_area(ring: Sequence[Sequence[float]]) -> float:
    s = 0.0
    n = len(ring)
    for i in range(n):
        x0, y0 = ring[i][0], ring[i][1]
        x1, y1 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        s += x0 * y1 - x1 * y0
    return 0.5 * s


def _clean_ring(ring: Sequence[Sequence[float]],
                eps: float = 1e-6) -> list[tuple[float, float]]:
    """Drop the closing duplicate and any coincident consecutive vertices."""
    pts: list[tuple[float, float]] = []
    for p in ring:
        q = (float(p[0]), float(p[1]))
        if pts and abs(q[0] - pts[-1][0]) < eps and abs(q[1] - pts[-1][1]) < eps:
            continue
        pts.append(q)
    while len(pts) > 1 and abs(pts[0][0] - pts[-1][0]) < eps \
            and abs(pts[0][1] - pts[-1][1]) < eps:
        pts.pop()
    return pts


def triangulate(ring: Sequence[tuple[float, float]]) -> list[Tri]:
    """Ear-clipping triangulation of a simple polygon, CCW, returning index
    triples into ``ring``.

    A fan would be wrong here: OSM footprints are frequently L- and U-shaped,
    and a fan over a concave polygon produces roof triangles that stick out
    through the walls -- geometry the ray tracer will happily reflect off.
    """
    n = len(ring)
    if n < 3:
        return []
    if n == 3:
        return [(0, 1, 2)]

    idx = list(range(n))
    if _signed_area(ring) < 0:                       # make it CCW
        idx.reverse()

    def cross(o, a, b) -> float:
        return ((ring[a][0] - ring[o][0]) * (ring[b][1] - ring[o][1])
                - (ring[a][1] - ring[o][1]) * (ring[b][0] - ring[o][0]))

    def inside(p, a, b, c) -> bool:
        d1 = cross(a, b, p)
        d2 = cross(b, c, p)
        d3 = cross(c, a, p)
        neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
        pos = (d1 > 0) or (d2 > 0) or (d3 > 0)
        return not (neg and pos)

    tris: list[Tri] = []
    guard = 0
    while len(idx) > 3 and guard < 4 * n:
        guard += 1
        clipped = False
        for k in range(len(idx)):
            a = idx[(k - 1) % len(idx)]
            b = idx[k]
            c = idx[(k + 1) % len(idx)]
            if cross(a, b, c) <= 0:                  # reflex (or degenerate)
                continue
            if any(inside(p, a, b, c) for p in idx if p not in (a, b, c)):
                continue
            tris.append((a, b, c))
            idx.pop(k)
            clipped = True
            break
        if not clipped:                              # self-touching ring: fan it
            break
    if len(idx) == 3:
        tris.append((idx[0], idx[1], idx[2]))
    elif len(idx) > 3:
        tris.extend((idx[0], idx[i], idx[i + 1]) for i in range(1, len(idx) - 1))
    return tris


# ----------------------------------------------------------------- buildings
def building_mesh(manifest: dict, mode: str) -> tuple[list[Vec3], list[Tri], dict]:
    """Extrude every footprint into a closed prism: floor, walls and roof.

    Closed matters. An open box lets rays enter through the missing face and
    bounce around inside, which shows up as spurious energy in shadowed cells.
    """
    terrain = manifest["terrain"]
    verts: list[Vec3] = []
    faces: list[Tri] = []
    heights: list[float] = []
    skipped = 0

    for b in manifest["buildings"]:
        ring = _clean_ring(b["ring"])
        if len(ring) < 3:
            skipped += 1
            continue
        if _signed_area(ring) < 0:                   # normalise winding to CCW
            ring = ring[::-1]

        h = float(b["h"])
        if mode == "flat":
            base = 0.0
        else:
            # seat on the lowest ground under the footprint so nothing floats
            base = min(terrain_z(terrain, x, y) for x, y in ring)
        top = base + h
        heights.append(h)

        n = len(ring)
        v0 = len(verts)
        verts.extend((x, y, base) for x, y in ring)          # v0     .. v0+n-1
        verts.extend((x, y, top) for x, y in ring)           # v0+n   .. v0+2n-1

        loc = triangulate(ring)
        # roof: CCW from above -> +Z normal
        faces.extend((v0 + n + a, v0 + n + b_, v0 + n + c) for a, b_, c in loc)
        # floor: reversed -> -Z normal
        faces.extend((v0 + c, v0 + b_, v0 + a) for a, b_, c in loc)
        # walls: outward normals for a CCW footprint
        for i in range(n):
            j = (i + 1) % n
            bl, br = v0 + i, v0 + j
            tl, tr = v0 + n + i, v0 + n + j
            faces.append((bl, br, tr))
            faces.append((bl, tr, tl))

    stats = {
        "buildings": len(heights),
        "skipped": skipped,
        "h_min": min(heights) if heights else 0.0,
        "h_max": max(heights) if heights else 0.0,
        "h_mean": (sum(heights) / len(heights)) if heights else 0.0,
    }
    return verts, faces, stats


# ----------------------------------------------------------------- PLY / XML
def write_ply(path: Path, verts: Sequence[Vec3], faces: Sequence[Tri]) -> int:
    """Binary little-endian PLY -- the format Mitsuba's ``ply`` shape reads."""
    header = (
        "ply\n"
        "format binary_little_endian 1.0\n"
        "comment generated by ulap_scope.stages.export_mitsuba_direct\n"
        f"element vertex {len(verts)}\n"
        "property float x\nproperty float y\nproperty float z\n"
        f"element face {len(faces)}\n"
        "property list uchar uint vertex_indices\n"
        "end_header\n"
    ).encode("ascii")

    body = bytearray()
    vfmt = struct.Struct("<3f")
    for v in verts:
        body += vfmt.pack(*v)
    ffmt = struct.Struct("<B3I")
    for f in faces:
        body += ffmt.pack(3, *f)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + bytes(body))
    return path.stat().st_size


def _bsdf_xml(name: str) -> str:
    r, g, b = _MAT_RGB[name]
    return (
        f'\t<bsdf type="twosided" id="mat-{name}" name="mat-{name}">\n'
        f'\t\t<bsdf type="diffuse" name="bsdf">\n'
        f'\t\t\t<rgb value="{r:.6f} {g:.6f} {b:.6f}" name="reflectance"/>\n'
        f'\t\t</bsdf>\n'
        f'\t</bsdf>\n'
    )


def _shape_xml(mesh: str, material: str) -> str:
    return (
        f'\t<shape type="ply" id="mesh-{mesh}" name="mesh-{mesh}">\n'
        f'\t\t<string name="filename" value="meshes/{mesh}.ply"/>\n'
        f'\t\t<boolean name="face_normals" value="true"/>\n'
        f'\t\t<ref id="mat-{material}" name="bsdf"/>\n'
        f'\t</shape>\n'
    )


def write_scene_xml(path: Path, manifest: dict, mode: str,
                    shapes: Iterable[tuple[str, str]]) -> int:
    prov = manifest.get("provenance", {})
    ox, oy = manifest["origin"]
    lines = [
        '<scene version="2.1.0">\n\n',
        "<!--\n",
        f"  {prov.get('name', 'scene')} | ground mode: {mode}\n",
        "  Generated by ulap_scope.stages.export_mitsuba_direct from an open-data\n",
        "  scene manifest. No Blender involved; no licence-restricted input.\n",
        "\n",
        "  Coordinates are scene-local metres, Z-up (Sionna's convention).\n",
        f"  Georeference: EPSG:{manifest.get('epsg')}, local (0,0) is easting\n"
        f"  {ox:.3f} m, northing {oy:.3f} m.\n",
        "\n",
        "  Sources and licences:\n",
        f"    buildings  {prov.get('buildings', {}).get('source', 'n/a')}\n",
        f"               {prov.get('buildings', {}).get('licence', 'n/a')}\n",
        f"    terrain    {prov.get('terrain', {}).get('source', 'n/a')}\n",
        f"               {prov.get('terrain', {}).get('licence', 'n/a')}\n",
        "  See docs/OPEN-DATA-SCENE.md for attribution requirements and limits.\n",
        "-->\n\n",
        '\t<integrator type="path">\n',
        '\t\t<integer name="max_depth" value="12"/>\n',
        "\t</integrator>\n\n",
        "<!-- Materials: the `mat-itu_*` id is what Sionna converts into an\n"
        "     itu-radio-material. The diffuse BSDF below is only for previews. -->\n",
    ]
    shapes = list(shapes)
    seen: list[str] = []
    for _mesh, material in shapes:
        if material not in seen:
            seen.append(material)
            lines.append(_bsdf_xml(material))
    lines.append("\n<!-- Shapes -->\n")
    for mesh, material in shapes:
        lines.append(_shape_xml(mesh, material))
    lines.append("\n</scene>\n")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines))
    return path.stat().st_size


# ---------------------------------------------------------------------- main
def export(manifest_path: Path, out_dir: Path, mode: str = "terrain",
           margin: float = GROUND_MARGIN_M, quiet: bool = False) -> dict:
    """Write ``<out_dir>/scene.xml`` + ``<out_dir>/meshes/*.ply``. Returns stats."""
    if mode not in ("terrain", "flat"):
        raise ValueError(f"mode must be 'terrain' or 'flat', got {mode!r}")

    manifest = json.loads(Path(manifest_path).read_text())
    out_dir = Path(out_dir)

    gverts, gfaces = ground_mesh(manifest, mode, margin)
    bverts, bfaces, bstats = building_mesh(manifest, mode)

    ground_name = "Terrain" if mode == "terrain" else "Ground"
    gbytes = write_ply(out_dir / "meshes" / f"{ground_name}.ply", gverts, gfaces)
    bbytes = write_ply(out_dir / "meshes" / "Buildings.ply", bverts, bfaces)
    xbytes = write_scene_xml(out_dir / "scene.xml", manifest, mode,
                             [(ground_name, MAT_GROUND),
                              ("Buildings", MAT_BUILDING)])

    allv = gverts + bverts
    stats = {
        "mode": mode,
        "scene_xml": str(out_dir / "scene.xml"),
        "buildings": bstats["buildings"],
        "buildings_skipped": bstats["skipped"],
        "h_min": bstats["h_min"], "h_max": bstats["h_max"],
        "h_mean": bstats["h_mean"],
        "ground_verts": len(gverts), "ground_faces": len(gfaces),
        "building_verts": len(bverts), "building_faces": len(bfaces),
        "bbox": {
            "x": (min(v[0] for v in allv), max(v[0] for v in allv)),
            "y": (min(v[1] for v in allv), max(v[1] for v in allv)),
            "z": (min(v[2] for v in allv), max(v[2] for v in allv)),
        },
        "bytes": {"scene.xml": xbytes,
                  f"meshes/{ground_name}.ply": gbytes,
                  "meshes/Buildings.ply": bbytes,
                  "total": xbytes + gbytes + bbytes},
    }
    if not quiet:
        bb = stats["bbox"]
        print(f"[export] mode={mode}  ->  {out_dir}")
        print(f"[export] buildings {stats['buildings']} "
              f"(skipped {stats['buildings_skipped']}), "
              f"h {stats['h_min']:.1f}-{stats['h_max']:.1f} m "
              f"(mean {stats['h_mean']:.2f})")
        print(f"[export] ground    {len(gverts)} verts / {len(gfaces)} tris")
        print(f"[export] buildings {len(bverts)} verts / {len(bfaces)} tris")
        print(f"[export] bbox x {bb['x'][0]:.1f}..{bb['x'][1]:.1f}  "
              f"y {bb['y'][0]:.1f}..{bb['y'][1]:.1f}  "
              f"z {bb['z'][0]:.1f}..{bb['z'][1]:.1f}  (metres, local, Z-up)")
        print(f"[export] size      {stats['bytes']['total'] / 1024:.0f} KiB total")
    return stats


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="export_mitsuba_direct",
        description="Build a Sionna-loadable Mitsuba scene from a scene "
                    "manifest, without Blender.")
    ap.add_argument("manifest", type=Path, help="scene manifest JSON")
    ap.add_argument("out_dir", type=Path, help="output directory for scene.xml + meshes/")
    ap.add_argument("--mode", choices=("terrain", "flat"), default="terrain",
                    help="ground surface: terrain mesh (default) or flat z=0 plane")
    ap.add_argument("--margin", type=float, default=GROUND_MARGIN_M,
                    help="metres of ground added beyond the building extent")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    export(args.manifest, args.out_dir, args.mode, args.margin, args.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
