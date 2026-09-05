import uuid
from django.db import models


class DetectionJob(models.Model):
    """Tracks a single SAR image analysis job."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    uploaded_image = models.ImageField(upload_to='uploads/')
    result_mask = models.ImageField(upload_to='results/', null=True, blank=True)
    status = models.CharField(max_length=20, choices=[
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ], default='pending')
    error_message = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    processing_time_ms = models.IntegerField(null=True, blank=True)
    image_width = models.IntegerField(null=True, blank=True)
    image_height = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'DetectionJob {self.id} [{self.status}]'


class SpillRegion(models.Model):
    """A detected oil spill polygon from a DetectionJob."""
    job = models.ForeignKey(DetectionJob, related_name='spill_regions', on_delete=models.CASCADE)
    polygon_geojson = models.JSONField()
    centroid_lat = models.FloatField(null=True, blank=True)
    centroid_lon = models.FloatField(null=True, blank=True)
    area_sq_km = models.FloatField(null=True, blank=True)
    confidence = models.FloatField()

    def __str__(self):
        return f'SpillRegion {self.id} (job={self.job_id}, conf={self.confidence:.2f})'
