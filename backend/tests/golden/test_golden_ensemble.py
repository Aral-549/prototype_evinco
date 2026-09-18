"""Golden: Monte Carlo drift ensemble.

Covers `contracts/drift_ensemble.md` cases 1-8 and the BUGLOG entries
"Origin uncertainty was a fabricated constant", "Wind-driven drift applied with no
Coriolis/Ekman deflection", "Single met-ocean sample held constant", "Met-ocean
perturbations compounded geometrically", and "Drift ensemble varied release
position but not release time".
"""
from datetime import datetime, timezone

import numpy as np
import pytest

from apps.drift.engines.base import DriftInput
from apps.drift.engines.lagrangian import LagrangianDriftEngine
from apps.drift.engines.ensemble import (
    EnsembleDriftEngine, EnsembleDriftInput, evaporated_fraction,
)

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
BASE = dict(
    start_lat=19.0, start_lon=72.0, detection_time=T0,
    wind_speed_mps=6.0, wind_direction_deg=225.0,
    current_speed_mps=0.4, current_direction_deg=90.0,
    duration_hours=24.0, time_step_hours=1.0,
)
DETERMINISTIC = dict(
    n_particles=1, wind_speed_sigma_frac=0.0, wind_dir_sigma_deg=0.0,
    current_speed_sigma_frac=0.0, current_dir_sigma_deg=0.0,
    windage_sigma=0.0, diffusion_m2_s=0.0, duration_sigma_frac=0.0,
)


def test_case1_degenerate_ensemble_reduces_to_deterministic_engine():
    """Case 1: zero spread, zero diffusion, zero deflection == the legacy engine.

    Tolerance 1e-4 deg (~11 m), not 1e-6: the ensemble evaluates cos(lat) for the
    longitude step half a step along the trajectory while the legacy engine
    evaluates it at the step's start. That difference is the intended improvement,
    not error. Measured residual is 5.3e-6 deg over 24 h.
    """
    det = LagrangianDriftEngine().compute(DriftInput(**BASE))
    ens = EnsembleDriftEngine().compute(
        EnsembleDriftInput(**BASE, **DETERMINISTIC, deflection_deg=0.0))

    assert ens.origin_lat == pytest.approx(det.origin_lat, abs=1e-4)
    assert ens.origin_lon == pytest.approx(det.origin_lon, abs=1e-4)


def test_case2_identical_seed_gives_identical_output():
    """Case 2: court-grade reproducibility. Same inputs + seed => same everything."""
    a = EnsembleDriftEngine().compute(EnsembleDriftInput(**BASE, n_particles=300, seed=7))
    b = EnsembleDriftEngine().compute(EnsembleDriftInput(**BASE, n_particles=300, seed=7))

    assert a.origin_lat == b.origin_lat
    assert a.origin_lon == b.origin_lon
    assert a.radius_50_km == b.radius_50_km
    assert a.radius_90_km == b.radius_90_km
    assert a.particles == b.particles


def test_case3_different_seed_differs_by_less_than_the_90th_percentile():
    """Case 3: sampling noise must not dominate the answer."""
    from apps.detection.geodesy import haversine_km
    a = EnsembleDriftEngine().compute(EnsembleDriftInput(**BASE, n_particles=800, seed=1))
    b = EnsembleDriftEngine().compute(EnsembleDriftInput(**BASE, n_particles=800, seed=2))

    shift = haversine_km(a.origin_lat, a.origin_lon, b.origin_lat, b.origin_lon)
    assert a.origin_lat != b.origin_lat
    assert shift < a.radius_90_km


def test_case4_uncertainty_grows_with_hindcast_duration():
    """Case 4: the fabricated `2.0 + 0.5*h` is gone; spread is measured and monotonic."""
    e = EnsembleDriftEngine()
    radii = {
        h: e.compute(EnsembleDriftInput(
            **{**BASE, 'duration_hours': h}, n_particles=600, seed=3)).radius_50_km
        for h in (12.0, 24.0, 48.0)
    }
    assert radii[12.0] < radii[24.0] < radii[48.0]
    # And it must NOT equal the old placeholder formula.
    assert radii[24.0] != pytest.approx(2.0 + 0.5 * 24.0, abs=0.01)


