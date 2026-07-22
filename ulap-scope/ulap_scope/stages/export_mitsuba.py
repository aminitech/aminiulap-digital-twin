#!/usr/bin/env python3
"""
export_mitsuba.py -- headless Mitsuba XML export for the Sionna RT scene.

    Blender -b <scene>.blend --python export_mitsuba.py -- <out_dir>/scene.xml

Enables the mitsuba-blender addon and exports the whole scene Z-up / Y-forward
(Sionna's convention), with object IDs so the itu_* material names survive.
"""
import bpy, sys, os, addon_utils

argv = sys.argv[sys.argv.index("--") + 1:]
OUT_XML = argv[0]
os.makedirs(os.path.dirname(OUT_XML), exist_ok=True)

# --- enable the addon (mitsuba pkg already installed in Blender's python) ---
addon_utils.enable("mitsuba_blender", default_set=True, persistent=True)

# make sure everything is selectable/visible and selected (export uses depsgraph;
# use_selection=False exports all, but select-all avoids any hidden-state issues)
for o in bpy.data.objects:
    o.hide_set(False); o.hide_viewport = False; o.hide_render = False
bpy.ops.object.select_all(action="SELECT")

res = bpy.ops.export_scene.mitsuba(
    filepath=OUT_XML,
    use_selection=False,
    split_files=False,
    export_ids=True,          # keep 'id' on shapes/bsdfs -> itu_ names survive
    ignore_background=True,
    axis_up="Z",              # Sionna expects Z-up
    axis_forward="Y",
)
print("export result:", res)
print("wrote:", OUT_XML, "exists:", os.path.exists(OUT_XML))
