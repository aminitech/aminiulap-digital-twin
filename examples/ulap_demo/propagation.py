"""
ulap_demo.propagation -- a small, honest, analytical radio model.

This is deliberately *not* a ray tracer. It is the classic teaching stack:

    free-space loss           20 log10(4 pi d / lambda)
  + two-ray ground reflection coherent direct + ground-reflected ray, with a
                              Fresnel reflection coefficient and the standard
                              breakpoint smoothing
  + knife-edge diffraction    ITU-R P.526 J(nu) over the single dominant
                              obstacle on the terrain + building profile

That trio explains most of what a rural/suburban coverage map does, runs in a
second on a laptop, and is small enough to read in one sitting. What it cannot
do is exactly what you buy a ray tracer for: multi-bounce specular chains,
material-dependent reflection and transmission, diffuse scattering, and any
delay-domain quantity (delay spread, CIR taps, Doppler). When these demos and
``docs/renders/`` disagree, the ray tracer is right.

Sign convention: **path gain** is negative dB (a loss of 100 dB is a path gain
of -100 dB), matching Sionna's ``path_gain`` and the pilot's CSV outputs.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

C = 299_792_458.0                 # speed of light [m/s]
BOLTZMANN_DBM_HZ = -173.98        # 10*log10(k*T0*1000) at T0 = 290 K


# --------------------------------------------------------------- free space
def wavelength(freq_hz: float) -> float:
    return C / float(freq_hz)


def fspl_db(d_m, freq_hz: float):
    """Isotropic free-space path *loss* in dB. Distances below 1 m are clamped
    (the far-field formula is meaningless closer in)."""
    d = np.maximum(np.asarray(d_m, dtype=float), 1.0)
    return 20 * np.log10(4 * np.pi * d / wavelength(freq_hz))


def log_distance_db(d_m, pl_d0_db: float, n: float, d0: float = 1.0):
    """Log-distance path *loss*: ``PL(d0) + 10 n log10(d/d0)``."""
    d = np.maximum(np.asarray(d_m, dtype=float), d0)
    return pl_d0_db + 10.0 * n * np.log10(d / d0)


@dataclass
class LogDistanceFit:
    """Least-squares log-distance fit. ``n`` is the path-loss exponent (2 =
    free space, >2 = obstructed, <2 = constructive ground reflection)."""

    n: float
    pl_d0_db: float
    d0: float
    rms_db: float
    n_points: int

    def predict(self, d_m):
        """Predicted path *gain* (negative dB) at distance ``d_m``."""
        return -log_distance_db(d_m, self.pl_d0_db, self.n, self.d0)

    def __str__(self) -> str:
        return (f"path gain = -({self.pl_d0_db:.1f} + "
                f"{10 * self.n:.1f} log10(d/{self.d0:g} m))  "
                f"[n = {self.n:.2f}, RMS residual {self.rms_db:.2f} dB, "
                f"{self.n_points} points]")


def fit_log_distance(d_m, path_gain_db, d0: float = 1.0) -> LogDistanceFit:
    """Fit ``n`` and the reference loss to measured/ray-traced path gain."""
    d = np.asarray(d_m, dtype=float)
    pg = np.asarray(path_gain_db, dtype=float)
    ok = np.isfinite(d) & np.isfinite(pg) & (d > 0)
    d, pg = d[ok], pg[ok]
    loss = -pg
    x = 10.0 * np.log10(d / d0)
    slope, intercept = np.polyfit(x, loss, 1)
    resid = loss - (slope * x + intercept)
    return LogDistanceFit(n=float(slope), pl_d0_db=float(intercept), d0=float(d0),
                          rms_db=float(np.sqrt(np.mean(resid ** 2))), n_points=int(d.size))


# ------------------------------------------------------------- diffraction
def knife_edge_loss_db(nu):
    """ITU-R P.526 single knife-edge diffraction loss J(nu), in dB (>= 0).

    ``nu`` is the dimensionless Fresnel-Kirchhoff parameter: negative means the
    obstacle is below the ray with Fresnel clearance to spare (no loss),
    ``nu = 0`` is grazing (~6 dB), positive means blocked."""
    nu = np.asarray(nu, dtype=float)
    out = np.zeros_like(nu)
    m = nu > -0.78                    # below this, J(nu) is taken as 0 dB
    t = nu[m] - 0.1
    out[m] = 6.9 + 20 * np.log10(np.sqrt(t ** 2 + 1) + t)
    return np.maximum(out, 0.0)


def fresnel_radius_m(d1, d2, freq_hz: float):
    """Radius of the first Fresnel zone at a point d1 from one end, d2 from the
    other. Keep 60 % of this clear and the link behaves like free space."""
    d1 = np.asarray(d1, dtype=float)
    d2 = np.asarray(d2, dtype=float)
    d = np.maximum(d1 + d2, 1e-9)
    return np.sqrt(np.maximum(wavelength(freq_hz) * d1 * d2 / d, 0.0))


def fresnel_nu(clearance_m, d1, d2, freq_hz: float, min_distance_m: float = 1.0):
    """Fresnel-Kirchhoff nu for an obstacle standing ``clearance_m`` above the
    line of sight (negative = below the line).

    ``d1``/``d2`` are clamped to ``min_distance_m``: the knife-edge formula
    diverges as an obstacle approaches either endpoint, which would otherwise
    turn a building *under the receiver* into an infinite wall."""
    d1 = np.maximum(np.asarray(d1, dtype=float), min_distance_m)
    d2 = np.maximum(np.asarray(d2, dtype=float), min_distance_m)
    lam = wavelength(freq_hz)
    return np.asarray(clearance_m, dtype=float) * np.sqrt(2.0 / lam * (1.0 / d1 + 1.0 / d2))


# ---------------------------------------------------------- ground reflection
def ground_reflection_coeff(theta_rad, freq_hz: float,
                            eps_r: float = 15.0, sigma: float = 1e-3):
    """Fresnel reflection coefficient for **vertical** polarisation at grazing
    angle ``theta_rad`` over ground with relative permittivity ``eps_r`` and
    conductivity ``sigma`` [S/m]. Defaults approximate ITU medium-dry ground --
    the same material class the pilot scene uses. Tends to -1 at grazing."""
    lam = wavelength(freq_hz)
    eps_c = eps_r - 1j * 60.0 * lam * sigma
    s = np.sin(np.asarray(theta_rad, dtype=float))
    c = np.cos(np.asarray(theta_rad, dtype=float))
    root = np.sqrt(eps_c - c ** 2)
    return (eps_c * s - root) / (eps_c * s + root)


def two_ray_gain_db(d_m, h_t: float, h_r: float, freq_hz: float,
                    mode: str = "average", eps_r: float = 15.0, sigma: float = 1e-3):
    """Gain of the two-ray model *relative to free space*, in dB.

    ``mode``:
      ``"coherent"`` full interference fringes -- what a fine transect shows;
      ``"average"``  fringes below the breakpoint replaced by their local mean
                     power ``1 + |Gamma|^2``, which is what a coarse coverage
                     grid can resolve without aliasing. That approaches +3 dB at
                     grazing incidence, but dips toward 0 dB near the
                     pseudo-Brewster angle where a vertically-polarised
                     reflection nearly vanishes;
      ``"none"``     no ground reflection at all (pure free space).

    The breakpoint ``d_bp = 4 h_t h_r / lambda`` is where the direct and
    reflected rays fall within pi of each other; beyond it the two rays cancel
    progressively and the loss steepens toward the classic d^-4 asymptote."""
    if mode == "none":
        return np.zeros_like(np.asarray(d_m, dtype=float))
    d = np.maximum(np.asarray(d_m, dtype=float), 1e-6)
    lam = wavelength(freq_hz)

    d_direct = np.sqrt(d ** 2 + (h_t - h_r) ** 2)
    d_refl = np.sqrt(d ** 2 + (h_t + h_r) ** 2)
    dphi = 2 * np.pi * (d_refl - d_direct) / lam
    theta = np.arctan2(h_t + h_r, d)              # grazing angle of the bounce
    gamma = ground_reflection_coeff(theta, freq_hz, eps_r, sigma)

    # Spreading loss of the reflected ray is slightly larger; keep the ratio so
    # the model stays exact at short range instead of assuming d_refl ~ d.
    coherent = np.abs(1.0 + gamma * (d_direct / d_refl) * np.exp(-1j * dphi)) ** 2
    if mode == "coherent":
        return 10 * np.log10(np.maximum(coherent, 1e-12))
    if mode != "average":
        raise ValueError(f"mode must be coherent|average|none, got {mode!r}")

    # Below the breakpoint (|dphi| > pi) a real grid cannot resolve the fringe;
    # use the phase-averaged power 1 + |Gamma|^2 there.
    incoherent = 1.0 + np.abs(gamma) ** 2
    blended = np.where(np.abs(dphi) > np.pi, incoherent, coherent)
    return 10 * np.log10(np.maximum(blended, 1e-12))


# ------------------------------------------------------------------- noise
def noise_floor_dbm(bandwidth_hz: float, noise_figure_db: float = 7.0) -> float:
    """Thermal noise floor: kTB + NF, in dBm."""
    return BOLTZMANN_DBM_HZ + 10 * np.log10(float(bandwidth_hz)) + float(noise_figure_db)


# ------------------------------------------------------------------- model
@dataclass
class PropagationModel:
    """Link parameters + the switches that decide which physics is in play.

    Defaults match the pilot study: 3.5 GHz, 33 dBm (2 W) per site, 100 MHz,
    receivers at 1.5 m above ground (handset height -- the level planning
    decisions should be made at)."""

    freq_hz: float = 3.5e9
    tx_power_dbm: float = 33.0
    tx_gain_dbi: float = 8.0          # a modest sector panel
    rx_gain_dbi: float = 0.0          # isotropic handset
    bandwidth_hz: float = 100e6
    noise_figure_db: float = 7.0
    rx_height_m: float = 1.5
    use_terrain: bool = True
    use_buildings: bool = True
    ground_reflection: str = "average"       # coherent | average | none
    eps_r: float = 15.0
    sigma: float = 1e-3
    profile_samples: int = 48                 # obstacle samples per link
    raster_cell_m: float = 5.0                # building/terrain raster resolution
    min_distance_m: float = 5.0
    # A single knife edge can predict 60+ dB of loss deep in a terrain shadow. In
    # reality those pixels are rescued by reflections -- which this model does not
    # trace at all. Capping the diffraction term is the standard stand-in for that
    # missing multipath; without it, shadowed pixels are wildly pessimistic. Set
    # it to `float("inf")` to see the raw knife-edge prediction.
    max_diffraction_db: float = 40.0

    # -- derived -----------------------------------------------------------
    @property
    def wavelength_m(self) -> float:
        return wavelength(self.freq_hz)

    @property
    def noise_dbm(self) -> float:
        return noise_floor_dbm(self.bandwidth_hz, self.noise_figure_db)

    @property
    def eirp_dbm(self) -> float:
        return self.tx_power_dbm + self.tx_gain_dbi

    def describe(self) -> str:
        return (f"{self.freq_hz / 1e9:g} GHz (lambda = {self.wavelength_m * 100:.1f} cm), "
                f"EIRP {self.eirp_dbm:.0f} dBm, {self.bandwidth_hz / 1e6:g} MHz, "
                f"noise floor {self.noise_dbm:.1f} dBm, RX at {self.rx_height_m} m\n"
                f"terrain={'on' if self.use_terrain else 'off'}, "
                f"buildings={'on' if self.use_buildings else 'off'}, "
                f"ground reflection={self.ground_reflection}, "
                f"diffraction capped at {self.max_diffraction_db:g} dB")

    # -- the model ---------------------------------------------------------
    def path_gain_db(self, scene, tower, X, Y, return_parts: bool = False):
        """Path gain [dB] from ``tower`` to every point of the (X, Y) grid.

        With ``return_parts=True`` you also get the free-space, ground-reflection
        and diffraction terms separately -- useful for teaching which term is
        doing the work where."""
        X = np.asarray(X, dtype=float)
        Y = np.asarray(Y, dtype=float)
        raster = scene.height_raster(self.raster_cell_m)

        ground = raster.ground if self.use_terrain else np.zeros_like(raster.ground)
        obstacles = ground + (raster.building_height if self.use_buildings
                              else np.zeros_like(ground))
        surf = type(raster)(ground=ground, top=obstacles, minx=raster.minx,
                            miny=raster.miny, cell_m=raster.cell_m)

        tx_z = (tower.ground_z if self.use_terrain else 0.0) + tower.h
        rx_ground = surf.sample_ground(X, Y)
        rx_z = rx_ground + self.rx_height_m

        dx = X - tower.x
        dy = Y - tower.y
        d_horiz = np.maximum(np.hypot(dx, dy), self.min_distance_m)
        d_3d = np.hypot(d_horiz, rx_z - tx_z)

        loss_fs = fspl_db(d_3d, self.freq_hz)

        # --- dominant-obstacle knife edge over the terrain+building profile ---
        nu_max = np.full(X.shape, -np.inf)
        k = max(int(self.profile_samples), 1)
        for t in (np.arange(k) + 0.5) / k:              # interior samples only
            px = tower.x + t * dx
            py = tower.y + t * dy
            h_obs = surf.sample_top(px, py)
            h_ray = tx_z + t * (rx_z - tx_z)
            d1 = t * d_horiz
            d2 = (1.0 - t) * d_horiz
            nu = fresnel_nu(h_obs - h_ray, d1, d2, self.freq_hz)
            np.maximum(nu_max, nu, out=nu_max)
        loss_diff = np.minimum(knife_edge_loss_db(nu_max), self.max_diffraction_db)

        # --- ground reflection, only where the link is effectively clear ---
        gain_2ray = two_ray_gain_db(d_horiz, tx_z - rx_ground, self.rx_height_m,
                                    self.freq_hz, mode=self.ground_reflection,
                                    eps_r=self.eps_r, sigma=self.sigma)
        gain_2ray = np.where(nu_max < -0.78, gain_2ray, 0.0)

        pg = -loss_fs + gain_2ray - loss_diff
        if return_parts:
            return pg, {"fspl_db": loss_fs, "two_ray_db": gain_2ray,
                        "diffraction_db": loss_diff, "nu": nu_max,
                        "distance_m": d_horiz, "los": nu_max < -0.78}
        return pg

    def rx_power_dbm(self, scene, tower, X, Y):
        """Received power [dBm] = EIRP + RX gain + path gain."""
        return self.eirp_dbm + self.rx_gain_dbi + self.path_gain_db(scene, tower, X, Y)

    def radial(self, scene, tower, distances_m, bearing_xy=None, return_parts=False):
        """Path gain along a straight radial from ``tower``.

        ``bearing_xy`` is a direction vector; the default aims at the scene
        origin, reproducing the transect the pilot's ``analysis`` stage traces."""
        d = np.asarray(distances_m, dtype=float)
        if bearing_xy is None:
            vx, vy = -tower.x, -tower.y
        else:
            vx, vy = float(bearing_xy[0]), float(bearing_xy[1])
        norm = np.hypot(vx, vy) or 1.0
        ux, uy = vx / norm, vy / norm
        X = tower.x + ux * d
        Y = tower.y + uy * d
        return self.path_gain_db(scene, tower, X, Y, return_parts=return_parts)

    def coverage(self, scene, towers=None, cell_m: float = 10.0) -> "Coverage":
        """Multi-tower coverage: per-tower path gain, best server, RSRP, SINR."""
        towers = list(towers) if towers is not None else scene.towers_in_scene()
        if not towers:
            known = ", ".join(f"{t.name} at ({t.x:.0f}, {t.y:.0f})" for t in scene.towers)
            raise ValueError(
                "no towers to serve the scene. "
                + (f"The scene lists {len(scene.towers)} site(s) but none fall inside "
                   f"the study box: {known}. Pass towers=... explicitly, or rebuild the "
                   "scene with sites inside the box."
                   if scene.towers else
                   "The scene manifest has no 'antennas' entries at all."))
        X, Y, extent = scene.grid(cell_m)
        pg = np.stack([self.path_gain_db(scene, t, X, Y) for t in towers])
        rsrp = self.eirp_dbm + self.rx_gain_dbi + pg

        best = np.argmax(rsrp, axis=0)
        best_rsrp = np.max(rsrp, axis=0)

        lin = 10 ** (rsrp / 10.0)                    # mW
        total = lin.sum(axis=0)
        serving = np.max(lin, axis=0)
        interference = np.maximum(total - serving, 0.0)
        noise_mw = 10 ** (self.noise_dbm / 10.0)
        sinr = 10 * np.log10(serving / (interference + noise_mw))

        return Coverage(X=X, Y=Y, extent=extent, tower_names=[t.name for t in towers],
                        path_gain_db=pg, rsrp_dbm=rsrp, best_server=best,
                        best_rsrp_dbm=best_rsrp, sinr_db=sinr, cell_m=cell_m, model=self)


