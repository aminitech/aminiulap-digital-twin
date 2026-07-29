"""
Tests for the example demos.

These keep the examples honest in two ways: they check the physics helpers
against closed-form values, and they pin the headline claims the notebooks make
about the shipped ray-traced data (e.g. "n = 1.73", "sub-dB agreement"). If a
change to the model breaks a claim in a notebook, a test here fails first.

    cd examples && python -m pytest -q
"""
from __future__ import annotations

import ast
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

EXAMPLES = Path(__file__).resolve().parents[1]
REPO = EXAMPLES.parent
sys.path[:0] = [str(EXAMPLES), str(REPO / "ulap-scope")]

from ulap_demo import (  # noqa: E402
    DATA_DIR, PropagationModel, fit_log_distance, fspl_db, knife_edge_loss_db,
    load_link_metrics, load_scene, log_distance_db, noise_floor_dbm)
from ulap_demo.propagation import (  # noqa: E402
    C, fresnel_nu, fresnel_radius_m, ground_reflection_coeff, two_ray_gain_db, wavelength)
from ulap_demo.scene import SAMPLE_SCENE, SCENE_ENV_VAR, Tower, resolve_scene_path  # noqa: E402

SAMPLE_PATH = DATA_DIR / SAMPLE_SCENE


@pytest.fixture(scope="module")
def scene():
    """Always the bundled open-data sample.

    ``load_scene()`` with no argument prefers a real pipeline manifest when the
    developer has one, which is right for a human and wrong for a test: results
    would differ between a maintainer's laptop and CI."""
    return load_scene(SAMPLE_PATH)


# --------------------------------------------------------------- free space
def test_fspl_matches_closed_form():
    d, f = 1000.0, 3.5e9
    expected = 20 * np.log10(4 * np.pi * d * f / C)
    assert fspl_db(d, f) == pytest.approx(expected, abs=1e-9)


def test_fspl_doubling_rules():
    # doubling either distance or frequency costs 6.02 dB
    assert fspl_db(2000, 3.5e9) - fspl_db(1000, 3.5e9) == pytest.approx(6.0206, abs=1e-3)
    assert fspl_db(1000, 7.0e9) - fspl_db(1000, 3.5e9) == pytest.approx(6.0206, abs=1e-3)


def test_fspl_clamps_near_field():
    assert fspl_db(0.0, 3.5e9) == fspl_db(1.0, 3.5e9)


def test_wavelength():
    assert wavelength(3e8) == pytest.approx(1.0, rel=1e-3)


# ------------------------------------------------------------- diffraction
def test_knife_edge_grazing_is_about_6_db():
    assert knife_edge_loss_db(0.0) == pytest.approx(6.0, abs=0.5)


def test_knife_edge_clear_path_is_lossless():
    assert knife_edge_loss_db(-1.0) == 0.0
    assert knife_edge_loss_db(-5.0) == 0.0


def test_knife_edge_is_monotonic_in_obstruction():
    nu = np.linspace(-0.5, 10, 60)
    loss = knife_edge_loss_db(nu)
    assert np.all(np.diff(loss) >= -1e-9)
    assert loss[-1] > 25          # deeply blocked


