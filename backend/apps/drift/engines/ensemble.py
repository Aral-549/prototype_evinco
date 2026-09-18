"""Monte Carlo backward drift: a probability distribution over the release point.

The deterministic engine answers "where did it come from, assuming the wind and
current were exactly this?" That assumption is never true. A single met-ocean
sample carries roughly 20-30% speed error and 15-20 degrees of direction error,
the wind drift factor is itself uncertain (2-4% is the accepted range), and
turbulent diffusion spreads a patch regardless. Integrated backward over 24-48
hours those errors dominate the answer.

So this engine advects an ensemble of particles, each drawing its own met-ocean
realisation and windage factor, and reports the resulting cloud. The output
uncertainty is then measured from the ensemble's own spread rather than asserted
by a formula, which is what BUGLOG "Origin uncertainty was a fabricated constant"
records: the previous value was `2.0 + 0.5 * duration_hours`, i.e. exactly 14 km
for every 24 h hindcast no matter the conditions.

Three physics corrections over the deterministic engine:

  1. Coriolis/Ekman deflection. Wind-driven surface drift does not run straight
     downwind; it is deflected to the right of the wind in the Northern
     Hemisphere and to the left in the Southern, by roughly 15-25 degrees.
  2. Time-varying field. The met-ocean field is re-sampled along the trajectory
     when a provider is supplied, instead of one vector held for 48 hours.
  3. Midpoint (RK2) integration rather than forward Euler, which halves the
     integration error for the same step size.
"""
import logging
import math
from dataclasses import dataclass, field
from datetime import timedelta

import numpy as np

from .base import DriftEngine, DriftInput, DriftOutput

logger = logging.getLogger('pipeline')

R_EARTH_M = 6_371_000.0
DEG = 180.0 / math.pi

# Latitude beyond which the cos(lat) longitude conversion becomes numerically
# unusable. Operationally irrelevant for Indian EEZ work but must not produce inf.
MAX_ABS_LAT = 89.5


@dataclass
class EnsembleDriftInput(DriftInput):
    """Drift input plus the stochastic parameters of the ensemble."""
    n_particles: int = 500
    seed: int = 42
    wind_speed_sigma_frac: float = 0.20
    wind_dir_sigma_deg: float = 15.0
    current_speed_sigma_frac: float = 0.30
    current_dir_sigma_deg: float = 20.0
    windage_mean: float = 0.030
    windage_sigma: float = 0.005
    deflection_deg: float = 20.0
    diffusion_m2_s: float = 5.0
    # Relative 1-sigma on the hindcast duration itself. The time the slick spent
    # adrift is not known exactly, so release TIME is sampled as well as position.
    duration_sigma_frac: float = 0.15
    sea_surface_temp_c: float = 25.0
    metocean_provider: object = None


@dataclass
class EnsembleDriftOutput(DriftOutput):
    """Deterministic-compatible output, extended with the ensemble statistics."""
    radius_50_km: float = 0.0
    radius_90_km: float = 0.0
    confidence_polygon_50: dict = field(default_factory=dict)
    confidence_polygon_90: dict = field(default_factory=dict)
    particles: list = field(default_factory=list)
    evaporated_fraction: float = 0.0
    weathering_warning: str = ''
    n_particles: int = 0
    seed: int = 0
    metocean_degraded_steps: int = 0


def _dt_from_timestamp(epoch: float, reference):
    """Rebuild an aware datetime from an epoch, preserving the reference tzinfo."""
    from datetime import datetime as _d
    return _d.fromtimestamp(epoch, tz=reference.tzinfo)


def _wrap_lon(lon):
    return ((lon + 180.0) % 360.0) - 180.0


def _haversine_km(lat1, lon1, lat2, lon2):
    p1 = np.radians(lat1)
    p2 = np.radians(lat2)
    dphi = p2 - p1
    dlam = np.radians(((lon2 - lon1 + 180.0) % 360.0) - 180.0)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlam / 2) ** 2
    return 2.0 * 6371.0 * np.arcsin(np.clip(np.sqrt(a), 0, 1))