@dataclass
class Coverage:
    """Result of :meth:`PropagationModel.coverage` -- grids plus the stats you
    actually report to a planner."""

    X: np.ndarray
    Y: np.ndarray
    extent: list
    tower_names: list
    path_gain_db: np.ndarray      # (n_tx, ny, nx)
    rsrp_dbm: np.ndarray          # (n_tx, ny, nx)
    best_server: np.ndarray       # (ny, nx) index into tower_names
    best_rsrp_dbm: np.ndarray     # (ny, nx)
    sinr_db: np.ndarray           # (ny, nx)
    cell_m: float
    model: PropagationModel = field(repr=False, default=None)

    @property
    def cell_area_km2(self) -> float:
        return self.cell_m ** 2 / 1e6

    def fraction_above(self, rsrp_dbm: float) -> float:
        """Fraction of the study area with best-server RSRP above a threshold."""
        return float(np.mean(self.best_rsrp_dbm >= rsrp_dbm))

    def fraction_sinr_above(self, sinr_db: float) -> float:
        return float(np.mean(self.sinr_db >= sinr_db))

    def served_area_km2(self, rsrp_dbm: float) -> float:
        return float(np.sum(self.best_rsrp_dbm >= rsrp_dbm) * self.cell_area_km2)

    def server_share(self) -> dict[str, float]:
        """Fraction of the area each tower wins as best server."""
        return {name: float(np.mean(self.best_server == i))
                for i, name in enumerate(self.tower_names)}

    def summary(self, rsrp_threshold_dbm: float = -100.0,
                sinr_threshold_db: float = 0.0) -> str:
        pct = 100 * self.fraction_above(rsrp_threshold_dbm)
        spct = 100 * self.fraction_sinr_above(sinr_threshold_db)
        shares = ", ".join(f"{k} {100 * v:.0f}%" for k, v in self.server_share().items())
        return (
            f"grid {self.best_rsrp_dbm.shape[1]}x{self.best_rsrp_dbm.shape[0]} "
            f"@ {self.cell_m:g} m ({self.cell_area_km2 * self.best_rsrp_dbm.size:.2f} km2)\n"
            f"  best-server RSRP : median {np.median(self.best_rsrp_dbm):.1f} dBm, "
            f"5th pct {np.percentile(self.best_rsrp_dbm, 5):.1f} dBm\n"
            f"  coverage         : {pct:.1f}% of area >= {rsrp_threshold_dbm:g} dBm "
            f"({self.served_area_km2(rsrp_threshold_dbm):.2f} km2)\n"
            f"  SINR             : median {np.median(self.sinr_db):.1f} dB, "
            f"{spct:.1f}% >= {sinr_threshold_db:g} dB\n"
            f"  best-server share: {shares}")
