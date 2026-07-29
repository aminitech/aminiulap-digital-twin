"""
ulap_demo -- dependency-light support code for the Ulap example notebooks & apps.

The real pipeline (``ulap-scope``) ray-traces scenes in Sionna RT across three
Python environments. That is the *product*; it is also a 20-minute install. This
package exists so the open-source community can explore the same scene, the same
study definition and the same radio questions in **numpy + matplotlib only**, in
seconds, on a laptop.

What is real here
    The scene: 576 LiDAR-height building footprints, the 70x70 terrain grid and
    the tower registry are the actual Newton / Rising Sun (Barbados) pilot data,
    exported by ``ulap-scope preprocess``. ``newton_link_metrics.csv`` is real
    Sionna RT output.

What is an approximation here
    The propagation engine in :mod:`ulap_demo.propagation` is an *analytical*
    model -- free-space + two-ray ground reflection + a dominant-obstacle
    knife-edge diffraction term. It is fast and it captures the first-order
    physics, but it is NOT the ray tracer: no multi-bounce specular chains, no
    material-specific reflection/transmission, no scattering, no delay spread.
    Numbers from these demos are for learning and for shaping intuition. The
    figures in ``docs/renders/`` are the ray-traced ground truth.

See ``examples/README.md`` for the tour.
"""
from __future__ import annotations

from pathlib import Path

__version__ = "0.1.0"

#: Directory holding the sample scene / tower / link-metric files.
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

#: Repository root (the checkout that contains ulap-scope/, blender/, docs/).
REPO_ROOT = Path(__file__).resolve().parents[2]

from .scene import Scene, load_link_metrics, load_scene  # noqa: E402
from .propagation import (  # noqa: E402
    Coverage,
    PropagationModel,
    fit_log_distance,
    fspl_db,
    knife_edge_loss_db,
    log_distance_db,
    noise_floor_dbm,
)

__all__ = [
    "DATA_DIR",
    "REPO_ROOT",
    "Scene",
    "load_scene",
    "load_link_metrics",
    "PropagationModel",
    "Coverage",
    "fspl_db",
    "log_distance_db",
    "fit_log_distance",
    "knife_edge_loss_db",
    "noise_floor_dbm",
]
