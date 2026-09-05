import os
import time
import cv2
from celery import shared_task
from django.conf import settings
from config.logging import PipelineLogger

from apps.pipeline.models import PipelineRun
from apps.detection.models import DetectionJob, SpillRegion
from apps.detection.inference import ModelManager
from apps.detection.preprocessing import load_image
from apps.detection.postprocessing import mask_to_polygons, pixels_to_geo


@shared_task(
    bind=True,
    queue='detection_queue',
    max_retries=2,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def detect_spill_task(self, run_id: str):
    """Celery task: Run SAR image tiling and U-Net segmentation."""
    log = PipelineLogger(run_id)
    log.stage_start('detection')

    pipeline_run = PipelineRun.objects.get(id=run_id)
    pipeline_run.status = 'detecting'
    pipeline_run.stage = 'detection'
    pipeline_run.save(update_fields=['status', 'stage'])

    image_path = pipeline_run.image_path
    user_bbox = None
    if all(getattr(pipeline_run, k) is not None for k in ('bbox_min_lon', 'bbox_min_lat', 'bbox_max_lon', 'bbox_max_lat')):
        user_bbox = (pipeline_run.bbox_min_lon, pipeline_run.bbox_min_lat, pipeline_run.bbox_max_lon, pipeline_run.bbox_max_lat)

    image_array, metadata = load_image(image_path, user_bbox=user_bbox)
    h, w = metadata['height'], metadata['width']

    rel_image_path = os.path.relpath(image_path, settings.MEDIA_ROOT)
    detection_job = DetectionJob.objects.create(
        uploaded_image=rel_image_path,
        image_width=w,
        image_height=h,
        status='processing',
    )
    pipeline_run.detection_job = detection_job
    pipeline_run.save(update_fields=['detection_job'])

    t0 = time.time()
    mask = ModelManager().predict(image_array)
    elapsed_ms = int((time.time() - t0) * 1000)

    results_dir = os.path.join(settings.MEDIA_ROOT, 'results')
    os.makedirs(results_dir, exist_ok=True)
    mask_filename = f'{pipeline_run.id}_mask.png'
    mask_path = os.path.join(results_dir, mask_filename)
    cv2.imwrite(mask_path, mask)

    detection_job.result_mask = f'results/{mask_filename}'
    detection_job.processing_time_ms = elapsed_ms
    detection_job.status = 'completed'
    detection_job.save()

    bbox = metadata.get('bbox')
    is_georeferenced = metadata.get('is_georeferenced', False)
    pipeline_run.is_georeferenced = is_georeferenced

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
    pipeline_run.save(update_fields=['is_georeferenced', 'spills_detected', 'stage_durations'])

    log.stage_end('detection', spills_count=len(spill_regions), duration_ms=elapsed_ms)
    return str(run_id)
