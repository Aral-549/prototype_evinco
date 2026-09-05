import time
from celery import shared_task
from django.utils import timezone
from config.logging import PipelineLogger

from apps.pipeline.models import PipelineRun
from apps.drift.models import DriftResult
from apps.drift.engines.lagrangian import LagrangianDriftEngine
from apps.drift.engines.base import DriftInput
from apps.drift.metocean import fetch_metocean_vectors


@shared_task(
    bind=True,
    queue='drift_queue',
    max_retries=2,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def compute_drift_task(self, run_id: str):
    """Celery task: Compute backward hindcast and forward forecast for detected slicks."""
    log = PipelineLogger(run_id)
    log.stage_start('drift')
    t0 = time.time()

    pipeline_run = PipelineRun.objects.get(id=run_id)
    pipeline_run.status = 'drifting'
    pipeline_run.stage = 'drift'
    pipeline_run.save(update_fields=['status', 'stage'])

    if not pipeline_run.detection_job:
        raise ValueError("Detection job missing for drift stage")

    spill_regions = list(pipeline_run.detection_job.spill_regions.all())

    # Layer 3 Georeference Gate: Halt drift modeling if image has no verified coordinates
    if not pipeline_run.is_georeferenced or any(r.centroid_lat is None for r in spill_regions):
        pipeline_run.status = 'completed'
        pipeline_run.stage = 'georeference_gated'
        pipeline_run.completed_at = timezone.now()
        pipeline_run.suspects_ranked = 0
        pipeline_run.error_message = (
            "Georeference Gate Active: Image lacks geospatial metadata (GeoTIFF tags or manual coordinates). "
            "Detection mask generated successfully, but hydrodynamic drift hindcasting and AIS vessel attribution "
            "are gated to prevent false maritime attribution."
        )
        pipeline_run.save(update_fields=['status', 'stage', 'completed_at', 'suspects_ranked', 'error_message'])
        log.stage_end('drift', status='gated')
        return str(run_id)

    engine = LagrangianDriftEngine()
    detection_time = pipeline_run.created_at or timezone.now()

    met_source = 'default_fallback'
    for region in spill_regions:
        wind_spd = pipeline_run.wind_speed_mps
        wind_dir = pipeline_run.wind_direction_deg
        curr_spd = pipeline_run.current_speed_mps
        curr_dir = pipeline_run.current_direction_deg

        # If user left values at standard defaults (5.0, 180.0, 0.3, 90.0), attempt to fetch real metocean data from cache/API
        if wind_spd == 5.0 and wind_dir == 180.0 and curr_spd == 0.3 and curr_dir == 90.0:
            met = fetch_metocean_vectors(region.centroid_lat, region.centroid_lon, detection_time)
            wind_spd = met['wind_speed_mps']
            wind_dir = met['wind_direction_deg']
            curr_spd = met['current_speed_mps']
            curr_dir = met['current_direction_deg']
            met_source = met.get('source', 'default_fallback')
        else:
            met_source = 'manual_override'

        drift_input = DriftInput(
            start_lat=region.centroid_lat,
            start_lon=region.centroid_lon,
            detection_time=detection_time,
            wind_speed_mps=wind_spd,
            wind_direction_deg=wind_dir,
            current_speed_mps=curr_spd,
            current_direction_deg=curr_dir,
            duration_hours=pipeline_run.drift_duration_hours,
        )
        drift_output = engine.compute(drift_input)

        DriftResult.objects.create(
            spill_region=region,
            engine_used=engine.name,
            origin_lat=drift_output.origin_lat,
            origin_lon=drift_output.origin_lon,
            origin_time=drift_output.origin_time,
            origin_uncertainty_km=drift_output.origin_uncertainty_km,
            hindcast_trajectory=drift_output.hindcast_trajectory,
            forecast_trajectory=drift_output.forecast_trajectory,
            wind_speed_mps=wind_spd,
            wind_direction_deg=wind_dir,
            current_speed_mps=curr_spd,
            current_direction_deg=curr_dir,
            duration_hours=pipeline_run.drift_duration_hours,
            metocean_source=met_source,
        )

    pipeline_run.metocean_source = met_source
    pipeline_run.save(update_fields=['metocean_source'])

    elapsed_ms = int((time.time() - t0) * 1000)
    pipeline_run.stage_durations['drift'] = elapsed_ms
    pipeline_run.save(update_fields=['stage_durations'])

    log.stage_end('drift', duration_ms=elapsed_ms)
    return str(run_id)
