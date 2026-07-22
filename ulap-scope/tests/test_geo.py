"""Fast unit tests for the pure geometry/geo core (numpy/scipy only)."""
import numpy as np
import pytest
from ulap_scope import geo


# ---- coordinate transforms ----
def test_to_local_and_back():
    origin = (32735.32, 64854.74)
    x, y = 33000.0, 65000.0
    lx, ly = geo.to_local(x, y, origin)
    assert lx == pytest.approx(x - origin[0])
    bx, by = geo.to_crs(lx, ly, origin)
    assert (bx, by) == pytest.approx((x, y))


# ---- terrain bilinear ----
def _grid():
    # 2x2 grid over [0,10]x[0,10]; z row-major (y outer): (0,0)=0 (1,0)=10 (0,1)=20 (1,1)=30
    return {"nx": 2, "ny": 2, "minx": 0.0, "maxx": 10.0, "miny": 0.0, "maxy": 10.0,
            "z": [0.0, 10.0, 20.0, 30.0], "zmin": 0.0, "zmax": 30.0}

def test_terrain_at_corners():
    t = _grid()
    assert geo.terrain_bilinear(t, 0, 0) == pytest.approx(0)
    assert geo.terrain_bilinear(t, 10, 0) == pytest.approx(10)
    assert geo.terrain_bilinear(t, 0, 10) == pytest.approx(20)
    assert geo.terrain_bilinear(t, 10, 10) == pytest.approx(30)

def test_terrain_center_is_mean():
    assert geo.terrain_bilinear(_grid(), 5, 5) == pytest.approx(15)

def test_terrain_clamps_outside():
    t = _grid()
    assert geo.terrain_bilinear(t, -100, -100) == pytest.approx(0)
    assert geo.terrain_bilinear(t, 999, 999) == pytest.approx(30)

def test_terrain_vectorised():
    t = _grid()
    out = geo.terrain_bilinear(t, np.array([0.0, 10.0]), np.array([0.0, 10.0]))
    assert np.allclose(out, [0, 30])


# ---- footprint validation ----
def test_clean_ring_drops_closing_dup():
    ring = [[0, 0], [1, 0], [1, 1], [0, 0]]     # closed triangle
    assert geo.clean_ring(ring) == [[0, 0], [1, 0], [1, 1]]

def test_ring_too_few_points_invalid():
    assert not geo.ring_is_valid([[0, 0], [1, 1], [0, 0]])   # only 2 distinct
    assert not geo.ring_is_valid([[0, 0], [1, 0]])

def test_ring_triangle_valid():
    assert geo.ring_is_valid([[0, 0], [2, 0], [1, 2]])


# ---- ITU frequency validity ----
def test_freq_validity_windows():
    assert geo.freq_valid_for("concrete", 3.5e9)
    assert geo.freq_valid_for("concrete", 28e9)          # concrete valid to 100 GHz
    assert geo.freq_valid_for("medium_dry_ground", 3.5e9)
    assert not geo.freq_valid_for("medium_dry_ground", 28e9)   # ground only <=10 GHz
    assert not geo.freq_valid_for("concrete", 0.5e9)     # below 1 GHz


# ---- scattered DTM interpolation ----
def test_interpolate_dtm_recovers_plane():
    # z = 2x + 3y sampled at scattered points -> grid should recover the plane
    pts = [[0, 0], [10, 0], [0, 10], [10, 10], [5, 5]]
    dtm = [2 * x + 3 * y for x, y in pts]
    gx = np.linspace(0, 10, 5); gy = np.linspace(0, 10, 5)
    z = geo.interpolate_dtm(pts, dtm, gx, gy)
    assert z.shape == (5, 5)
    assert z[0, 0] == pytest.approx(0, abs=1e-6)
    assert z[-1, -1] == pytest.approx(2 * 10 + 3 * 10, abs=1e-6)


# ---- manifest schema validation (data-free, CI-friendly) ----
def _good_manifest():
    return {
        "epsg": 21292, "origin": [32735.32, 64854.74],
        "basemap": {"minx": -1000, "maxx": 1000, "miny": -1000, "maxy": 1000, "tif": "x.tif"},
        "terrain": {"nx": 2, "ny": 2, "minx": 0, "maxx": 1, "miny": 0, "maxy": 1,
                    "z": [0, 1, 2, 3], "zmin": 0, "zmax": 3},
        "buildings": [{"ring": [[0, 0], [1, 0], [1, 1]], "h": 3.0, "dtm": 80.0}],
        "antennas": [{"name": "Newton", "x": 0, "y": 0, "h": 30.0}],
    }

def test_validate_manifest_accepts_good():
    assert geo.validate_manifest(_good_manifest()) == []

def test_validate_manifest_flags_missing_key():
    m = _good_manifest(); del m["terrain"]
    assert any("terrain" in e for e in geo.validate_manifest(m))

def test_validate_manifest_flags_bad_epsg():
    m = _good_manifest(); m["epsg"] = 3857
    assert any("epsg" in e for e in geo.validate_manifest(m))

def test_validate_manifest_flags_inverted_terrain():
    m = _good_manifest(); m["terrain"]["zmin"], m["terrain"]["zmax"] = 3, 0
    assert any("zmin > zmax" in e for e in geo.validate_manifest(m))

def test_validate_manifest_flags_bad_terrain_length():
    m = _good_manifest(); m["terrain"]["z"] = [0, 1, 2]     # != nx*ny
    assert any("length" in e for e in geo.validate_manifest(m))
