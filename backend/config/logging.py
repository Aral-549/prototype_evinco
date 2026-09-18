import json
import logging
import time
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """Formats log records as structured JSON lines with audit attributes."""

    def format(self, record):
        log_entry = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'correlation_id': getattr(record, 'correlation_id', None),
            'stage': getattr(record, 'stage', None),
            'duration_ms': getattr(record, 'duration_ms', None),
        }

        # Include custom extra metadata if present. stage_inputs/stage_outputs are
        # what make a scattered bug traceable to one stage rather than "somewhere in
        # the pipeline": each boundary records what it received and what it emitted.
        for key in ('stage_event', 'spills_count', 'suspects_count', 'error',
                    'stage_inputs', 'stage_outputs'):
            if hasattr(record, key):
                log_entry[key] = getattr(record, key)

        if record.exc_info:
            log_entry['exception'] = self.formatException(record.exc_info)

        # A log line must never crash the run that emitted it: a value that is not
        # JSON-serialisable falls back to its repr rather than raising.
        return json.dumps(log_entry, default=repr)


class PipelineLogger:
    """Helper logger adapter for pipeline stage boundaries."""

    def __init__(self, run_id: str):
        self.logger = logging.getLogger('pipeline')
        self.run_id = str(run_id)
        self.t_start = None
        self.current_stage = None

    def stage_start(self, stage: str, **kwargs):
        self.current_stage = stage
        self.t_start = time.time()
        self.logger.info(
            f"Stage started: {stage}",
            extra={
                'correlation_id': self.run_id,
                'stage': stage,
                'stage_event': 'stage_start',
                **kwargs,
            }
        )

    def stage_end(self, stage: str, status: str = 'completed', **kwargs):
        duration_ms = int((time.time() - self.t_start) * 1000) if self.t_start else 0
        self.logger.info(
            f"Stage {stage} {status} in {duration_ms}ms",
            extra={
                'correlation_id': self.run_id,
                'stage': stage,
                'stage_event': 'stage_end',
                'duration_ms': duration_ms,
                **kwargs,
            }
        )

    def error(self, msg: str, **kwargs):
        self.logger.error(
            msg,
            extra={
                'correlation_id': self.run_id,
                'stage': self.current_stage,
                **kwargs,
            }
        )
