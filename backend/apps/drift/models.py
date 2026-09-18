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
    # Monte Carlo ensemble output. origin_uncertainty_km above is now the measured
    # 50th-percentile particle spread rather than the old 2.0 + 0.5*duration formula.
    n_particles = models.IntegerField(default=0)
    ensemble_seed = models.IntegerField(default=0)
    radius_50_km = models.FloatField(null=True, blank=True)
    radius_90_km = models.FloatField(null=True, blank=True)
    confidence_polygon_50 = models.JSONField(default=dict, blank=True)
    confidence_polygon_90 = models.JSONField(default=dict, blank=True)
    origin_particles = models.JSONField(default=list, blank=True)
    evaporated_fraction = models.FloatField(null=True, blank=True)
    weathering_warning = models.TextField(blank=True, default='')
    metocean_degraded_steps = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'DriftResult {self.id} (spill={self.spill_region_id}, engine={self.engine_used})'
