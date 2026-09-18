from django.db import models


class Vessel(models.Model):
    """A vessel identified by MMSI."""
    mmsi = models.CharField(max_length=9, unique=True, db_index=True)
    name = models.CharField(max_length=200, blank=True, default='')
    vessel_type = models.CharField(max_length=100, blank=True, default='')
    flag = models.CharField(max_length=50, blank=True, default='')
    length_m = models.FloatField(null=True, blank=True)
    width_m = models.FloatField(null=True, blank=True)

    def __str__(self):
        return f'{self.name or "Unknown"} (MMSI: {self.mmsi})'


class AISRecord(models.Model):
    """A single AIS position report."""
    vessel = models.ForeignKey(Vessel, related_name='ais_records', on_delete=models.CASCADE)
    timestamp = models.DateTimeField(db_index=True)
    lat = models.FloatField()
    lon = models.FloatField()
    speed_knots = models.FloatField(null=True, blank=True)
    heading = models.FloatField(null=True, blank=True)
    course = models.FloatField(null=True, blank=True)
    status = models.CharField(max_length=50, blank=True, default='')

    class Meta:
        ordering = ['timestamp']
        indexes = [
            models.Index(fields=['timestamp', 'lat', 'lon']),
            models.Index(fields=['vessel', 'timestamp']),
        ]

    def __str__(self):
        return f'AIS {self.vessel.mmsi} @ {self.timestamp}'


class SuspectScore(models.Model):
    """Scored suspect vessel for a specific drift result."""
    drift_result = models.ForeignKey(
        'drift.DriftResult', on_delete=models.CASCADE, related_name='suspect_scores'
    )
    vessel = models.ForeignKey(Vessel, on_delete=models.CASCADE, related_name='suspect_scores')
    proximity_score = models.FloatField()
    temporal_score = models.FloatField()
    behavioral_score = models.FloatField()
    composite_score = models.FloatField()
    min_distance_km = models.FloatField()
    closest_time = models.DateTimeField()
    anomalies_detected = models.JSONField(default=list)
    rank = models.IntegerField(default=0)
    # Bayesian attribution (apps/ais/attribution.py). The legacy composite_score
    # above is retained so existing clients and tests keep working, but posterior
    # is the figure the dossier reports: it is joint in space and time, whereas
    # composite_score summed independent proximity and temporal minima.
    posterior = models.FloatField(null=True, blank=True)
    spatiotemporal_likelihood = models.FloatField(null=True, blank=True)
    behavioural_factor = models.FloatField(null=True, blank=True)
    cpa_km = models.FloatField(null=True, blank=True)
    cpa_time = models.DateTimeField(null=True, blank=True)
    verdict = models.CharField(max_length=32, blank=True, default='')
    explanation = models.JSONField(default=list, blank=True)
    # Physical self-consistency of this vessel's AIS track. AIS is an
    # unauthenticated broadcast; a track that is physically impossible is grounds
    # for review, not proof of spoofing.
    integrity_plausible = models.BooleanField(default=True)
    integrity_flags = models.JSONField(default=list, blank=True)
    max_implied_speed_kn = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ['rank']
        unique_together = ['drift_result', 'vessel']

    def __str__(self):
        return f'Suspect #{self.rank}: {self.vessel.mmsi} (score={self.composite_score:.3f})'
