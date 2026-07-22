#!/usr/bin/env python3
"""
render_perspective.py -- render the *built* Barbados twin from an angled
perspective camera, so the extruded 3D buildings + satellite ground read as a
3D scene (not the flat top-down Sionna maps).

Headless:
    /Applications/Blender.app/Contents/MacOS/Blender -b \
        ulap-bbd-memorial-twin_built.blend --python render_perspective.py -- out.png
"""
import bpy, sys, math, os
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
OUT = argv[0] if argv else os.path.join(os.path.dirname(__file__), "sionna_out", "blender_perspective.png")

# in-scene transmitters (local metres, marker at antenna top)
TOWERS = [("Newton", -191.7, -805.6, 30.0), ("Rising Sun", 970.3, -131.1, 24.0)]

# ---- yellow transmitter markers (small emissive spheres at the antenna tops) ----
mk = bpy.data.materials.new("tx_marker"); mk.use_nodes = True
bsdf = mk.node_tree.nodes.get("Principled BSDF")
bsdf.inputs["Base Color"].default_value = (1.0, 0.78, 0.23, 1.0)
if "Emission Color" in bsdf.inputs:
    bsdf.inputs["Emission Color"].default_value = (1.0, 0.78, 0.23, 1.0)
    bsdf.inputs["Emission Strength"].default_value = 6.0
for name, x, y, h in TOWERS:
    bpy.ops.mesh.primitive_uv_sphere_add(radius=9, location=(x, y, h + 4))
    s = bpy.context.active_object; s.name = f"MARK_{name}"
    s.data.materials.append(mk)
    bpy.ops.object.shade_smooth()

# ---- camera: low 3/4 aerial across the satellite-textured area (x[-1118,966] y[-588,595]) ----
look = Vector((250.0, 60.0, 6.0))
cam_data = bpy.data.cameras.new("PerspCam"); cam_data.lens = 30
cam = bpy.data.objects.new("PerspCam", cam_data)
cam.location = (-560.0, -720.0, 205.0)
bpy.context.scene.collection.objects.link(cam)
d = (look - cam.location).normalized()
cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()  # aligns cam up to world Z -> level horizon
bpy.context.scene.camera = cam

# ---- lighting: sun + brighter world so the satellite ground shows ----
sun_data = bpy.data.lights.new("Sun", 'SUN'); sun_data.energy = 3.2
sun = bpy.data.objects.new("Sun", sun_data)
sun.rotation_euler = (math.radians(48), math.radians(18), math.radians(35))
bpy.context.scene.collection.objects.link(sun)
world = bpy.context.scene.world or bpy.data.worlds.new("World")
bpy.context.scene.world = world; world.use_nodes = True
bg = world.node_tree.nodes.get("Background")
if bg:
    bg.inputs["Color"].default_value = (0.05, 0.06, 0.08, 1.0)
    bg.inputs["Strength"].default_value = 1.0

# ---- render settings (Eevee = fast; textures visible like Material Preview) ----
sc = bpy.context.scene
try:
    sc.render.engine = 'BLENDER_EEVEE_NEXT'
except Exception:
    sc.render.engine = 'BLENDER_EEVEE'
sc.render.resolution_x = 1600
sc.render.resolution_y = 900
sc.render.film_transparent = False
sc.view_settings.view_transform = 'Standard'
sc.render.image_settings.file_format = 'PNG'
sc.render.filepath = OUT
bpy.ops.render.render(write_still=True)
print("wrote", OUT)