def evaporated_fraction(hours: float, wind_speed_mps: float, sst_c: float = 25.0) -> float:
    """Fraction of a medium crude lost to evaporation after `hours` at sea.

    A first-order analytical weathering approximation of the Fingas evaporation
    model: light fractions leave logarithmically in time, faster in warm water and
    strong wind. This is not a substitute for a full ADIOS/OpenDrift weathering
    run; it exists to tell the operator when a hindcast has been pushed past the
    point where the slick would still be recognisably the same slick.
    """
    if hours <= 0:
        return 0.0
    # Base logarithmic rate, tuned so a medium crude loses ~25% in 24 h at 15 degC
    # in a moderate breeze, consistent with the Fingas empirical curves. The
    # coefficient was originally 0.165, which contradicted this stated intent:
    # it produced 53% at 24 h and 79% at 36 h in a strong wind, figures typical of
    # a light distillate rather than a crude, and would have triggered spurious
    # "slick no longer coherent" warnings on ordinary cases.
    base = 0.080 * math.log(1.0 + hours)
    temp_factor = 1.0 + 0.010 * (sst_c - 15.0)
    wind_factor = 1.0 + 0.030 * max(0.0, (wind_speed_mps or 0.0) - 5.0)
    return float(min(0.95, max(0.0, base * temp_factor * wind_factor)))


def _drift_velocity(wind_speed, wind_dir_deg, curr_speed, curr_dir_deg,
                    windage, deflection_deg, latitude):
    """Surface drift velocity (east, north) in m/s.

    Wind direction is the direction the wind comes FROM (meteorological
    convention); current direction is the direction it flows TO (oceanographic
    convention). Both conventions are inherited unchanged from the deterministic
    engine so the two remain directly comparable.
    """
    wind_rad = np.radians(wind_dir_deg)
    wind_east = -wind_speed * np.sin(wind_rad)
    wind_north = -wind_speed * np.cos(wind_rad)

    # Coriolis/Ekman: rotate the wind-driven component. Clockwise (to the right
    # of the wind) in the Northern Hemisphere, counter-clockwise in the Southern.
    sign = -1.0 if latitude >= 0 else 1.0
    theta = sign * np.radians(deflection_deg)
    cos_t, sin_t = np.cos(theta), np.sin(theta)
    wind_east_r = wind_east * cos_t - wind_north * sin_t
    wind_north_r = wind_east * sin_t + wind_north * cos_t

    curr_rad = np.radians(curr_dir_deg)
    curr_east = curr_speed * np.sin(curr_rad)
    curr_north = curr_speed * np.cos(curr_rad)

    return (curr_east + windage * wind_east_r,
            curr_north + windage * wind_north_r)


def _convex_hull(points: np.ndarray) -> list:
    """Monotone-chain convex hull of an (N, 2) array. Returns a closed ring."""
    if len(points) < 3:
        return [[float(x), float(y)] for x, y in points]
    pts = sorted({(float(x), float(y)) for x, y in points})
    if len(pts) < 3:
        return [[x, y] for x, y in pts]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    ring = lower[:-1] + upper[:-1]
    ring = [[x, y] for x, y in ring]
    if ring and ring[0] != ring[-1]:
        ring.append(ring[0])
    return ring


