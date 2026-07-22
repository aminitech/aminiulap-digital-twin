"""Unit tests for the study spec: geodesy, validation, TOML round-trip.

Pure stdlib -- runs anywhere, no GIS deps.
"""
import pytest

from ulap_scope import study
from ulap_scope.study import Layer, StudySpec


# ---- UTM recommendation ----
def test_utm_barbados_is_21n():
    # Barbados (-59.53) is just east of the -60 zone boundary -> zone 21 north
    assert study.utm_zone(-59.533908, 13.088121) == (21, "N")
    assert study.utm_epsg(-59.533908, 13.088121) == 32621

def test_utm_london_is_30n():
    assert study.utm_epsg(-0.1276, 51.5072) == 32630

def test_utm_sydney_is_southern():
    assert study.utm_epsg(151.2093, -33.8688) == 32756

def test_utm_zone_clamped_at_antimeridian():
    zone, _ = study.utm_zone(180.0, 0.0)
    assert 1 <= zone <= 60


# ---- bbox math ----
def test_bbox_is_centred_and_ordered():
    lon, lat = -59.5339, 13.0881
    minx, miny, maxx, maxy = study.bbox_deg(lon, lat, 1000)
    assert minx < lon < maxx and miny < lat < maxy
    # 1000 m of latitude is ~0.009 deg everywhere
    assert (maxy - miny) / 2 == pytest.approx(1000 / 111_320.0)
    # longitude degrees are wider than latitude degrees off the equator
    assert (maxx - minx) > (maxy - miny)


# ---- validation ----
def test_defaults_are_valid():
    StudySpec().validate()

def test_bad_latitude_names_field_and_range():
    with pytest.raises(ValueError, match=r"lat 95.*\[-90, 90\]"):
        StudySpec(lat=95.0).validate()

def test_no_bands_rejected():
    with pytest.raises(ValueError, match="bands_ghz"):
        StudySpec(bands_ghz=()).validate()

def test_primary_must_be_in_bands():
    with pytest.raises(ValueError, match="primary_band_ghz"):
        StudySpec(bands_ghz=(1.8,), primary_band_ghz=3.5).validate()

def test_negative_half_width_rejected():
    with pytest.raises(ValueError, match="half_width_m"):
        StudySpec(half_width_m=-5).validate()

def test_local_layer_requires_path():
    spec = StudySpec()
    spec.layers["terrain"] = Layer(source="local", path="")
    with pytest.raises(ValueError, match="terrain"):
        spec.validate()

def test_crs_warning_for_web_mercator():
    assert StudySpec(epsg=3857).crs_warning() is not None
    assert StudySpec(epsg=32621).crs_warning() is None


# ---- serialization ----
def test_toml_round_trip(tmp_path):
    spec = StudySpec(
        name="test-site", lon=12.5, lat=-4.25, half_width_m=750.0, epsg=32733,
        bands_ghz=(3.5, 6.0), primary_band_ghz=3.5, mmwave_ghz=(28.0,),
        tx_power_dbm=30.0, bandwidth_hz=50e6, rx_height_m=2.0,
        layers={"buildings": Layer(source="local", path="/data/bldg.shp"),
                "terrain": Layer(source="copernicus-glo30")},
        outputs=("coverage", "sinr"),
    )
    path = study.save_study(spec, tmp_path / "study.toml")
    loaded = study.load_study(path)
    assert loaded == spec

def test_defaults_round_trip(tmp_path):
    spec = StudySpec()
    path = study.save_study(spec, tmp_path / "study.toml")
    assert study.load_study(path) == spec

def test_mini_parser_matches_tomllib():
    """The 3.10 fallback parser must agree with tomllib on what we emit."""
    tomllib = pytest.importorskip("tomllib")
    text = study.to_toml(StudySpec())
    assert study._mini_toml_loads(text) == tomllib.loads(text)

def test_load_rejects_invalid_file(tmp_path):
    bad = study.to_toml(StudySpec()).replace("lat = 13.088121", "lat = 95.0")
    p = tmp_path / "study.toml"
    p.write_text(bad)
    with pytest.raises(ValueError, match="lat"):
        study.load_study(p)