def test_fresnel_radius_peaks_at_midpoint():
    d = np.linspace(1, 999, 400)
    F = fresnel_radius_m(d, 1000 - d, 3.5e9)
    assert np.argmax(F) == pytest.approx(len(d) // 2, abs=2)
    # first Fresnel radius at midpoint = sqrt(lambda * D / 4)
    assert F.max() == pytest.approx(np.sqrt(wavelength(3.5e9) * 1000 / 4), rel=1e-2)


def test_fresnel_nu_sign_convention():
    # obstacle above the ray -> positive nu -> loss; below -> negative -> none
    assert fresnel_nu(+5.0, 500, 500, 3.5e9) > 0
    assert fresnel_nu(-5.0, 500, 500, 3.5e9) < 0


def test_fresnel_nu_clamps_at_endpoints():
    """An obstacle at the receiver must not become an infinite wall."""
    nu = fresnel_nu(3.0, 1e-9, 500.0, 3.5e9)
    assert np.isfinite(nu) and nu < 100


# --------------------------------------------------------- ground reflection
def test_reflection_coefficient_tends_to_minus_one_at_grazing():
    g = ground_reflection_coeff(1e-6, 3.5e9)
    assert g.real == pytest.approx(-1.0, abs=1e-3)
    assert abs(g) == pytest.approx(1.0, abs=1e-3)


def test_two_ray_none_mode_is_free_space():
    assert np.all(two_ray_gain_db(np.linspace(10, 5000, 50), 24, 1.5, 3.5e9,
                                  mode="none") == 0.0)


def test_two_ray_average_is_the_incoherent_sum_below_breakpoint():
    """Below the breakpoint the fringes are averaged out, leaving the
    phase-independent power sum 1 + |Gamma|^2. That tends to +3 dB at grazing
    but dips toward 0 dB near the pseudo-Brewster angle, where a
    vertically-polarised ground reflection nearly vanishes."""
    h_t, h_r, f = 24.0, 1.5, 3.5e9
    d_bp = 4 * h_t * h_r / wavelength(f)
    for d in (d_bp / 8, d_bp / 4, d_bp / 2):
        gamma = ground_reflection_coeff(np.arctan2(h_t + h_r, d), f)
        expected = 10 * np.log10(1 + abs(gamma) ** 2)
        assert two_ray_gain_db(d, h_t, h_r, f, mode="average") == pytest.approx(
            expected, abs=1e-9)
    # far out, where the reflection is near-total, it does approach +3 dB
    far = 4 * d_bp
    assert two_ray_gain_db(far, h_t, h_r, f, mode="average") < 3.01


def test_two_ray_steepens_beyond_breakpoint():
    """Past the breakpoint the rays cancel: loss heads toward the d^-4 slope."""
    h_t, h_r, f = 24.0, 1.5, 3.5e9
    d_bp = 4 * h_t * h_r / wavelength(f)
    near = two_ray_gain_db(d_bp, h_t, h_r, f, mode="average")
    far = two_ray_gain_db(10 * d_bp, h_t, h_r, f, mode="average")
    assert far < near - 10


def test_two_ray_rejects_unknown_mode():
    with pytest.raises(ValueError):
        two_ray_gain_db(100.0, 24, 1.5, 3.5e9, mode="magic")


# ------------------------------------------------------------------- fitting
def test_fit_recovers_a_known_exponent():
    d = np.logspace(1, 3.2, 40)
    truth_n, truth_pl0 = 2.7, 41.0
    pg = -log_distance_db(d, truth_pl0, truth_n)
    fit = fit_log_distance(d, pg)
    assert fit.n == pytest.approx(truth_n, abs=1e-6)
    assert fit.pl_d0_db == pytest.approx(truth_pl0, abs=1e-6)
    assert fit.rms_db < 1e-9


def test_fit_ignores_non_finite_points():
    d = np.array([10.0, 100.0, np.nan, 1000.0])
    pg = np.array([-50.0, -70.0, -80.0, -90.0])
    assert fit_log_distance(d, pg).n_points == 3


def test_noise_floor():
    # kTB at 1 Hz with 0 dB NF is -174 dBm/Hz
    assert noise_floor_dbm(1.0, 0.0) == pytest.approx(-174.0, abs=0.1)
    assert noise_floor_dbm(100e6, 7.0) == pytest.approx(-87.0, abs=0.2)


# --------------------------------------------------------------- sample data
def test_link_metrics_load():
    lm = load_link_metrics()
    assert set(lm) == {"distance_m", "path_gain_dB", "delay_spread_ns", "num_paths"}
    assert len(lm["distance_m"]) == 14


def test_ray_traced_exponent_is_sub_free_space():
    """The pilot's transect fits n = 1.73 -- notebook 02 says so out loud."""
    lm = load_link_metrics()
    fit = fit_log_distance(lm["distance_m"], lm["path_gain_dB"])
    assert fit.n == pytest.approx(1.73, abs=0.02)
    assert fit.n < 2.0
    assert fit.rms_db < 0.3


def test_sample_manifest_structure_is_valid():
    """The bundled sample passes every pipeline check except the EPSG one.

    ``validate_manifest`` is hard-coded to the pilot's national grid (21292); our
    open-data sample is in UTM 21N. Notebook 03 explains this and flags relaxing
    the check as a good first contribution. If someone does relax it, this test
    should start expecting an empty list."""
    from ulap_scope.geo import validate_manifest
    m = json.loads(SAMPLE_PATH.read_text())
    assert validate_manifest(m) == ["epsg should be 21292, got 32621"]


def test_sample_study_round_trips():
    from ulap_scope.study import load_study
    spec = load_study(DATA_DIR / "newton-bbd.study.toml")
    assert spec.name == "newton-bbd"
    assert spec.epsg == spec.recommended_epsg == 32621
    assert spec.crs_warning() is None


def test_shipped_manifest_has_no_developer_paths():
    """The sample must not leak an absolute path from whoever generated it."""
    text = SAMPLE_PATH.read_text()
    assert "/Users/" not in text and "/home/" not in text


def test_shipped_data_is_open_and_attributed():
    """DATA.md: no licence-restricted geospatial layer is committed. The sample
    scene must therefore be open data, and must say so."""
    prov = json.loads(SAMPLE_PATH.read_text())["provenance"]
    assert "OpenStreetMap" in prov["buildings"]["source"]
    assert "ODbL" in prov["buildings"]["licence"]
    assert "Terrain Tiles" in prov["terrain"]["source"]
    assert prov["terrain"]["licence"]
    assert "PLACEHOLDER" in prov["towers"]["note"]


def test_no_geoportal_derived_scene_is_committed():
    """Guard against the Barbados Geoportal layers reappearing here while their
    disclosure review is open (see DATA.md)."""
    for path in DATA_DIR.glob("*.json"):
        m = json.loads(path.read_text())
        if "epsg" not in m:
            continue
        assert m["epsg"] != 21292, (
            f"{path.name} is in the Barbados National Grid — that scene is "
            "geoportal-derived and must not be committed; see DATA.md")


# ------------------------------------------------------- repository hygiene
def _tracked_files():
    """Every file git tracks, or None when we are not in a git checkout."""
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True,
                             text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return [REPO / f for f in out.stdout.split("\0") if f]


def test_no_developer_paths_in_tracked_files():
    """No tracked file may embed an absolute home directory.

    This has bitten twice: two `blender/` scripts hard-coded a developer's
    project path, and Blender wrote the same path into a PNG `tEXt` chunk in
    `docs/renders/`. Both disclose a username; neither is visible in a diff of a
    binary. This test reads bytes, so it catches the metadata case too."""
    tracked = _tracked_files()
    if tracked is None:
        pytest.skip("not a git checkout")

    # This file legitimately contains the literal string while documenting the rule.
    allowed = {Path(__file__).resolve()}
    markers = (b"/Users/", b"/home/", b"C:\\\\Users")
    # Documentation *about* the rule writes the path with a placeholder segment
    # (`/Users/<name>/...`, `/home/$USER/...`). A real leak has an actual
    # username there, so key on the character right after the prefix rather than
    # maintaining an allowlist of every doc that mentions the pattern.
    placeholders = (b"<", b"$", b"{", b"~", b".", b"*")
    offenders = []
    for path in tracked:
        if path in allowed or not path.is_file():
            continue
        blob = path.read_bytes()
        for marker in markers:
            start = 0
            while (idx := blob.find(marker, start)) != -1:
                nxt = blob[idx + len(marker):idx + len(marker) + 1]
                if nxt and nxt not in placeholders:
                    offenders.append(f"{path.relative_to(REPO)} :: "
                                     f"{blob[idx:idx + 60].decode('latin-1')!r}")
                    break
                start = idx + len(marker)
            else:
                continue
            break
    assert not offenders, "developer path leaked into tracked files:\n  " + "\n  ".join(offenders)


def test_blender_working_dir_is_not_tracked():
    """`blender/` is a working directory: the pipeline's outputs there are both
    regenerable and geoportal-derived, so only notes and render helpers belong
    in git. See DATA.md."""
    tracked = _tracked_files()
    if tracked is None:
        pytest.skip("not a git checkout")

    under_blender = {p.relative_to(REPO).as_posix() for p in tracked
                     if p.relative_to(REPO).as_posix().startswith("blender/")}
    assert under_blender == {
        "blender/barbados_blender_sionna_pipeline.md",
        "blender/render_perspective.py",
        "blender/render_sionna_perspective.py",
    }, f"unexpected tracked files under blender/: {sorted(under_blender)}"


# -------------------------------------------------------------------- scene
def test_scene_loads(scene):
    assert len(scene.buildings) == 585
    assert scene.epsg == 32621                      # UTM 21N — metric
    assert len(scene.towers) == 2
    assert len(scene.towers_in_scene()) == 2
    assert 1900 < scene.size_m[0] < 2100
    assert "OpenStreetMap" in scene.sources()


def test_scene_resolution_order(tmp_path, monkeypatch):
    """Explicit path beats $ULAP_SCENE beats the bundled open-data sample."""
    monkeypatch.delenv(SCENE_ENV_VAR, raising=False)
    explicit = tmp_path / "mine.json"
    explicit.write_text("{}")
    assert resolve_scene_path(explicit) == explicit

    monkeypatch.setenv(SCENE_ENV_VAR, str(explicit))
    assert resolve_scene_path() == explicit
    assert resolve_scene_path(SAMPLE_PATH) == SAMPLE_PATH      # argument still wins

    monkeypatch.setenv(SCENE_ENV_VAR, str(tmp_path / "nope.json"))
    with pytest.raises(FileNotFoundError):
        resolve_scene_path()


def test_default_scene_is_always_the_open_sample(monkeypatch):
    """The default must not depend on whose checkout this is.

    A clone may contain `blender/scene_build/scene_manifest.json` (it is tracked),
    and that scene is licence-restricted -- see DATA.md. Selecting it must be an
    explicit opt-in, never the default."""
    monkeypatch.delenv(SCENE_ENV_VAR, raising=False)
    assert resolve_scene_path() == SAMPLE_PATH
    assert load_scene().epsg == 32621          # UTM, i.e. the open sample


def test_pipeline_hint_mentions_the_env_var():
    from ulap_demo.scene import PIPELINE_SCENE, pipeline_scene_hint
    hint = pipeline_scene_hint()
    if PIPELINE_SCENE.exists():
        assert SCENE_ENV_VAR in hint and str(PIPELINE_SCENE) in hint
    else:
        assert hint == ""


def test_missing_scene_raises_clearly(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_scene(tmp_path / "absent.json")


def test_scene_lookup_and_crs(scene):
    t = scene.tower("rising sun")
    assert t.name == "Rising Sun" and t.h == 24.0
    assert t.z == pytest.approx(t.ground_z + t.h)
    x, y = scene.to_crs(0.0, 0.0)
    assert (x, y) == pytest.approx(scene.origin)
    with pytest.raises(KeyError):
        scene.tower("nowhere")


def test_terrain_sampling_stays_in_range(scene):
    X, Y, _ = scene.grid(cell_m=50.0)
    z = scene.terrain_z(X, Y)
    t = scene.terrain
    assert z.shape == X.shape
    assert z.min() >= t["zmin"] - 1e-6
    assert z.max() <= t["zmax"] + 1e-6


def test_terrain_sampling_clamps_outside_the_grid(scene):
    assert np.isfinite(scene.terrain_z(1e6, 1e6))
    assert np.isfinite(scene.terrain_z(-1e6, -1e6))


def test_height_raster_covers_buildings(scene):
    r = scene.height_raster(cell_m=5.0)
    bh = r.building_height
    assert np.all(bh >= -1e-9)                       # never below ground
    assert (bh > 0.1).sum() > 1000                   # footprints actually burned in
    assert bh.max() == pytest.approx(scene.building_heights().max(), abs=0.01)
    assert r.top.shape == r.ground.shape


def test_height_raster_is_cached(scene):
    assert scene.height_raster(5.0) is scene.height_raster(5.0)
    assert scene.height_raster(5.0) is not scene.height_raster(10.0)


def test_every_building_is_represented_at_coarse_resolution(scene):
    """Footprints smaller than a pixel must not silently vanish."""
    coarse = scene.height_raster(cell_m=20.0)
    assert (coarse.building_height > 0.1).sum() >= 300


# -------------------------------------------------------------------- model
def test_flat_empty_model_reduces_to_free_space_plus_two_ray(scene):
    """With terrain and buildings off, the model must equal the closed form."""
    m = PropagationModel(use_terrain=False, use_buildings=False,
                         ground_reflection="none")
    t = Tower(name="probe", x=0.0, y=0.0, h=30.0, ground_z=0.0)
    d = np.array([100.0, 500.0, 1000.0])
    pg = m.path_gain_db(scene, t, d, np.zeros_like(d))
    expected = -fspl_db(np.hypot(d, 30.0 - m.rx_height_m), m.freq_hz)
    assert pg == pytest.approx(expected, abs=1e-6)


def test_path_gain_decreases_with_distance(scene):
    m = PropagationModel(use_terrain=False, use_buildings=False)
    t = Tower(name="probe", x=0.0, y=0.0, h=30.0, ground_z=0.0)
    d = np.array([50.0, 200.0, 800.0, 1500.0])
    pg = m.path_gain_db(scene, t, d, np.zeros_like(d))
    assert np.all(np.diff(pg) < 0)


def test_higher_frequency_loses_more(scene):
    t = scene.tower("Newton")
    X, Y, _ = scene.grid(cell_m=50.0)
    lo = PropagationModel(freq_hz=1.8e9).path_gain_db(scene, t, X, Y)
    hi = PropagationModel(freq_hz=28e9).path_gain_db(scene, t, X, Y)
    assert np.median(hi) < np.median(lo)


def test_obstacles_only_ever_cost_signal(scene):
    """Turning geometry on can lower a pixel but must never raise it, for a
    fixed antenna height above a fixed ground."""
    t = Tower(name="probe", x=0.0, y=0.0, h=40.0, ground_z=0.0)
    X, Y, _ = scene.grid(cell_m=40.0)
    clear = PropagationModel(use_terrain=False, use_buildings=False)
    built = PropagationModel(use_terrain=False, use_buildings=True)
    assert np.all(built.path_gain_db(scene, t, X, Y)
                  <= clear.path_gain_db(scene, t, X, Y) + 1e-9)


def test_diffraction_cap_is_respected(scene):
    t = scene.tower("Newton")
    X, Y, _ = scene.grid(cell_m=40.0)
    m = PropagationModel(max_diffraction_db=12.0)
    _, parts = m.path_gain_db(scene, t, X, Y, return_parts=True)
    assert parts["diffraction_db"].max() <= 12.0 + 1e-9


def test_return_parts_decomposes_the_budget(scene):
    t = scene.tower("Newton")
    X, Y, _ = scene.grid(cell_m=60.0)
    m = PropagationModel()
    pg, parts = m.path_gain_db(scene, t, X, Y, return_parts=True)
    recomposed = -parts["fspl_db"] + parts["two_ray_db"] - parts["diffraction_db"]
    assert pg == pytest.approx(recomposed, abs=1e-9)
    assert parts["los"].dtype == bool


def test_model_reproduces_the_ray_traced_transect(scene):
    """Headline claim of notebook 02: after one calibration constant, the
    analytical model tracks Sionna RT along the Rising Sun radial to under a dB,
    and recovers the path-loss exponent to within 0.1.

    The clear-path model is the right comparison because the ray tracer itself
    reports exactly two paths (direct + ground reflection) at most points."""
    lm = load_link_metrics()
    assert (lm["num_paths"] == 2).sum() >= 10
    m = PropagationModel(freq_hz=3.5e9, use_terrain=False, use_buildings=False)
    pg = m.radial(scene, scene.tower("Rising Sun"), lm["distance_m"])

    rt_n = fit_log_distance(lm["distance_m"], lm["path_gain_dB"]).n
    model_n = fit_log_distance(lm["distance_m"], pg).n
    assert abs(rt_n - model_n) < 0.1

    resid = lm["path_gain_dB"] - pg
    assert np.sqrt(np.mean((resid - resid.mean()) ** 2)) < 1.0


# ----------------------------------------------------------------- coverage
def test_coverage_shapes_and_invariants(scene):
    m = PropagationModel()
    cov = m.coverage(scene, cell_m=40.0)
    n_tx = len(scene.towers_in_scene())
    assert cov.path_gain_db.shape[0] == n_tx
    assert cov.rsrp_dbm.shape == cov.path_gain_db.shape
    assert cov.best_rsrp_dbm.shape == cov.sinr_db.shape == cov.X.shape
    assert cov.best_server.min() >= 0 and cov.best_server.max() < n_tx
    assert np.all(np.isfinite(cov.sinr_db))
    # best server really is the strongest
    assert np.allclose(cov.best_rsrp_dbm, cov.rsrp_dbm.max(axis=0))


def test_coverage_fraction_is_monotonic_in_threshold(scene):
    cov = PropagationModel().coverage(scene, cell_m=40.0)
    thresholds = [-130, -110, -95, -80, -60]
    fractions = [cov.fraction_above(t) for t in thresholds]
    assert all(a >= b for a, b in zip(fractions, fractions[1:]))
    assert fractions[0] == 1.0


def test_server_share_sums_to_one(scene):
    cov = PropagationModel().coverage(scene, cell_m=40.0)
    assert sum(cov.server_share().values()) == pytest.approx(1.0)
    assert cov.summary()          # renders without raising


def test_more_power_never_reduces_sinr_with_uniform_sites(scene):
    """Raising every site's power equally lifts RSRP but leaves SINR alone."""
    low = PropagationModel(tx_power_dbm=20.0).coverage(scene, cell_m=40.0)
    high = PropagationModel(tx_power_dbm=40.0).coverage(scene, cell_m=40.0)
    assert np.all(high.best_rsrp_dbm > low.best_rsrp_dbm)
    assert np.median(high.sinr_db) >= np.median(low.sinr_db) - 0.01


def test_adding_a_site_raises_rsrp(scene):
    m = PropagationModel()
    base = m.coverage(scene, cell_m=40.0)
    extra = Tower(name="Candidate", x=250.0, y=350.0, h=25.0,
                  ground_z=float(scene.terrain_z(250.0, 350.0)))
    more = m.coverage(scene, towers=scene.towers_in_scene() + [extra], cell_m=40.0)
    assert np.median(more.best_rsrp_dbm) > np.median(base.best_rsrp_dbm)


def test_coverage_requires_a_tower(scene):
    """And the error has to say what to do about it -- this is the failure a
    user hits after building a scene whose sites fell outside the study box."""
    with pytest.raises(ValueError) as exc:
        PropagationModel().coverage(scene, towers=[], cell_m=100.0)
    msg = str(exc.value)
    assert "no towers to serve the scene" in msg
    assert "inside the study box" in msg or "no 'antennas' entries" in msg


# ----------------------------------------------------- open-data scene builder
sys.path.insert(0, str(EXAMPLES / "data"))
import fetch_open_scene as fos  # noqa: E402


def test_utm_zone_selection():
    assert fos.utm_zone_epsg(-59.533908, 13.088121) == (21, 32621)
    assert fos.utm_zone_epsg(36.8219, -1.2921) == (37, 32737)      # southern
    assert fos.utm_zone_epsg(120.9842, 14.5995) == (51, 32651)
    assert fos.utm_zone_epsg(-179.9, 0.0)[0] == 1
    assert fos.utm_zone_epsg(179.9, 0.0)[0] == 60


def test_utm_central_meridian_is_the_false_easting():
    for zone in (1, 21, 30, 60):
        e, _ = fos.lonlat_to_utm(zone * 6 - 183, 10.0, zone, True)
        assert float(e) == pytest.approx(500_000.0, abs=1e-6)


def test_utm_matches_reference_values():
    """Checked against pyproj (EPSG:4326 -> EPSG:326xx) to the millimetre."""
    for lon, lat, zone, north, ee, en in [
        (-59.533908, 13.088121, 21, True, 225235.90, 1448257.23),
        (36.8219, -1.2921, 37, False, 257634.50, 9857079.97),
        (-0.1276, 51.5072, 30, True, 699330.98, 5710142.07),
        (-21.9426, 64.1466, 27, True, 454138.38, 7113689.87),
    ]:
        e, n = fos.lonlat_to_utm(lon, lat, zone, north)
        assert float(e) == pytest.approx(ee, abs=0.01)
        assert float(n) == pytest.approx(en, abs=0.01)


def test_utm_southern_hemisphere_uses_the_false_northing():
    _, n = fos.lonlat_to_utm(36.8219, -1.2921, 37, False)
    assert 9_000_000 < float(n) < 10_000_000


def test_building_height_precedence():
    assert fos.building_height_m({"height": "12.5"}) == (12.5, "osm:height")
    assert fos.building_height_m({"height": "9 m"})[0] == 9.0
    assert fos.building_height_m({"building:levels": "4"}) == (12.0, "osm:levels")
    # an explicit height wins over a level count
    assert fos.building_height_m({"height": "7", "building:levels": "9"})[0] == 7.0
    # unparseable tags fall through to the type table rather than crashing
    h, how = fos.building_height_m({"height": "tall", "building": "house"})
    assert h == fos.DEFAULT_HEIGHTS_M["house"] and how.startswith("default")
    assert fos.building_height_m({"building": "not_a_real_type"})[0] == fos.DEFAULT_HEIGHT_M


def test_bbox_is_square_in_metres():
    lon, lat, half = -59.5339, 13.0881, 1000.0
    min_lon, min_lat, max_lon, max_lat = fos.bbox_deg(lon, lat, half)
    ns = (max_lat - min_lat) * 111_320
    ew = (max_lon - min_lon) * 111_320 * math.cos(math.radians(lat))
    assert ns == pytest.approx(2 * half, rel=0.01)
    assert ew == pytest.approx(2 * half, rel=0.01)


def test_tile_math_matches_the_known_slippy_map_formula():
    # London (-0.1276, 51.5072) is slippy tile 511/340 at zoom 10
    x, y = fos._tile_xy(-0.1276, 51.5072, 10)
    assert (int(x), int(y)) == (511, 340)
    # the north-west corner of the Web Mercator world maps to tile origin (0, 0)
    x, y = fos._tile_xy(-180.0, 85.0511, 3)
    assert float(x) == pytest.approx(0.0, abs=1e-6)
    assert float(y) == pytest.approx(0.0, abs=1e-4)


def test_tower_template_scales_with_the_study_box():
    """Fixed metre offsets fall outside a smaller study area, leaving the scene
    with no serving site. The template is expressed as a fraction of the
    half-width so it lands inside the box at any size."""
    for entry in fos.TOWER_TEMPLATE:
        fx, fy = entry["offset_frac"]
        assert abs(fx) <= 1.0 and abs(fy) <= 1.0, entry["name"]


def test_tower_placement_accepts_all_three_position_forms():
    """offset_frac scales, offset_m is absolute, lon/lat is projected."""
    import io
    from contextlib import redirect_stdout

    osm = {"elements": [{"id": 1, "geometry": [
        {"lon": -59.5340, "lat": 13.0880}, {"lon": -59.5339, "lat": 13.0880},
        {"lon": -59.5339, "lat": 13.0881}, {"lon": -59.5340, "lat": 13.0881}],
        "tags": {"building": "house"}}]}
    with open(tmp := (Path(subprocess.os.environ.get("TMPDIR", "/tmp")) / "_ulap_osm.json"),
              "w") as fh:
        json.dump(osm, fh)

    # Only the tower maths is under test; monkeypatch the network away.
    real_terrain = fos.fetch_terrain_grid
    fos.fetch_terrain_grid = lambda bbox, nx, ny, zoom=13: np.zeros((ny, nx))
    towers = Path(subprocess.os.environ.get("TMPDIR", "/tmp")) / "_ulap_towers.json"
    towers.write_text(json.dumps([
        {"_comment": "should be skipped"},
        {"name": "frac", "offset_frac": [0.5, -0.5], "h": 20.0},
        {"name": "metres", "offset_m": [100.0, 200.0], "h": 20.0},
        {"name": "lonlat", "lon": -59.533908, "lat": 13.088121, "h": 20.0},
    ]))
    try:
        with redirect_stdout(io.StringIO()):
            m = fos.build_manifest("t", -59.533908, 13.088121, 500.0, 13,
                                   str(towers), 8, str(tmp))
    finally:
        fos.fetch_terrain_grid = real_terrain

    by_name = {a["name"]: a for a in m["antennas"]}
    assert set(by_name) == {"frac", "metres", "lonlat"}      # _comment skipped
    assert by_name["frac"]["x"] == pytest.approx(250.0)      # 0.5 * 500 m
    assert by_name["frac"]["y"] == pytest.approx(-250.0)
    assert by_name["metres"]["x"] == pytest.approx(100.0)
    assert by_name["lonlat"]["x"] == pytest.approx(0.0, abs=0.5)   # the centre
    assert by_name["lonlat"]["y"] == pytest.approx(0.0, abs=0.5)
    assert all(a["in_scene"] for a in m["antennas"])


def test_bundled_sample_sites_are_inside_the_box(scene):
    """Whatever else changes, the shipped scene must be servable."""
    assert scene.towers_in_scene(), "no in-scene tower: coverage() would raise"


def test_ssl_advice_is_actionable():
    """A local trust-store failure must not be reported as a rate limit."""
    assert issubclass(fos.CertificateError, RuntimeError)
    for hint in ("Install Certificates", "pip install certifi", "--osm-json"):
        assert hint in fos._SSL_ADVICE


def test_tile_math_is_vectorised():
    x, y = fos._tile_xy(np.array([-59.5, 36.8]), np.array([13.1, -1.3]), 10)
    assert x.shape == y.shape == (2,)


# ---------------------------------------------------------------- notebooks
NOTEBOOKS = sorted((EXAMPLES / "notebooks").glob("*.ipynb"))


def test_notebooks_exist():
    assert len(NOTEBOOKS) == 4


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: p.name)
def test_notebook_code_cells_compile(path):
    """Cheap guard against a broken notebook: every code cell must parse."""
    nb = json.loads(path.read_text())
    for i, cell in enumerate(nb["cells"]):
        if cell["cell_type"] != "code":
            continue
        src = "".join(cell["source"])
        if src.lstrip().startswith("%") or "\n%" in src:
            continue                       # IPython magics are not Python
        ast.parse(src)


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: p.name)
def test_notebook_outputs_are_stripped(path):
    """Committed notebooks stay diff-friendly: no stored outputs."""
    nb = json.loads(path.read_text())
    for cell in nb["cells"]:
        if cell["cell_type"] == "code":
            assert cell.get("outputs") == []
            assert cell.get("execution_count") is None


# --------------------------------------------------------------------- apps
def test_drive_test_app_runs(tmp_path):
    """End-to-end smoke test of the drive-test app (a few frames only)."""
    pytest.importorskip("matplotlib")
    out = tmp_path / "drive.gif"
    r = subprocess.run(
        [sys.executable, str(EXAMPLES / "apps" / "drive_test" / "drive_test.py"),
         "--frames", "4", "--cell-m", "40", "--out", str(out)],
        capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stderr
    assert out.exists() and out.stat().st_size > 0
    csv_out = out.with_suffix(".csv")
    assert csv_out.exists()
    header = csv_out.read_text().splitlines()[0]
    assert "serving_tower" in header and "sinr_db" in header


def test_twin_viewer_app_reports_a_missing_page(tmp_path):
    r = subprocess.run(
        [sys.executable, str(EXAMPLES / "apps" / "twin_viewer" / "serve.py"),
         "--page", "does-not-exist.html", "--no-open"],
        capture_output=True, text=True, timeout=120)
    assert r.returncode == 1
    assert "not found" in r.stderr


def test_coverage_explorer_app_compiles():
    src = (EXAMPLES / "apps" / "coverage_explorer" / "app.py").read_text()
    ast.parse(src)
