"""
ulap_scope.wizard -- `ulap-scope init`: interactive study definition.

Walks the user through location, bounding box, projection, signals and
geospatial layers, recommending open data (marked with a heart) wherever a
layer is missing, and writes a versioned ``study.toml``.

Testable by construction: prompts go through an injectable ``ask`` function
and all output through a stream, so the whole flow runs scripted in pytest.
"""
from __future__ import annotations

import sys
from pathlib import Path

from .study import (BAND_CATALOG, LAYER_FALLBACKS, NON_METRIC_EPSG, OUTPUT_PRODUCTS,
                    RECOMMENDED_BANDS, RECOMMENDED_PRIMARY, Layer, StudySpec,
                    bbox_deg, save_study, utm_epsg, utm_zone)

# ---------------------------------------------------------------------------
# banner -- cell towers in love with a laptop
# ---------------------------------------------------------------------------

BANNER = r"""
      ((HH))                                             ((HH))
       /|\        ~ HH ~   .  .  .   ~ HH ~               /|\
      / | \    HH      ~  .  ulap  .  ~      HH          / | \
     /  |  \          .   digital twin  .               /  |  \
    /___|___\        _____________________            /___|___\
      tower A       | .-----------------. |             tower B
                    | |  6G study  HH   | |
                    | '-----------------' |
                    '---------------------'
                     /:::::::::::::::::::\
                    '---------------------'
"""

WELCOME = "Ulap Study Wizard -- twin a place, trace its signals HH"


def _hearts(text: str, stream) -> str:
    """Use real hearts when the terminal can render them, ASCII otherwise.
    Both replacements are two columns wide so the ASCII art stays aligned."""
    heart = "♥ "
    try:
        heart.encode(getattr(stream, "encoding", None) or "utf-8")
    except (UnicodeEncodeError, LookupError):
        heart = "<3"
    return text.replace("HH", heart)


# ---------------------------------------------------------------------------
# prompt helpers (injectable for tests)
# ---------------------------------------------------------------------------

def _make_ask(input_fn, out):
    def ask(label: str, default: str) -> str:
        out.write(f"  {label} [{default}]: ")
        out.flush()
        try:
            answer = input_fn().strip()
        except EOFError:
            answer = ""
        return answer or default
    return ask


def _ask_float(ask, label, default, lo=None, hi=None):
    while True:
        raw = ask(label, str(default))
        try:
            v = float(raw)
        except ValueError:
            continue
        if (lo is None or v >= lo) and (hi is None or v <= hi):
            return v


# ---------------------------------------------------------------------------
# the flow
# ---------------------------------------------------------------------------

