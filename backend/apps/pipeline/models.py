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

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'PipelineRun {self.id} [{self.status}]'
