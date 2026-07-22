"""
ulap_scope.study -- portable study definition for reusable digital twins.

A *study* is everything the pipeline needs to twin a new location:
where (centre + bounding box), in which projection (metric, please),
which signals to ray-trace, and which geospatial layers to use --
with open-data fallbacks for anything the user doesn't have.

Written/read as a versioned ``study.toml`` (tomllib on 3.11+, bundled
mini-parser for the subset we emit on 3.10). Pure stdlib; fully unit-tested.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# catalogs (recommendations distilled from the Barbados pilot study)
# ---------------------------------------------------------------------------

#: band GHz -> (label, note). 3.5 GHz is the recommended primary band.
BAND_CATALOG: dict[float, tuple[str, str]] = {
    1.8:  ("low-band",      "coverage fill / rural reach (~6 dB more margin than 3.5)"),
    3.5:  ("mid-band",      "recommended primary -- coverage/capacity sweet spot"),
    6.0:  ("upper mid",     "capacity near towers; pays the free-space lambda^2 penalty"),
    10.0: ("upper mid",     "capacity near towers; pays the free-space lambda^2 penalty"),
    28.0: ("mmWave",        "LoS-only -- fixed-wireless / hotspots, never area coverage"),
    60.0: ("mmWave",        "LoS-only + ~15 dB/km oxygen absorption"),
}
RECOMMENDED_BANDS = (1.8, 3.5, 6.0, 10.0)
RECOMMENDED_PRIMARY = 3.5

#: layer -> (recommended open source, human description of the fallback)
LAYER_FALLBACKS: dict[str, tuple[str, str]] = {
    "buildings": ("osm-overpass",       "OpenStreetMap footprints via Overpass API"),
    "terrain":   ("copernicus-glo30",   "Copernicus GLO-30 DEM (30 m, global, free)"),
    "basemap":   ("esri-world-imagery", "ESRI World Imagery satellite tiles"),
    "landcover": ("esa-worldcover",     "ESA WorldCover 10 m (for foliage modelling)"),
    "towers":    ("template-two-tower", "editable two-tower template (30 m + 24 m)"),
}

OUTPUT_PRODUCTS = ("coverage", "sinr", "sweep", "mmwave", "link-metrics", "animate")

#: EPSG codes that are *not* in true metres -- link budgets inherit the error.
NON_METRIC_EPSG = {3857: "Web Mercator stretches distances (~2.6% at 13 deg N)",
                   4326: "WGS84 degrees are not metres"}


# ---------------------------------------------------------------------------
# geodesy helpers
# ---------------------------------------------------------------------------

def utm_zone(lon: float, lat: float) -> tuple[int, str]:
    """Standard UTM zone number + hemisphere for a lon/lat."""
    zone = int((lon + 180.0) // 6.0) + 1
    zone = min(max(zone, 1), 60)
    return zone, ("N" if lat >= 0 else "S")


def utm_epsg(lon: float, lat: float) -> int:
    """Recommended metric CRS: EPSG code of the UTM zone containing lon/lat."""
    zone, hemi = utm_zone(lon, lat)
    return (32600 if hemi == "N" else 32700) + zone


def bbox_deg(lon: float, lat: float, half_width_m: float) -> tuple[float, float, float, float]:
    """Approximate geographic bounding box (min_lon, min_lat, max_lon, max_lat)
    of a square of +/- half_width_m around the centre (spherical earth)."""
    dlat = half_width_m / 111_320.0
    dlon = half_width_m / (111_320.0 * max(math.cos(math.radians(lat)), 1e-9))
    return (lon - dlon, lat - dlat, lon + dlon, lat + dlat)


# ---------------------------------------------------------------------------
# the study spec
# ---------------------------------------------------------------------------

@dataclass
class Layer:
    source: str            # "local" or a key from LAYER_FALLBACKS / "none"
    path: str = ""         # local file path when source == "local"


def _default_layers() -> dict[str, Layer]:
    return {name: Layer(source=src) for name, (src, _) in LAYER_FALLBACKS.items()}


@dataclass
class StudySpec:
    """Everything needed to reproduce a propagation study somewhere new.
    Defaults reproduce the Newton, Barbados pilot."""
    name: str = "newton-bbd"
    lon: float = -59.533908
    lat: float = 13.088121
    half_width_m: float = 1000.0
    epsg: int = 32621                    # UTM 21N -- metric, computed from lon/lat
    bands_ghz: tuple[float, ...] = RECOMMENDED_BANDS
    primary_band_ghz: float = RECOMMENDED_PRIMARY
    mmwave_ghz: tuple[float, ...] = ()
    tx_power_dbm: float = 33.0
    bandwidth_hz: float = 100e6
    rx_height_m: float = 1.5             # ground-following UE height (planning ref)
    layers: dict[str, Layer] = field(default_factory=_default_layers)
    outputs: tuple[str, ...] = OUTPUT_PRODUCTS
    schema_version: int = SCHEMA_VERSION

    # -- validation ---------------------------------------------------------
    def validate(self) -> "StudySpec":
        def err(msg):  # keep messages field-named and range-explicit
            raise ValueError(f"study spec invalid: {msg}")
        if not self.name or not re.fullmatch(r"[A-Za-z0-9._-]+", self.name):
            err(f"name {self.name!r} must be a non-empty slug [A-Za-z0-9._-]")
        if not -180.0 <= self.lon <= 180.0:
            err(f"lon {self.lon} out of range [-180, 180]")
        if not -90.0 <= self.lat <= 90.0:
            err(f"lat {self.lat} out of range [-90, 90]")
        if self.half_width_m <= 0:
            err(f"half_width_m {self.half_width_m} must be > 0")
        if self.epsg <= 0:
            err(f"epsg {self.epsg} must be a positive EPSG code")
        if not self.bands_ghz:
            err("bands_ghz must contain at least one band")
        if self.primary_band_ghz not in self.bands_ghz:
            err(f"primary_band_ghz {self.primary_band_ghz} not in bands_ghz {self.bands_ghz}")
        if self.rx_height_m <= 0:
            err(f"rx_height_m {self.rx_height_m} must be > 0")
        for prod in self.outputs:
            if prod not in OUTPUT_PRODUCTS:
                err(f"unknown output {prod!r} (valid: {OUTPUT_PRODUCTS})")
        for lname, layer in self.layers.items():
            if lname not in LAYER_FALLBACKS:
                err(f"unknown layer {lname!r} (valid: {tuple(LAYER_FALLBACKS)})")
            if layer.source == "local" and not layer.path:
                err(f"layer {lname!r} is 'local' but has no path")
        return self

    # -- derived ------------------------------------------------------------
    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return bbox_deg(self.lon, self.lat, self.half_width_m)

    @property
    def recommended_epsg(self) -> int:
        return utm_epsg(self.lon, self.lat)

    def crs_warning(self) -> str | None:
        return NON_METRIC_EPSG.get(self.epsg)


# ---------------------------------------------------------------------------
# TOML serialization (we emit a small, flat subset -- see parser below)
# ---------------------------------------------------------------------------

def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    raise TypeError(f"cannot serialize {type(v)}")


def to_toml(spec: StudySpec) -> str:
    b = spec.bbox
    lines = [
        "# study.toml -- generated by `ulap-scope init` ((o))~ <3 ~[laptop]",
        f"schema_version = {spec.schema_version}",
        f"name = {_toml_value(spec.name)}",
        "",
        "[area]",
        f"lon = {spec.lon!r}",
        f"lat = {spec.lat!r}",
        f"half_width_m = {spec.half_width_m!r}",
        f"bbox = {_toml_value([round(x, 6) for x in b])}  # derived: min_lon min_lat max_lon max_lat",
        "",
        "[projection]",
        f"epsg = {spec.epsg}",
        f"recommended_epsg = {spec.recommended_epsg}  # UTM zone computed from lon/lat",
        "",
        "[signals]",
        f"bands_ghz = {_toml_value(list(spec.bands_ghz))}",
        f"primary_band_ghz = {spec.primary_band_ghz!r}",
        f"mmwave_ghz = {_toml_value(list(spec.mmwave_ghz))}",
        f"tx_power_dbm = {spec.tx_power_dbm!r}",
        f"bandwidth_hz = {spec.bandwidth_hz!r}",
        f"rx_height_m = {spec.rx_height_m!r}",
        "",
        "[outputs]",
        f"products = {_toml_value(list(spec.outputs))}",
    ]
    for lname, layer in spec.layers.items():
        lines += ["", f"[layers.{lname}]", f"source = {_toml_value(layer.source)}"]
        if layer.path:
            lines.append(f"path = {_toml_value(layer.path)}")
    return "\n".join(lines) + "\n"


# -- parsing ----------------------------------------------------------------

def _parse_scalar(tok: str):
    tok = tok.strip()
    if tok.startswith('"'):
        m = re.match(r'"((?:[^"\\]|\\.)*)"', tok)
        if not m:
            raise ValueError(f"bad string: {tok}")
        return m.group(1).replace('\\"', '"').replace("\\\\", "\\")
    if tok in ("true", "false"):
        return tok == "true"
    return float(tok) if any(c in tok for c in ".eE") else int(tok)


def _mini_toml_loads(text: str) -> dict:
    """Parser for the flat subset of TOML that `to_toml` emits (3.10 fallback)."""
    root: dict = {}
    table = root
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            keys = line[1:line.index("]")].split(".")
            table = root
            for k in keys:
                table = table.setdefault(k, {})
            continue
        key, _, rest = line.partition("=")
        rest = rest.strip()
        # strip trailing comments (safe: emitted strings never contain '#')
        if rest.startswith("["):
            inner = rest[1:rest.index("]")]
            val = [_parse_scalar(t) for t in inner.split(",") if t.strip()]
        else:
            val = _parse_scalar(rest.split("#")[0] if not rest.startswith('"') else rest)
        table[key.strip()] = val
    return root


def toml_loads(text: str) -> dict:
    try:
        import tomllib
        return tomllib.loads(text)
    except ImportError:                      # Python 3.10
        return _mini_toml_loads(text)


def from_dict(d: dict) -> StudySpec:
    layers = {name: Layer(source=ld.get("source", "none"), path=ld.get("path", ""))
              for name, ld in d.get("layers", {}).items()}
    area, proj, sig = d.get("area", {}), d.get("projection", {}), d.get("signals", {})
    spec = StudySpec(
        name=d.get("name", "unnamed"),
        lon=float(area.get("lon", 0.0)),
        lat=float(area.get("lat", 0.0)),
        half_width_m=float(area.get("half_width_m", 1000.0)),
        epsg=int(proj.get("epsg", 0)),
        bands_ghz=tuple(float(b) for b in sig.get("bands_ghz", [])),
        primary_band_ghz=float(sig.get("primary_band_ghz", 0.0)),
        mmwave_ghz=tuple(float(b) for b in sig.get("mmwave_ghz", [])),
        tx_power_dbm=float(sig.get("tx_power_dbm", 33.0)),
        bandwidth_hz=float(sig.get("bandwidth_hz", 100e6)),
        rx_height_m=float(sig.get("rx_height_m", 1.5)),
        layers=layers or _default_layers(),
        outputs=tuple(d.get("outputs", {}).get("products", OUTPUT_PRODUCTS)),
        schema_version=int(d.get("schema_version", SCHEMA_VERSION)),
    )
    return spec.validate()


def save_study(spec: StudySpec, path: Path) -> Path:
    spec.validate()
    path = Path(path)
    path.write_text(to_toml(spec), encoding="utf-8")
    return path


def load_study(path: Path) -> StudySpec:
    return from_dict(toml_loads(Path(path).read_text(encoding="utf-8")))
