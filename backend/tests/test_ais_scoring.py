from datetime import datetime, timedelta, timezone
import pytest
from apps.ais.models import Vessel, AISRecord
from apps.drift.models import DriftResult
from apps.detection.models import DetectionJob, SpillRegion
from apps.ais.scoring import score_vessels


@pytest.mark.django_db
def test_ais_scoring_ranks_anomalous_proximate_vessel_first():
    """Unit Test: Proximate vessel with speed anomaly scores higher than distant steady transit vessel."""
    job = DetectionJob.objects.create(status='completed')
    region = SpillRegion.objects.create(
        job=job,
        polygon_geojson={'type': 'Polygon', 'coordinates': []},
        centroid_lat=19.0,
        centroid_lon=72.0,
        confidence=1.0,
    )

    t_origin = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    drift = DriftResult.objects.create(
        spill_region=region,
        engine_used='lagrangian',
        origin_lat=19.0,
        origin_lon=72.0,
        origin_time=t_origin,
        wind_speed_mps=5.0,
        wind_direction_deg=180.0,
        current_speed_mps=0.3,
        current_direction_deg=90.0,
    )

    # Vessel A (Prime Suspect: 1km away, decelerates from 15 kn to 3 kn within 5 min)
    vessel_a = Vessel.objects.create(mmsi='111111111', name='SUSPECT TANKER')
    AISRecord.objects.create(
        vessel=vessel_a,
        timestamp=t_origin - timedelta(minutes=5),
        lat=18.99,
        lon=71.99,
        speed_knots=15.0
    )
    AISRecord.objects.create(
        vessel=vessel_a,
        timestamp=t_origin,
        lat=19.005,
        lon=72.005,
        speed_knots=3.0  # Speed drop > 5 kn within 15 min
    )

    # Vessel B (Innocent Transit: 35km away, steady 16 kn)
    vessel_b = Vessel.objects.create(mmsi='222222222', name='INNOCENT CARGO')
    AISRecord.objects.create(
        vessel=vessel_b,
        timestamp=t_origin,
        lat=19.32,
        lon=72.0,
        speed_knots=16.0
    )

    scores = score_vessels(drift, search_radius_km=50.0, time_window_hours=24.0)

    assert len(scores) == 2
    assert scores[0].vessel == vessel_a
    assert scores[0].rank == 1
    assert scores[1].vessel == vessel_b
    assert scores[1].rank == 2
    assert scores[0].composite_score > scores[1].composite_score
    assert 'speed_change' in scores[0].anomalies_detected
