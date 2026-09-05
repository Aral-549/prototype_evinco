import time
from celery import shared_task, chain
from django.utils import timezone
from config.logging import PipelineLogger

from apps.pipeline.models import PipelineRun
from apps.detection.tasks import detect_spill_task
from apps.drift.tasks import compute_drift_task
from apps.ais.tasks import score_ais_suspects_task


@shared_task(queue='default')
def finalize_run_task(run_id: str):
    """Celery task: Mark pipeline run as completed and compute final totals."""
    log = PipelineLogger(run_id)
    pipeline_run = PipelineRun.objects.get(id=run_id)

    total_duration_ms = sum(pipeline_run.stage_durations.values())
    pipeline_run.status = 'completed'
    pipeline_run.stage = 'completed'
    pipeline_run.completed_at = timezone.now()
    pipeline_run.save(update_fields=['status', 'stage', 'completed_at'])

    log.stage_end('full_pipeline', status='completed', total_duration_ms=total_duration_ms)
    return str(run_id)


@shared_task(queue='default')
def pipeline_error_handler(request, exc, traceback, run_id: str):
    """Celery errback: Handle task failure, record error on PipelineRun."""
    log = PipelineLogger(run_id)
    try:
        pipeline_run = PipelineRun.objects.get(id=run_id)
        pipeline_run.status = 'failed'
        pipeline_run.stage = 'failed'
        pipeline_run.error_message = str(exc)
        pipeline_run.save(update_fields=['status', 'stage', 'error_message'])
        log.error(f"Pipeline failed: {exc}", error=str(exc))
    except Exception as e:
        log.error(f"Failed to record pipeline error: {e}")


def launch_pipeline_chain(run_id: str):
    """Trigger the asynchronous execution chain:

    detect_spill -> compute_drift -> score_ais_suspects -> finalize_run
    """
    workflow = chain(
        detect_spill_task.s(run_id),
        compute_drift_task.s(),
        score_ais_suspects_task.s(),
        finalize_run_task.s(),
    )
    # Link error callback
    return workflow.apply_async(link_error=pipeline_error_handler.s(run_id))
