import math
from datetime import datetime, timezone
import pytest
from apps.drift.engines.base import DriftInput
from apps.drift.engines.lagrangian import LagrangianDriftEngine


def test_lagrangian_drift_pure_north_current():
    """Unit Test: Pure North current vector -> assert backward hindcast moves South by exact degrees."""
    engine = LagrangianDriftEngine()

    t0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    inp = DriftInput(
        start_lat=0.0,
        start_lon=0.0,
        detection_time=t0,
        wind_speed_mps=0.0,
        wind_direction_deg=180.0,
        current_speed_mps=1.0,
        current_direction_deg=0.0,  # Flowing due North
        duration_hours=1.0,
        time_step_hours=1.0,
    )

    out = engine.compute(inp)

    # Hand calculation:
    # dt = 3600s, v_north = 1.0 m/s, distance = 3600m
    # delta_lat = - 3600 / 6_371_000 * (180 / pi) = -0.03237102°
    expected_lat = - (3600.0 / 6_371_000.0) * (180.0 / math.pi)

    assert pytest.approx(out.origin_lat, abs=1e-5) == expected_lat
    assert pytest.approx(out.origin_lon, abs=1e-5) == 0.0
    assert len(out.hindcast_trajectory) == 2
    assert len(out.forecast_trajectory) == 2


def test_lagrangian_drift_pure_east_wind():
    """Unit Test: Wind from West (270°) pushes East at alpha * wind_speed."""
    engine = LagrangianDriftEngine()

    t0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    inp = DriftInput(
        start_lat=0.0,
        start_lon=0.0,
        detection_time=t0,
        wind_speed_mps=10.0,
        wind_direction_deg=270.0,  # Wind coming FROM West pushes East
        current_speed_mps=0.0,
        current_direction_deg=0.0,
        duration_hours=1.0,
        time_step_hours=1.0,
    )

    out = engine.compute(inp)

    # alpha = 0.03 -> v_east = 0.03 * 10 = 0.3 m/s
    # Backward hindcast should place origin to the West (negative lon)
    expected_lon = - (0.3 * 3600.0 / 6_371_000.0) * (180.0 / math.pi)

    assert pytest.approx(out.origin_lon, abs=1e-5) == expected_lon
    assert pytest.approx(out.origin_lat, abs=1e-5) == 0.0
