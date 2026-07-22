#!/usr/bin/env python3
"""
build_scene.py  --  Blender background scene builder for the Barbados / Sionna RT twin.

Run headless:
    /Applications/Blender.app/Contents/MacOS/Blender -b <input>.blend \
        --python build_scene.py -- <scene_manifest.json> <output>.blend

Builds, in the existing scene's EPSG:21292 georef (origin = scene custom props):
  * ground plane textured with the reprojected Google-Satellite basemap  -> itu_medium_dry_ground
  * one merged Buildings mesh, footprints extruded to real LiDAR heights  -> itu_concrete
  * an empty marker per cell tower (name + height custom prop)
All geometry is placed in scene-local metres (CRS coord - scene origin), so it
lines up with the BlenderGIS georeferencing already stored in the .blend.
"""
import bpy, bmesh, json, sys, os

argv = sys.argv[sys.argv.index("--") + 1:]
MANIFEST, OUT_BLEND = argv[0], argv[1]
MODE = argv[2] if len(argv) > 2 else "flat"      # "flat" | "terrain"
TERRAIN = (MODE == "terrain")
M = json.load(open(MANIFEST))

def terrain_z(x, y):
    """Bilinear sample of the interpolated AVG_DTM grid at local (x,y)."""
    t = M["terrain"]
    nx, ny = t["nx"], t["ny"]
    fx = (x - t["minx"]) / (t["maxx"] - t["minx"]) * (nx - 1)
    fy = (y - t["miny"]) / (t["maxy"] - t["miny"]) * (ny - 1)
    fx = min(max(fx, 0), nx - 1); fy = min(max(fy, 0), ny - 1)
    ix, iy = int(fx), int(fy); ix1 = min(ix+1, nx-1); iy1 = min(iy+1, ny-1)
    tx, ty = fx - ix, fy - iy
    z = t["z"]
    z00 = z[iy*nx+ix]; z10 = z[iy*nx+ix1]; z01 = z[iy1*nx+ix]; z11 = z[iy1*nx+ix1]
    return (z00*(1-tx)*(1-ty) + z10*tx*(1-ty) + z01*(1-tx)*ty + z11*tx*ty)

# ---------------------------------------------------------------- helpers
def itu_material(name, rgba=(0.6, 0.6, 0.6, 1.0), image_path=None):
    """A Principled-BSDF material whose *name* carries the itu_ Sionna tag."""
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = rgba
    bsdf.inputs["Roughness"].default_value = 0.9
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = 0.1
    if image_path:
        img = bpy.data.images.load(image_path, check_existing=True)
        tex = nt.nodes.new("ShaderNodeTexImage"); tex.image = img
        tex.location = (-400, 300)
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    return mat

def link(obj):
    bpy.context.scene.collection.objects.link(obj)

# ---------------------------------------------------------------- clean up
# drop the degenerate baked-basemap object (kept the image datablock)
for n in ("GOOGLE_SAT_WM", "EXPORT_GOOGLE_SAT_WM"):
    o = bpy.data.objects.get(n)
    if o:
        bpy.data.objects.remove(o, do_unlink=True)

# ---------------------------------------------------------------- 1. ground plane (full extent)
# The baked satellite frame is smaller than the 2 km building clip. For a correct
# radio map we need ground under *every* building, so the plane spans the union of
# the basemap frame and all building footprints (+margin). The satellite texture is
# UV-mapped onto its true sub-rectangle and CLIP-ped outside (Sionna ignores the
# texture anyway -- it uses the itu_ name -- but this keeps the Blender view honest).
bm_info = M["basemap"]
bx0, bx1 = bm_info["minx"], bm_info["maxx"]
by0, by1 = bm_info["miny"], bm_info["maxy"]
# building extent
xs = [p[0] for b in M["buildings"] for p in b["ring"]]
ys = [p[1] for b in M["buildings"] for p in b["ring"]]
MARGIN = 60.0
minx = min(min(xs), bx0) - MARGIN; maxx = max(max(xs), bx1) + MARGIN
miny = min(min(ys), by0) - MARGIN; maxy = max(max(ys), by1) + MARGIN

mesh = bpy.data.meshes.new("Ground")
plane = bpy.data.objects.new("GOOGLE_SAT_BNG", mesh)
bm = bmesh.new()
uv = bm.loops.layers.uv.new("UVMap")
def guv(x, y):   # world XY -> texture UV (imagery lands on [bx0..bx1] x [by0..by1])
    return ((x - bx0) / (bx1 - bx0), (y - by0) / (by1 - by0))

