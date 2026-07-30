"""
Integration test for the **shipped open-data Mitsuba scene**.

`examples/data/open_scene_mitsuba/` is committed, so unlike `test_rt_smoke.py`
(which needs a scene exported from the licence-restricted Barbados data) this
test runs from a fresh clone with nothing but the Sionna RT environment. That
is the whole point of the scene: the ray-tracing path is reproducible by a
stranger.

Marked `rt`; auto-skips unless run in the Sionna env.

    <rt python> -m pytest -m rt tests/test_open_scene_rt.py
"""
import struct
from collections import Counter
from pathlib import Path

import numpy as np
import pytest
from conftest import sionna_available

pytestmark = pytest.mark.rt

if not sionna_available():
    pytest.skip("sionna.rt not importable in this interpreter", allow_module_level=True)

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "examples" / "data" / "newton-open_scene_manifest.json"
SCENE_DIR = REPO / "examples" / "data" / "open_scene_mitsuba"

# (mode, scene dir, ground mesh name). "terrain" is the default scene at the top
# level; "flat" is the z=0 control variant.
VARIANTS = [
    ("terrain", SCENE_DIR, "Terrain"),
    ("flat", SCENE_DIR / "flat", "Ground"),
]
IDS = [v[0] for v in VARIANTS]

# The manifest is a 2 km study box centred on the local origin, so every vertex
# must land inside a generous version of that box. A scene exported in degrees,
# in feet, or Y-up fails here rather than quietly producing wrong physics.
HALF_BOX_M = 1000.0
MAX_OVERSHOOT_M = 400.0          # ground margin + footprints spilling over the edge


def _load(scene_dir: Path):
    from sionna.rt import load_scene
    xml = scene_dir / "scene.xml"
    assert xml.exists(), f"shipped scene missing at {xml}"
    sc = load_scene(str(xml))
    sc.frequency = 3.5e9
    return sc


@pytest.fixture(scope="module", params=VARIANTS, ids=IDS)
def variant(request):
    mode, scene_dir, ground = request.param
    return mode, scene_dir, ground, _load(scene_dir)


def read_ply(path: Path):
    """Minimal binary-little-endian PLY reader, enough for our own output."""
    raw = path.read_bytes()
    cut = raw.index(b"end_header\n") + len(b"end_header\n")
    header = raw[:cut].decode("ascii")
    nv = int(next(l for l in header.splitlines()
                  if l.startswith("element vertex")).split()[-1])
    nf = int(next(l for l in header.splitlines()
                  if l.startswith("element face")).split()[-1])
    verts = np.frombuffer(raw[cut:cut + nv * 12], dtype="<f4").reshape(nv, 3)
    rec = np.frombuffer(raw[cut + nv * 12: cut + nv * 12 + nf * 13],
                        dtype=np.dtype([("n", "u1"), ("i", "<3u4")]))
    assert (rec["n"] == 3).all(), "expected a triangle mesh"
    return verts, rec["i"].astype(np.int64)


# ------------------------------------------------------------------ scene load
def test_scene_files_are_shipped():
    for _mode, d, ground in VARIANTS:
        assert (d / "scene.xml").exists()
        assert (d / "meshes" / f"{ground}.ply").exists()
        assert (d / "meshes" / "Buildings.ply").exists()


def test_itu_materials_recognised(variant):
    from sionna.rt import ITURadioMaterial
    _mode, _d, _g, scene = variant
    mats = scene.radio_materials
    assert "itu_concrete" in mats, sorted(mats)
    assert "itu_medium_dry_ground" in mats, sorted(mats)
    assert all(isinstance(m, ITURadioMaterial) for m in mats.values())


def test_scene_bbox_is_local_metres(variant):
    mode, _d, _g, scene = variant
    bb = scene.mi_scene.bbox()
    lo = [float(bb.min[i]) for i in range(3)]
    hi = [float(bb.max[i]) for i in range(3)]

    lim = HALF_BOX_M + MAX_OVERSHOOT_M
    for ax in (0, 1):
        assert -lim < lo[ax] < 0, f"axis {ax} min {lo[ax]} outside the study box"
        assert 0 < hi[ax] < lim, f"axis {ax} max {hi[ax]} outside the study box"
        assert 1800.0 < hi[ax] - lo[ax] < 2 * lim, "scene is not ~2 km across"

    # Z-up: the vertical axis must be far shorter than the horizontal ones.
    assert (hi[2] - lo[2]) < 0.2 * (hi[0] - lo[0])

    if mode == "flat":
        assert -0.01 <= lo[2] < 0.01, "flat ground must sit at z = 0"
        assert 0.0 < hi[2] < 30.0, f"building tops at {hi[2]} m are implausible"
    else:
        # true elevations from the manifest's terrain grid (~60-117 m here)
        t = _manifest()["terrain"]
        assert t["zmin"] - 1.0 <= lo[2] <= t["zmin"] + 5.0
        assert t["zmax"] <= hi[2] <= t["zmax"] + 30.0


