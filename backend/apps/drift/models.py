from django.db import models


class DriftResult(models.Model):
    """Result of drift hindcast/forecast for a spill region."""
    spill_region = models.ForeignKey(
        'detection.SpillRegion', on_delete=models.CASCADE, related_name='drift_results'
    )
    engine_used = models.CharField(max_length=50)  # 'lagrangian' or 'opendrift'
    # Estimated origin
    origin_lat = models.FloatField()
    origin_lon = models.FloatField()
    origin_time = models.DateTimeField()
    origin_uncertainty_km = models.FloatField(default=5.0)
    # Trajectories stored as JSON: [{"lat": float, "lon": float, "time": str}, ...]
    hindcast_trajectory = models.JSONField(default=list)
    forecast_trajectory = models.JSONField(default=list)
    # Environmental parameters used
    wind_speed_mps = models.FloatField()
    wind_direction_deg = models.FloatField()
    current_speed_mps = models.FloatField()
    current_direction_deg = models.FloatField()
    duration_hours = models.FloatField(default=24.0)
    metocean_source = models.CharField(max_length=50, default='default_fallback', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'DriftResult {self.id} (spill={self.spill_region_id}, engine={self.engine_used})'
