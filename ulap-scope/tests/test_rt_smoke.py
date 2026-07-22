"""
Integration smoke test for the exported Mitsuba scene in Sionna RT.
Marked `rt`; auto-skips unless run in the Sionna env with a built scene.

Run explicitly:
    /opt/anaconda3/envs/sionna/bin/python -m pytest -m rt tests/test_rt_smoke.py
"""
import numpy as np
import pytest
from conftest import sionna_available

pytestmark = pytest.mark.rt

pytest.importorskip  # noqa
if not sionna_available():
    pytest.skip("sionna.rt not importable in this interpreter", allow_module_level=True)


@pytest.fixture(scope="module")
def scene(cfg):
    xml = cfg.work_dir / "mitsuba_scene" / "scene.xml"
    if not xml.exists():
        pytest.skip(f"scene not exported at {xml}")
    from sionna.rt import load_scene
    sc = load_scene(str(xml)); sc.frequency = 3.5e9
    return sc


def test_itu_materials_recognised(scene):
    from sionna.rt import ITURadioMaterial
    mats = scene.radio_materials
    assert "itu_concrete" in mats and "itu_medium_dry_ground" in mats
    assert all(isinstance(m, ITURadioMaterial) for m in mats.values())


def test_scene_bbox_is_local_metres(scene):
    bb = scene.mi_scene.bbox()
    # scene spans the ~2 km box centred on the origin, Z-up, buildings <= ~15 m
    assert -1300 < float(bb.min[0]) < 0 and 0 < float(bb.max[0]) < 1300
    assert 0 <= float(bb.min[2]) < 1 and float(bb.max[2]) < 20


def test_radio_map_has_finite_coverage(scene):
    from sionna.rt import PlanarArray, Transmitter, RadioMapSolver
    scene.tx_array = PlanarArray(num_rows=1, num_cols=1, pattern="tr38901", polarization="V")
    scene.rx_array = PlanarArray(num_rows=1, num_cols=1, pattern="dipole", polarization="V")
    scene.add(Transmitter("t", [970.3, -131.1, 24.0]))
    bb = scene.mi_scene.bbox()
    cx = float((bb.min[0]+bb.max[0])/2); cy = float((bb.min[1]+bb.max[1])/2)
    sx = float(bb.max[0]-bb.min[0]); sy = float(bb.max[1]-bb.min[1])
    rm = RadioMapSolver()(scene=scene, max_depth=3, cell_size=(20., 20.),
                          samples_per_tx=10**5, center=[cx, cy, 1.5],
                          size=[sx, sy], orientation=[0., 0., 0.])
    pg = np.array(rm.path_gain)
    assert np.isfinite(pg).any() and (pg > 0).any()
