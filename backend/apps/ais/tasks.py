import time
from celery import shared_task
from config.logging import PipelineLogger

from apps.pipeline.models import PipelineRun
from apps.drift.models import DriftResult
from apps.ais.models import SuspectScore
from apps.ais.scoring import score_vessels


@shared_task(
    bind=True,
    queue='ais_queue',
    max_retries=2,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def score_ais_suspects_task(self, run_id: str):
    """Celery task: Correlate AIS tracks within origin window and rank suspect vessels."""
    log = PipelineLogger(run_id)
    log.stage_start('ais_attribution')
    t0 = time.time()

    pipeline_run = PipelineRun.objects.get(id=run_id)

    # Layer 3 Gate: Skip AIS correlation if un-georeferenced
    if not pipeline_run.is_georeferenced or pipeline_run.stage == 'georeference_gated':
        log.stage_end('ais_attribution', status='skipped_unanchored')
        return str(run_id)

    pipeline_run.status = 'scoring'
    pipeline_run.stage = 'ais_attribution'
    pipeline_run.save(update_fields=['status', 'stage'])

    drift_qs = DriftResult.objects.filter(
        spill_region__job=pipeline_run.detection_job
    )

    total_suspects = 0
    for drift_res in drift_qs:
        scores = score_vessels(drift_res)
        if scores:
            SuspectScore.objects.bulk_create(scores)
            total_suspects += len(scores)

    elapsed_ms = int((time.time() - t0) * 1000)
    pipeline_run.suspects_ranked = total_suspects
    pipeline_run.stage_durations['ais_attribution'] = elapsed_ms
    pipeline_run.save(update_fields=['suspects_ranked', 'stage_durations'])

    log.stage_end('ais_attribution', suspects_count=total_suspects, duration_ms=elapsed_ms)
    return str(run_id)