def _manifest():
    import json
    return json.loads(MANIFEST.read_text())


# -------------------------------------------------------------------- geometry
def test_buildings_are_closed_solids():
    """Every edge shared by exactly two faces, and outward-facing normals.

    An open or inverted building box lets rays leak inside and reflect off the
    wrong surface, which shows up as spurious energy in shadowed cells.
    """
    verts, faces = read_ply(SCENE_DIR / "meshes" / "Buildings.ply")
    edges = Counter()
    for a, b, c in faces:
        for u, v in ((a, b), (b, c), (c, a)):
            edges[(min(u, v), max(u, v))] += 1
    assert set(edges.values()) == {2}, \
        f"non-manifold building mesh: edge degrees {sorted(set(edges.values()))}"

    p = verts[faces].astype(np.float64)
    signed_volume = np.einsum("ij,ij->i", p[:, 0],
                              np.cross(p[:, 1], p[:, 2])).sum() / 6.0
    assert signed_volume > 0, "building normals point inward"


def test_building_heights_match_the_manifest():
    man = _manifest()
    hs = [b["h"] for b in man["buildings"]]
    verts, _ = read_ply(SCENE_DIR / "flat" / "meshes" / "Buildings.ply")
    # flat variant runs 0 -> h, so the mesh's z extent is exactly the height range
    assert abs(float(verts[:, 2].min()) - 0.0) < 1e-3
    assert abs(float(verts[:, 2].max()) - max(hs)) < 1e-3
    assert 2.0 < np.mean(hs) < 60.0, "OSM default heights are out of plausible range"


def test_scene_regenerates_byte_identical(tmp_path):
    """The committed scene is exactly what the exporter produces today."""
    import sys
    sys.path.insert(0, str(REPO / "ulap-scope"))
    from ulap_scope.stages.export_mitsuba_direct import export

    for mode, shipped, _ground in VARIANTS:
        out = tmp_path / mode
        export(MANIFEST, out, mode=mode, quiet=True)
        for rel in sorted(p.relative_to(out) for p in out.rglob("*") if p.is_file()):
            assert (shipped / rel).exists(), f"{rel} missing from the committed scene"
            assert (shipped / rel).read_bytes() == (out / rel).read_bytes(), \
                f"{mode}/{rel} differs from a fresh export"


# ------------------------------------------------------------------- ray tracing
def test_radio_map_has_finite_coverage(variant):
    from sionna.rt import PlanarArray, Transmitter, RadioMapSolver
    mode, _d, _g, scene = variant
    scene = _load(_d)          # fresh copy: transmitters must not leak between tests

    scene.tx_array = PlanarArray(num_rows=1, num_cols=1,
                                 pattern="tr38901", polarization="V")
    scene.rx_array = PlanarArray(num_rows=1, num_cols=1,
                                 pattern="dipole", polarization="V")

    # Transmitter placeholders come from the manifest -- there is no open tower
    # registry, so these positions are illustrative, not surveyed sites.
    antennas = _manifest()["antennas"]
    assert antennas, "manifest carries no antennas"
    for a in antennas:
        z = a["h"] + (a["ground_z"] if mode == "terrain" else 0.0)
        scene.add(Transmitter(a["name"].replace(" ", "_"), [a["x"], a["y"], z]))

    bb = scene.mi_scene.bbox()
    cx = float((bb.min[0] + bb.max[0]) / 2)
    cy = float((bb.min[1] + bb.max[1]) / 2)
    sx = float(bb.max[0] - bb.min[0])
    sy = float(bb.max[1] - bb.min[1])
    # A radio map is a single horizontal plane. Over terrain there is no "1.5 m
    # above ground" plane, so we sample just above the highest ground instead --
    # see docs/OPEN-DATA-SCENE.md, "A flat plane over non-flat ground".
    plane_z = 1.5 + (float(bb.max[2]) if mode == "terrain" else 0.0)

    rm = RadioMapSolver()(scene=scene, max_depth=3, cell_size=(20., 20.),
                          samples_per_tx=10**5, center=[cx, cy, plane_z],
                          size=[sx, sy], orientation=[0., 0., 0.])
    pg = np.array(rm.path_gain)

    assert pg.shape[0] == len(antennas)
    assert np.isfinite(pg).all(), "radio map contains NaN/inf"
    total = pg.sum(axis=0)
    lit = total[total > 0]
    assert lit.size > 0.10 * total.size, \
        f"only {lit.size}/{total.size} cells received any energy"

    db = 10.0 * np.log10(lit)
    assert -200.0 < db.min() and db.max() < 0.0, \
        f"path gain {db.min():.1f}..{db.max():.1f} dB is not physical"
    assert -180.0 < float(np.median(db)) < -40.0
