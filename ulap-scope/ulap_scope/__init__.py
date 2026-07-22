"""
Ulap Scope -- Barbados / Newton digital-twin RF pipeline
(BlenderGIS -> Mitsuba -> Sionna RT) for the Ulap One project.

Import stays light on purpose: `geo` and `config` are pure and always available;
heavy stages (Blender/Sionna/GDAL) are run out-of-process via `pipeline`.
"""
__version__ = "0.1.0"

from . import geo, config          # noqa: F401
from .config import Config, load_config   # noqa: F401

__all__ = ["geo", "config", "Config", "load_config", "__version__"]