def run_wizard(out=None, input_fn=None, defaults: bool = False,
               output_path: str | Path = "study.toml") -> Path:
    """Run the wizard; returns the path of the written study.toml."""
    out = out or sys.stdout
    input_fn = input_fn or input
    P = lambda s="": out.write(_hearts(s, out) + "\n")

    P(BANNER.rstrip("\n"))
    P()
    P(f"  {WELCOME}")
    P("  press Enter to accept any [default] -- HH marks our recommendation")
    P()

    spec = StudySpec()
    if defaults:
        P("  --defaults: writing the Newton, Barbados pilot study HH")
        path = save_study(spec, output_path)
        P(f"  wrote {path}")
        return path

    ask = _make_ask(input_fn, out)

    # -- identity & location -----------------------------------------------
    P("== Where is the study? ==")
    spec.name = ask("Study name", spec.name)
    spec.lon = _ask_float(ask, "Longitude of study centre", spec.lon, -180, 180)
    spec.lat = _ask_float(ask, "Latitude of study centre", spec.lat, -90, 90)

    # -- bounding box -------------------------------------------------------
    spec.half_width_m = _ask_float(ask, "Bounding-box half-width in metres", 1000, 1)
    b = bbox_deg(spec.lon, spec.lat, spec.half_width_m)
    P(f"  -> bbox: [{b[0]:.6f}, {b[1]:.6f}, {b[2]:.6f}, {b[3]:.6f}]"
      f"  ({2 * spec.half_width_m / 1000:g} km square)")
    P()

    # -- projection ---------------------------------------------------------
    P("== Projection ==")
    rec = utm_epsg(spec.lon, spec.lat)
    zone, hemi = utm_zone(spec.lon, spec.lat)
    P(f"  HH recommended: EPSG:{rec} (UTM zone {zone}{hemi}) -- true metres,")
    P("     so link budgets and delay spreads are not distorted")
    spec.epsg = int(_ask_float(ask, "EPSG code for the scene CRS", rec, 1))
    warning = NON_METRIC_EPSG.get(spec.epsg)
    if warning:
        P(f"  !! warning: EPSG:{spec.epsg} is not metric -- {warning}.")
        P(f"     Fine for browsing; rebuild in EPSG:{rec} before quoting numbers.")
    P()

    # -- signals ------------------------------------------------------------
    P("== Signals to model ==")
    for ghz, (label, note) in BAND_CATALOG.items():
        mark = "HH" if ghz == RECOMMENDED_PRIMARY else "  "
        P(f"  {mark} {ghz:>4g} GHz  {label:<9} {note}")
    raw = ask("Bands to ray-trace (GHz, comma-separated)",
              ",".join(f"{b:g}" for b in RECOMMENDED_BANDS))
    bands = tuple(sorted({float(t) for t in raw.split(",") if t.strip()}))
    spec.bands_ghz = tuple(b for b in bands if b < 24) or RECOMMENDED_BANDS
    spec.mmwave_ghz = tuple(b for b in bands if b >= 24)
    default_primary = (RECOMMENDED_PRIMARY if RECOMMENDED_PRIMARY in spec.bands_ghz
                       else spec.bands_ghz[0])
    spec.primary_band_ghz = _ask_float(ask, "Primary band (GHz)", default_primary)
    if spec.primary_band_ghz not in spec.bands_ghz:
        spec.bands_ghz = tuple(sorted(spec.bands_ghz + (spec.primary_band_ghz,)))
    spec.tx_power_dbm = _ask_float(ask, "TX power (dBm)", spec.tx_power_dbm)
    spec.bandwidth_hz = _ask_float(ask, "Bandwidth (MHz)", spec.bandwidth_hz / 1e6) * 1e6
    spec.rx_height_m = _ask_float(ask, "Receiver height AGL (m) -- 1.5 = handset",
                                  spec.rx_height_m, 0.1)
    P()

    # -- geospatial layers --------------------------------------------------
    P("== Geospatial layers ==")
    P("  give a local file path, or press Enter and we pull open data HH")
    spec.layers = {}
    for lname, (fallback, desc) in LAYER_FALLBACKS.items():
        path = ask(f"{lname} -- local path (Enter = {fallback})", "")
        if path:
            spec.layers[lname] = Layer(source="local", path=path)
        else:
            spec.layers[lname] = Layer(source=fallback)
            P(f"    HH will pull: {desc}")
    P()

    # -- outputs ------------------------------------------------------------
    P("== Outputs ==")
    raw = ask("Products to generate", ",".join(OUTPUT_PRODUCTS))
    products = tuple(t.strip() for t in raw.split(",")
                     if t.strip() in OUTPUT_PRODUCTS)
    spec.outputs = products or OUTPUT_PRODUCTS

    # -- write --------------------------------------------------------------
    path = save_study(spec, output_path)
    P()
    P(f"  wrote {path}  HH")
    P(f"  next: ulap-scope all   (clip -> preprocess -> basemap -> build -> RT)")
    P()
    P(_signoff())
    return path


def _signoff() -> str:
    return ("      ((HH))  ~ ~ ~ HH ~ ~ ~  [_____]\n"
            "       /|\\     happy tracing!  \\___/\n")