def test_case5_estimator_converges_with_particle_count():
    """Case 5: radius_50 is stable between 1000 and 5000 particles (< 15% change)."""
    e = EnsembleDriftEngine()
    r1 = e.compute(EnsembleDriftInput(**BASE, n_particles=1000, seed=3)).radius_50_km
    r2 = e.compute(EnsembleDriftInput(**BASE, n_particles=5000, seed=3)).radius_50_km
    assert abs(r2 - r1) / r1 < 0.15


def test_case6_coriolis_deflects_to_opposite_hemispheres():
    """Case 6: wind-driven drift goes right of the wind in the N, left in the S.

    Wind FROM 180 deg blows toward the north, so forward drift is north-east in the
    Northern Hemisphere and the BACKWARD hindcast origin lies to the south-west
    (negative longitude offset). The Southern Hemisphere mirrors it.
    """
    e = EnsembleDriftEngine()
    cfg = dict(detection_time=T0, wind_speed_mps=10.0, wind_direction_deg=180.0,
               current_speed_mps=0.0, current_direction_deg=0.0,
               duration_hours=24.0, time_step_hours=1.0, **DETERMINISTIC)

    north = e.compute(EnsembleDriftInput(start_lat=19.0, start_lon=72.0, **cfg))
    south = e.compute(EnsembleDriftInput(start_lat=-19.0, start_lon=72.0, **cfg))
    none_ = e.compute(EnsembleDriftInput(start_lat=19.0, start_lon=72.0,
                                         **{**cfg, 'deflection_deg': 0.0}))

    assert none_.origin_lon == pytest.approx(72.0, abs=1e-9), 'no deflection => no E/W shift'
    assert north.origin_lon < 72.0, 'NH hindcast origin must lie west'
    assert south.origin_lon > 72.0, 'SH hindcast origin must lie east'
    # Mirrored in sign and close in magnitude, but NOT exactly equal: both
    # hindcasts travel south, so the northern one moves toward the equator (cos lat
    # rises, longitude step shrinks) while the southern one moves away from it. The
    # ~0.1% asymmetry is the longitude metric doing its job, not a defect.
    assert (north.origin_lon - 72.0) == pytest.approx(
        -(south.origin_lon - 72.0), rel=0.01)
    # Both hindcast south of the detection, since the wind blew the slick north.
    assert north.origin_lat < 19.0 and south.origin_lat < -19.0


def test_case7_weathering_warns_on_long_hindcasts():
    """Case 7: evaporation is monotonic in time, wind and temperature, and warns.

    Calibration anchor: a medium crude loses ~25% in 24 h at 15 C in a moderate
    breeze (Fingas empirical curves). A coefficient that produced 53% at 24 h was
    a bug, not a conservative choice.
    """
    assert evaporated_fraction(24.0, 5.0, 15.0) == pytest.approx(0.26, abs=0.03)
    assert evaporated_fraction(0.0, 5.0, 15.0) == 0.0
    assert evaporated_fraction(48.0, 5.0, 15.0) > evaporated_fraction(24.0, 5.0, 15.0)
    assert evaporated_fraction(24.0, 15.0, 15.0) > evaporated_fraction(24.0, 5.0, 15.0)
    assert evaporated_fraction(24.0, 5.0, 30.0) > evaporated_fraction(24.0, 5.0, 15.0)
    assert evaporated_fraction(1000.0, 30.0, 40.0) <= 0.95

    out = EnsembleDriftEngine().compute(EnsembleDriftInput(
        **{**BASE, 'wind_speed_mps': 12.0, 'duration_hours': 36.0},
        n_particles=200, seed=1))
    assert out.evaporated_fraction > 0.30
    assert out.weathering_warning != ''


def test_case8_zero_particles_is_an_error():
    """Case 8: never return an empty ensemble silently."""
    with pytest.raises(ValueError):
        EnsembleDriftEngine().compute(EnsembleDriftInput(**BASE, n_particles=0))
    zero_step = {**BASE, 'time_step_hours': 0.0}
    with pytest.raises(ValueError):
        EnsembleDriftEngine().compute(
            EnsembleDriftInput(**zero_step, n_particles=10))


