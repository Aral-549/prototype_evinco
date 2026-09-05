import os
import time

import cv2
import numpy as np
from django.conf import settings
from django.utils import timezone

from apps.detection.inference import ModelManager
from apps.detection.preprocessing import load_image
from apps.detection.postprocessing import mask_to_polygons, pixels_to_geo
from apps.drift.engines.lagrangian import LagrangianDriftEngine
from apps.drift.engines.base import DriftInput
from apps.drift.metocean import fetch_metocean_vectors
from apps.ais.scoring import score_vessels

from apps.detection.models import DetectionJob, SpillRegion
from apps.drift.models import DriftResult
from apps.ais.models import SuspectScore


def run_pipeline(pipeline_run, image_path: str, detection_time=None, user_bbox=None) -> None:
    """Execute pipeline with Layer 1 (SAR OOD Check) and Layer 3 (Georeference Gate).

    If image is un-georeferenced, detection mask is extracted, but drift & AIS attribution
    are strictly gated to prevent false accusations.
    """
    try:
        if detection_time is None:
            detection_time = timezone.now()

        if user_bbox is None and all(getattr(pipeline_run, k) is not None for k in ('bbox_min_lon', 'bbox_min_lat', 'bbox_max_lon', 'bbox_max_lat')):
            user_bbox = (pipeline_run.bbox_min_lon, pipeline_run.bbox_min_lat, pipeline_run.bbox_max_lon, pipeline_run.bbox_max_lat)

        # ── Step 1: Detection & SAR Validation ────────────────────
        pipeline_run.status = 'detecting'
        pipeline_run.stage = 'detection'
        pipeline_run.save()

        # load_image executes Layer 1 SAR statistical validation & Layer 3 GeoTIFF extraction
        image_array, metadata = load_image(image_path, user_bbox=user_bbox)
        h, w = metadata['height'], metadata['width']
        is_georeferenced = metadata.get('is_georeferenced', False)
        bbox = metadata.get('bbox')

        pipeline_run.is_georeferenced = is_georeferenced
        pipeline_run.save(update_fields=['is_georeferenced'])

        rel_image_path = os.path.relpath(image_path, settings.MEDIA_ROOT)
        detection_job = DetectionJob.objects.create(
            uploaded_image=rel_image_path,
            image_width=w,
            image_height=h,
            status='processing',
        )
        pipeline_run.detection_job = detection_job
        pipeline_run.save()

        t0 = time.time()
        mask = ModelManager().predict(image_array)
        elapsed_ms = int((time.time() - t0) * 1000)

        # Save mask image
        results_dir = os.path.join(settings.MEDIA_ROOT, 'results')
        os.makedirs(results_dir, exist_ok=True)
        mask_filename = f'{pipeline_run.id}_mask.png'
        mask_path = os.path.join(results_dir, mask_filename)
        cv2.imwrite(mask_path, mask)

        detection_job.result_mask = f'results/{mask_filename}'
        detection_job.processing_time_ms = elapsed_ms
        detection_job.status = 'completed'
        detection_job.save()

        # Extract polygons
        raw_polygons = mask_to_polygons(mask)
        geo_polygons = pixels_to_geo(raw_polygons, w, h, bbox=bbox)

        spill_regions = []
        for gp in geo_polygons:
            region = SpillRegion.objects.create(
                job=detection_job,
                polygon_geojson=gp['polygon_geojson'],
                centroid_lat=gp['centroid_lat'],
                centroid_lon=gp['centroid_lon'],
                area_sq_km=gp.get('area_sq_km'),
                confidence=gp.get('confidence', 1.0),
            )
            spill_regions.append(region)

        pipeline_run.spills_detected = len(spill_regions)
        pipeline_run.stage_durations['detection'] = elapsed_ms

        # ── LAYER 3 GATE: Halt Attribution if Image is Un-georeferenced ──
        if not is_georeferenced or any(r.centroid_lat is None for r in spill_regions):
            pipeline_run.status = 'completed'
            pipeline_run.stage = 'georeference_gated'
            pipeline_run.completed_at = timezone.now()
            pipeline_run.suspects_ranked = 0
            pipeline_run.error_message = (
                "Georeference Gate Active: Image lacks geospatial metadata (GeoTIFF tags or manual coordinates). "
                "Detection mask generated successfully, but hydrodynamic drift hindcasting and AIS vessel attribution "
                "are gated to prevent false maritime attribution."
            )
            pipeline_run.save()
            return

        # ── Step 2: Drift hindcast / forecast ────────────────────
        pipeline_run.status = 'drifting'
        pipeline_run.stage = 'drift'
        pipeline_run.save()

        t_drift = time.time()
        engine = LagrangianDriftEngine()
        drift_results = []
        met_source = 'default_fallback'

        for region in spill_regions:
            wind_spd = pipeline_run.wind_speed_mps
            wind_dir = pipeline_run.wind_direction_deg
            curr_spd = pipeline_run.current_speed_mps
            curr_dir = pipeline_run.current_direction_deg

            # If user left values at standard defaults, attempt to fetch real metocean data
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

            drift_res = DriftResult.objects.create(
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
            drift_results.append(drift_res)

        pipeline_run.metocean_source = met_source
        pipeline_run.stage_durations['drift'] = int((time.time() - t_drift) * 1000)

        # ── Step 3: AIS vessel scoring ───────────────────────────
        pipeline_run.status = 'scoring'
        pipeline_run.stage = 'ais_attribution'
        pipeline_run.save()

        t_ais = time.time()
        total_suspects = 0
        for drift_res in drift_results:
            scores = score_vessels(drift_res)
            if scores:
                SuspectScore.objects.bulk_create(scores)
                total_suspects += len(scores)

        pipeline_run.stage_durations['ais_attribution'] = int((time.time() - t_ais) * 1000)

        # ── Done ─────────────────────────────────────────────────
        pipeline_run.status = 'completed'
        pipeline_run.stage = 'completed'
        pipeline_run.completed_at = timezone.now()
        pipeline_run.suspects_ranked = total_suspects
        pipeline_run.save()

    except Exception as e:
        pipeline_run.status = 'failed'
        pipeline_run.stage = 'failed'
        pipeline_run.error_message = str(e)
        pipeline_run.save()
        raise