if TERRAIN:
    # subdivided grid displaced to the AVG_DTM surface
    NG = M["terrain"]["nx"]
    gxs = [minx + (maxx-minx)*i/(NG-1) for i in range(NG)]
    gys = [miny + (maxy-miny)*j/(NG-1) for j in range(NG)]
    grid = [[bm.verts.new((gxs[i], gys[j], terrain_z(gxs[i], gys[j])))
             for i in range(NG)] for j in range(NG)]
    for j in range(NG-1):
        for i in range(NG-1):
            f = bm.faces.new((grid[j][i], grid[j][i+1], grid[j+1][i+1], grid[j+1][i]))
            for loop, vt in zip(f.loops, (grid[j][i], grid[j][i+1], grid[j+1][i+1], grid[j+1][i])):
                loop[uv].uv = guv(vt.co.x, vt.co.y)
else:
    corners = [(minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy)]
    verts = [bm.verts.new((x, y, 0.0)) for (x, y) in corners]
    face = bm.faces.new(verts)
    for loop, (x, y) in zip(face.loops, corners):
        loop[uv].uv = guv(x, y)
bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
bm.to_mesh(mesh); bm.free()
gmat = itu_material("itu_medium_dry_ground", (0.30, 0.32, 0.27, 1.0), image_path=bm_info["tif"])
# CLIP the texture so it doesn't tile across the whole (larger) plane
for n in gmat.node_tree.nodes:
    if n.type == "TEX_IMAGE":
        n.extension = "CLIP"
plane.data.materials.append(gmat)
link(plane)
print(f"[ground] full-extent plane {round(maxx-minx)}x{round(maxy-miny)} m "
      f"(texture sub-rect {round(bx1-bx0)}x{round(by1-by0)} m)")

# ---------------------------------------------------------------- 2. buildings (extruded)
bm = bmesh.new()
n_ok = 0
for b in M["buildings"]:
    ring = b["ring"]
    if len(ring) and ring[0] == ring[-1]:      # drop closing dup
        ring = ring[:-1]
    if len(ring) < 3:
        continue
    base_z = b["dtm"] if TERRAIN else 0.0       # seat on real ground elevation
    verts = [bm.verts.new((x, y, base_z)) for (x, y) in ring]
    try:
        f = bm.faces.new(verts)
    except ValueError:
        continue                                # skip self-touching/dup ring
    r = bmesh.ops.extrude_face_region(bm, geom=[f])
    top = [e for e in r["geom"] if isinstance(e, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, vec=(0, 0, b["h"]), verts=top)
    n_ok += 1
bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
bmesh_mesh = bpy.data.meshes.new("Buildings")
bm.to_mesh(bmesh_mesh); bm.free()
buildings = bpy.data.objects.new("Buildings", bmesh_mesh)
buildings.data.materials.append(itu_material("itu_concrete", (0.62, 0.60, 0.57, 1.0)))
link(buildings)
print(f"[buildings] {n_ok} extruded footprints merged into one mesh, {len(bmesh_mesh.polygons)} faces")

# ---------------------------------------------------------------- 3. antenna markers
tx_coll = bpy.data.collections.new("Antennas")
bpy.context.scene.collection.children.link(tx_coll)
for a in M["antennas"]:
    e = bpy.data.objects.new(f"TX_{a['name'].replace(' ', '_')}", None)
    e.empty_display_type = "PLAIN_AXES"
    e.empty_display_size = 15
    tx_z = (a.get("ground_z", 0.0) + a["h"]) if TERRAIN else a["h"]
    e.location = (a["x"], a["y"], tx_z)         # marker at antenna top (above ground)
    e["height_m"] = a["h"]
    e["ground_z"] = a.get("ground_z", 0.0)
    e["structure"] = a["structure"]
    e["site_name"] = a["name"]
    tx_coll.objects.link(e)
    print(f"[tx] {a['name']:12s} @ local ({a['x']:.1f}, {a['y']:.1f}, {a['h']})")

# ---------------------------------------------------------------- save
bpy.ops.wm.save_as_mainfile(filepath=OUT_BLEND)
print("saved ->", OUT_BLEND)
