"""Integrity tests against the real built manifest (skipped if not built)."""
import numpy as np
from ulap_scope import geo


def test_manifest_valid(manifest):
    assert geo.validate_manifest(manifest) == []

def test_manifest_epsg_and_origin(manifest):
    assert manifest["epsg"] == 21292
    ox, oy = manifest["origin"]
    assert 30000 < ox < 35000 and 60000 < oy < 70000     # Newton area in EPSG:21292

def test_buildings_present_and_bounded(manifest):
    b = manifest["buildings"]
    assert len(b) > 100
    xs = [p[0] for bb in b for p in bb["ring"]]
    ys = [p[1] for bb in b for p in bb["ring"]]
    # 2 km box -> everything within ~1.2 km of origin
    assert max(abs(min(xs)), abs(max(xs))) < 1300
    assert max(abs(min(ys)), abs(max(ys))) < 1300
    assert all(bb["h"] > 0 for bb in b)

def test_terrain_grid_consistent(manifest):
    t = manifest["terrain"]
    assert len(t["z"]) == t["nx"] * t["ny"]
    assert t["zmin"] < t["zmax"]
    # bilinear sample stays within the grid's own range
    z = geo.terrain_bilinear(t, 0.0, 0.0)
    assert t["zmin"] - 1 <= z <= t["zmax"] + 1

def test_towers_include_the_two_in_scene(manifest):
    names = {a["name"] for a in manifest["antennas"]}
    assert {"Newton", "Rising Sun"} <= names
