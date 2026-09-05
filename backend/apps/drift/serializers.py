from rest_framework import serializers
from .models import DriftResult

class DriftInputSerializer(serializers.Serializer):
    spill_region_id = serializers.IntegerField(required=True)
    detection_time = serializers.DateTimeField(required=True)
    wind_speed_mps = serializers.FloatField(default=5.0)
    wind_direction_deg = serializers.FloatField(default=180.0)
    current_speed_mps = serializers.FloatField(default=0.3)
    current_direction_deg = serializers.FloatField(default=90.0)
    duration_hours = serializers.FloatField(default=24.0)
    engine = serializers.CharField(default='lagrangian')

class DriftResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = DriftResult
        fields = '__all__'
