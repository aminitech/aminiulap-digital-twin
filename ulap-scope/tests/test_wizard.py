"""Scripted runs of the `ulap-scope init` wizard -- no TTY needed."""
import io

import pytest

from ulap_scope import study, wizard


def run(answers, tmp_path, **kw):
    """Drive the wizard with a scripted list of answers; '' = accept default."""
    out = io.StringIO()
    it = iter(answers)
    path = wizard.run_wizard(out=out, input_fn=lambda: next(it, ""),
                             output_path=tmp_path / "study.toml", **kw)
    return study.load_study(path), out.getvalue()


def test_defaults_flag_writes_pilot_study(tmp_path):
    out = io.StringIO()
    path = wizard.run_wizard(out=out, defaults=True,
                             output_path=tmp_path / "study.toml")
    spec = study.load_study(path)
    assert spec.name == "newton-bbd"
    assert spec.lon == pytest.approx(-59.533908)
    assert spec.epsg == 32621
    assert 3.5 in spec.bands_ghz


def test_enter_everywhere_accepts_all_defaults(tmp_path):
    spec, out = run([""] * 40, tmp_path)
    assert spec.name == "newton-bbd"
    assert spec.primary_band_ghz == 3.5
    # untouched layers fall back to the recommended open sources
    assert spec.layers["buildings"].source == "osm-overpass"
    assert spec.layers["terrain"].source == "copernicus-glo30"
    assert "recommended: EPSG:32621" in out


def test_banner_has_towers_and_hearts(tmp_path):
    _, out = run([""] * 40, tmp_path)
    assert "/|\\" in out                 # a tower
    assert "6G study" in out             # the laptop
    assert "♥" in out or "<3" in out  # hearts, always


def test_custom_study_web_mercator_warns(tmp_path):
    answers = ["accra-gh",       # name
               "-0.1870",        # lon
               "5.6037",         # lat
               "2000",           # half width
               "3857",           # EPSG -> should warn
               "3.5,28",         # bands (28 goes to mmwave)
               "", "", "", "",   # primary, tx power, bandwidth, rx height
               "/data/accra_buildings.shp",  # local footprints
               "", "", "", "",   # terrain/basemap/landcover/towers -> fallbacks
               "coverage,sinr"]  # outputs
    spec, out = run(answers, tmp_path)
    assert "warning: EPSG:3857" in out
    assert spec.epsg == 3857
    assert spec.bands_ghz == (3.5,)
    assert spec.mmwave_ghz == (28.0,)
    assert spec.layers["buildings"] == study.Layer(source="local",
                                                   path="/data/accra_buildings.shp")
    assert spec.outputs == ("coverage", "sinr")
    # the wizard computed the metric recommendation for Accra (zone 30N)
    assert "EPSG:32630" in out


def test_cli_init_defaults(tmp_path, monkeypatch, capsys):
    from ulap_scope import cli
    monkeypatch.chdir(tmp_path)
    assert cli.main(["init", "--defaults", "-o", "s.toml"]) == 0
    assert (tmp_path / "s.toml").exists()
    assert "wrote" in capsys.readouterr().out