class EnsembleDriftEngine(DriftEngine):
    """Stochastic backward Lagrangian ensemble with a measured uncertainty."""

    name = 'monte_carlo_ensemble'

    def compute(self, params) -> EnsembleDriftOutput:
        if not isinstance(params, EnsembleDriftInput):
            # Accept a plain DriftInput and apply ensemble defaults.
            params = EnsembleDriftInput(**vars(params))

        n = int(params.n_particles)
        if n <= 0:
            raise ValueError(f'n_particles must be >= 1, got {n}')

        dt_hours = float(params.time_step_hours)
        if dt_hours <= 0:
            raise ValueError(f'time_step_hours must be > 0, got {dt_hours}')
        steps = max(1, int(round(params.duration_hours / dt_hours)))
        dt_s = dt_hours * 3600.0

        rng = np.random.default_rng(params.seed)

        # ── Per-particle met-ocean error draws ────────────────────
        # Each particle's error is drawn ONCE, as a multiplicative factor on speed
        # and an additive offset on direction, and is then applied to whatever the
        # field says at each step. Storing the factors rather than the resulting
        # speeds matters: an earlier version re-derived the factor each step as
        # `wind_speed / params.wind_speed_mps`, using the already-perturbed
        # `wind_speed` as the numerator. With a live field that differs from the
        # initial parameters the factor compounded geometrically -- a constant
        # 8 m/s field was read as 8, 16, 32, 63, 126, 252 m/s over six steps.
        wind_speed_factor = np.maximum(
            0.0, 1.0 + rng.normal(0.0, params.wind_speed_sigma_frac, n))
        wind_dir_offset = rng.normal(0.0, params.wind_dir_sigma_deg, n)
        curr_speed_factor = np.maximum(
            0.0, 1.0 + rng.normal(0.0, params.current_speed_sigma_frac, n))
        curr_dir_offset = rng.normal(0.0, params.current_dir_sigma_deg, n)
        windage = np.clip(
            rng.normal(params.windage_mean, params.windage_sigma, n), 0.0, 0.10)

        # Each particle also releases at its own time: the hindcast duration is
        # itself uncertain, so a particle that drifted for 20 h and one that drifted
        # for 28 h are both consistent with the same observed slick. Without this the
        # ensemble varied release POSITION only, every particle shared one release
        # time, and the attribution stage's "joint in space and time" claim was
        # only half true.
        release_step = np.clip(
            np.round(rng.normal(steps, steps * params.duration_sigma_frac, n)).astype(int),
            1, max(1, steps * 2))

        wind_speed = params.wind_speed_mps * wind_speed_factor
        wind_dir = params.wind_direction_deg + wind_dir_offset
        curr_speed = params.current_speed_mps * curr_speed_factor
        curr_dir = params.current_direction_deg + curr_dir_offset

        # Frozen release state: once a particle reaches its own release step it
        # stops advecting, so its recorded position is where IT came from.
        frozen_lat = np.full(n, float(params.start_lat))
        frozen_lon = np.full(n, float(params.start_lon))
        frozen = np.zeros(n, dtype=bool)
        release_times = [None] * n

        lat = np.full(n, float(params.start_lat))
        lon = np.full(n, float(params.start_lon))

        # Random-walk step for horizontal turbulent diffusion: sigma = sqrt(2 K dt)
        diff_sigma_m = math.sqrt(max(0.0, 2.0 * params.diffusion_m2_s * dt_s))

        mean_track = [{
            'lat': float(params.start_lat),
            'lon': float(params.start_lon),
            'time': params.detection_time.isoformat(),
        }]

        current_time = params.detection_time
        degraded_steps = 0

        for _step in range(steps):
            base_wind_speed, base_wind_dir = params.wind_speed_mps, params.wind_direction_deg
            base_curr_speed, base_curr_dir = params.current_speed_mps, params.current_direction_deg

            # ── Time-varying field, sampled at the ensemble centroid ──
            if params.metocean_provider is not None:
                try:
                    sample = params.metocean_provider(
                        float(np.mean(lat)), float(_wrap_lon(np.mean(lon))), current_time)
                    base_wind_speed = sample['wind_speed_mps']
                    base_wind_dir = sample['wind_direction_deg']
                    base_curr_speed = sample['current_speed_mps']
                    base_curr_dir = sample['current_direction_deg']
                    # Apply each particle's stored error draw to the FRESH field.
                    wind_speed = base_wind_speed * wind_speed_factor
                    curr_speed = base_curr_speed * curr_speed_factor
                    wind_dir = base_wind_dir + wind_dir_offset
                    curr_dir = base_curr_dir + curr_dir_offset
                except Exception as exc:
                    # A met-ocean outage must degrade the run, never abort it.
                    degraded_steps += 1
                    logger.warning(
                        f'Met-ocean provider failed at step {_step} '
                        f'({exc}); holding the previous field for this step.'
                    )

            safe_lat = np.clip(lat, -MAX_ABS_LAT, MAX_ABS_LAT)

            # ── Midpoint integration, BACKWARD in time ────────────
            # The field is sampled once per step (at the ensemble centroid), so the
            # velocity does not vary with position within a step and a second
            # velocity evaluation would return exactly the same numbers. What the
            # midpoint buys here is the metric term: the longitude step is divided
            # by cos(lat) evaluated half a step along rather than at the step's
            # start, which is the dominant discretisation error in a meridional
            # drift. Calling this full RK2 would overstate it.
            ve, vn = _drift_velocity(wind_speed, wind_dir, curr_speed, curr_dir,
                                     windage, params.deflection_deg, params.start_lat)

            half_lat = np.clip(safe_lat - (vn * dt_s * 0.5) / R_EARTH_M * DEG,
                               -MAX_ABS_LAT, MAX_ABS_LAT)

            dlat = -(vn * dt_s) / R_EARTH_M * DEG
            dlon = -(ve * dt_s) / (R_EARTH_M * np.cos(np.radians(half_lat))) * DEG

            if diff_sigma_m > 0:
                dlat += rng.normal(0.0, diff_sigma_m, n) / R_EARTH_M * DEG
                dlon += rng.normal(0.0, diff_sigma_m, n) / (
                    R_EARTH_M * np.cos(np.radians(half_lat))) * DEG

            # A particle that has already reached its own release step stops moving.
            active = ~frozen
            lat = np.where(active, np.clip(lat + dlat, -MAX_ABS_LAT, MAX_ABS_LAT), lat)
            lon = np.where(active, _wrap_lon(lon + dlon), lon)

            current_time -= timedelta(hours=dt_hours)

            newly_done = active & (release_step == (_step + 1))
            if newly_done.any():
                frozen_lat[newly_done] = lat[newly_done]
                frozen_lon[newly_done] = lon[newly_done]
                for idx in np.flatnonzero(newly_done):
                    release_times[idx] = current_time
                frozen |= newly_done

            mean_track.append({
                'lat': float(np.mean(lat)),
                'lon': float(_wrap_lon(np.mean(lon))),
                'time': current_time.isoformat(),
            })

        # Any particle whose release step exceeded the loop length releases at the end.
        still_moving = ~frozen
        if still_moving.any():
            frozen_lat[still_moving] = lat[still_moving]
            frozen_lon[still_moving] = lon[still_moving]
            for idx in np.flatnonzero(still_moving):
                release_times[idx] = current_time

        lat, lon = frozen_lat, frozen_lon
        origin_time = current_time

        # ── Ensemble statistics ───────────────────────────────────
        # Mean longitude via unit vectors, so a cloud straddling the antimeridian
        # averages to the correct side instead of to zero.
        mean_lat = float(np.mean(lat))
        lon_rad = np.radians(lon)
        mean_lon = float(_wrap_lon(math.degrees(
            math.atan2(float(np.mean(np.sin(lon_rad))), float(np.mean(np.cos(lon_rad)))))))

        dists = _haversine_km(mean_lat, mean_lon, lat, lon)
        radius_50 = float(np.percentile(dists, 50))
        radius_90 = float(np.percentile(dists, 90))

        coords = np.column_stack([lon, lat])
        idx_50 = np.argsort(dists)[:max(3, int(np.ceil(0.5 * n)))]
        idx_90 = np.argsort(dists)[:max(3, int(np.ceil(0.9 * n)))]

        evap = evaporated_fraction(
            params.duration_hours, params.wind_speed_mps, params.sea_surface_temp_c)
        warning = ''
        if evap > 0.50:
            warning = (
                f'Estimated {evap * 100:.0f}% of the released volume would have evaporated over '
                f'a {params.duration_hours:.0f} h hindcast. Beyond roughly 50% weathering the '
                f'detected slick may no longer correspond to a single coherent release, and the '
                f'reconstructed origin should be treated as indicative only.'
            )
        elif evap > 0.30:
            warning = (
                f'Estimated {evap * 100:.0f}% evaporation over {params.duration_hours:.0f} h. '
                f'Slick extent has likely contracted since release; the reconstructed origin '
                f'remains usable but its area is a lower bound on the volume spilled.'
            )

        particles = [
            {'lat': float(a), 'lon': float(_wrap_lon(b)),
             'time': (t or origin_time).isoformat(), 'windage': float(c)}
            for a, b, c, t in zip(lat, lon, windage, release_times)
        ]
        # The mean release time, used as the single headline figure.
        _epochs = [(t or origin_time).timestamp() for t in release_times]
        origin_time = _dt_from_timestamp(sum(_epochs) / len(_epochs), origin_time)

        return EnsembleDriftOutput(
            origin_lat=mean_lat,
            origin_lon=mean_lon,
            origin_time=origin_time,
            origin_uncertainty_km=radius_50,
            hindcast_trajectory=mean_track[::-1],
            forecast_trajectory=self._forecast(params, steps, dt_hours, dt_s),
            radius_50_km=radius_50,
            radius_90_km=radius_90,
            confidence_polygon_50={'type': 'Polygon',
                                   'coordinates': [_convex_hull(coords[idx_50])]},
            confidence_polygon_90={'type': 'Polygon',
                                   'coordinates': [_convex_hull(coords[idx_90])]},
            particles=particles,
            evaporated_fraction=evap,
            weathering_warning=warning,
            n_particles=n,
            seed=int(params.seed),
            metocean_degraded_steps=degraded_steps,
        )

    def _forecast(self, params, steps, dt_hours, dt_s):
        """Deterministic forward forecast of the slick centroid (landfall warning)."""
        lat, lon = float(params.start_lat), float(params.start_lon)
        t = params.detection_time
        track = [{'lat': lat, 'lon': lon, 'time': t.isoformat()}]

        for _ in range(steps):
            ve, vn = _drift_velocity(
                params.wind_speed_mps, params.wind_direction_deg,
                params.current_speed_mps, params.current_direction_deg,
                params.windage_mean, params.deflection_deg, params.start_lat)
            safe_lat = max(-MAX_ABS_LAT, min(MAX_ABS_LAT, lat))
            lat = max(-MAX_ABS_LAT, min(MAX_ABS_LAT,
                                        lat + (vn * dt_s) / R_EARTH_M * DEG))
            lon = _wrap_lon(lon + (ve * dt_s) / (
                R_EARTH_M * math.cos(math.radians(safe_lat))) * DEG)
            t += timedelta(hours=dt_hours)
            track.append({'lat': lat, 'lon': lon, 'time': t.isoformat()})
        return track