def test_case9_metocean_perturbations_do_not_compound(monkeypatch):
    """Case 9 (BUGLOG: perturbations compounded geometrically).

    A provider returning a CONSTANT field must be read as that constant at every
    step. The regression doubled it each step: 8, 16, 32, 63, 126, 252 m/s.
    """
    import apps.drift.engines.ensemble as ens

    observed = []
    original = ens._drift_velocity

    def spy(ws, wd, cs, cd, windage, deflection, lat):
        observed.append(float(np.mean(ws)))
        return original(ws, wd, cs, cd, windage, deflection, lat)

    monkeypatch.setattr(ens, '_drift_velocity', spy)

    def provider(lat, lon, when):
        return {'wind_speed_mps': 8.0, 'wind_direction_deg': 225.0,
                'current_speed_mps': 0.4, 'current_direction_deg': 90.0,
                'source': 'stub'}

    EnsembleDriftEngine().compute(EnsembleDriftInput(
        **{**BASE, 'wind_speed_mps': 4.0, 'duration_hours': 6.0},
        n_particles=100, seed=1, metocean_provider=provider))

    hindcast_steps = observed[:6]
    assert len(hindcast_steps) == 6
    for step, value in enumerate(hindcast_steps):
        assert 7.0 < value < 9.0, (
            f'step {step} used {value:.1f} m/s against a constant 8.0 m/s field; '
            f'perturbations are compounding again'
        )


def test_case10_particles_carry_distinct_release_times():
    """Case 10 (BUGLOG: ensemble varied position but not time).

    The hindcast duration is itself uncertain, so release TIME must vary across
    the ensemble for the attribution likelihood to be joint in space and time.
    """
    out = EnsembleDriftEngine().compute(
        EnsembleDriftInput(**BASE, n_particles=500, seed=11))

    times = {p['time'] for p in out.particles}
    assert len(times) > 1, 'every particle shares one release time'

    # With duration_sigma_frac=0 the spread must collapse back to a single time.
    fixed = EnsembleDriftEngine().compute(
        EnsembleDriftInput(**BASE, n_particles=500, seed=11, duration_sigma_frac=0.0))
    assert len({p['time'] for p in fixed.particles}) == 1


def test_case11_provider_failure_degrades_but_never_aborts():
    """Edge case: a met-ocean outage mid-trajectory must not lose the run."""
    def broken(lat, lon, when):
        raise RuntimeError('Open-Meteo unreachable')

    out = EnsembleDriftEngine().compute(EnsembleDriftInput(
        **{**BASE, 'duration_hours': 6.0}, n_particles=50, seed=1,
        metocean_provider=broken))

    assert out.metocean_degraded_steps == 6
    assert len(out.hindcast_trajectory) > 0
    assert out.radius_50_km > 0


def test_case12_antimeridian_and_pole_stay_finite():
    """Edge cases: longitude wraps, and cos(lat)->0 near the pole does not explode."""
    import math
    e = EnsembleDriftEngine()

    am = e.compute(EnsembleDriftInput(
        start_lat=0.5, start_lon=179.95, detection_time=T0,
        wind_speed_mps=15.0, wind_direction_deg=270.0,
        current_speed_mps=1.5, current_direction_deg=90.0,
        duration_hours=48.0, n_particles=200, seed=5))
    assert -180.0 <= am.origin_lon <= 180.0

    pole = e.compute(EnsembleDriftInput(
        start_lat=89.4, start_lon=10.0, detection_time=T0,
        wind_speed_mps=10.0, wind_direction_deg=180.0,
        current_speed_mps=0.5, current_direction_deg=90.0,
        duration_hours=24.0, n_particles=50, seed=2))
    assert math.isfinite(pole.origin_lon)
    assert math.isfinite(pole.origin_lat)
    assert math.isfinite(pole.radius_50_km)
    assert abs(pole.origin_lat) <= 90.0
