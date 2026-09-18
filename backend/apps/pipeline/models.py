import uuid
from django.db import models


class PipelineRun(models.Model):
    """End-to-end analysis run tying all three sub-systems."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    detection_job = models.OneToOneField(
        'detection.DetectionJob', on_delete=models.CASCADE,
        related_name='pipeline_run', null=True, blank=True
    )
    status = models.CharField(max_length=20, choices=[
        ('pending', 'Pending'),
        ('detecting', 'Detecting spills...'),
        ('drifting', 'Computing drift...'),
        ('scoring', 'Scoring vessels...'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ], default='pending')
    stage = models.CharField(max_length=50, default='queued', blank=True)
    stage_durations = models.JSONField(default=dict, blank=True)
    image_path = models.CharField(max_length=500, blank=True, default='')
    is_georeferenced = models.BooleanField(default=False)
    error_message = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    spills_detected = models.IntegerField(default=0)
    suspects_ranked = models.IntegerField(default=0)
    # Drift parameters (user can override defaults)
    wind_speed_mps = models.FloatField(default=5.0)
    wind_direction_deg = models.FloatField(default=180.0)
    current_speed_mps = models.FloatField(default=0.3)
    current_direction_deg = models.FloatField(default=90.0)
    drift_duration_hours = models.FloatField(default=24.0)
    metocean_source = models.CharField(max_length=50, default='default_fallback', blank=True)
    # Optional manual bounding box for georeferencing standard images
    bbox_min_lon = models.FloatField(null=True, blank=True)
    bbox_min_lat = models.FloatField(null=True, blank=True)
    bbox_max_lon = models.FloatField(null=True, blank=True)
    bbox_max_lat = models.FloatField(null=True, blank=True)
    # Forensic chain of custody (apps/pipeline/evidence.py)
    evidence_manifest = models.JSONField(default=dict, blank=True)
    manifest_sha256 = models.CharField(max_length=64, blank=True, default='', db_index=True)
    # Case-level attribution conclusion, including the explicit
    # "source is not in this AIS data" hypothesis.
    attribution_summary = models.JSONField(default=dict, blank=True)
    unknown_vessel_posterior = models.FloatField(null=True, blank=True)
    regions_rejected_as_lookalike = models.IntegerField(default=0)
    # Adversarial self-audit: how the conclusion holds up when the assumptions it
    # rests on are varied across their defensible ranges.
    robustness_report = models.JSONField(default=dict, blank=True)
    # Who submitted this scene. The label is the API key's name; the fingerprint is a
    # digest, never the key itself, so a leaked dossier cannot leak the credential
    # that produced it.
    submitted_by = models.CharField(max_length=64, blank=True, default='')
    submitted_by_fingerprint = models.CharField(max_length=64, blank=True, default='')

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'PipelineRun {self.id} [{self.status}]'
