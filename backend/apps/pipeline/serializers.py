from rest_framework import serializers
from .models import PipelineRun
from apps.detection.serializers import DetectionJobSerializer


class OptionalFloatField(serializers.FloatField):
    """FloatField that gracefully coerces empty form strings ('') to default or None."""
    def to_internal_value(self, data):
        if data == '' or data is None:
            if self.default is not serializers.empty:
                return self.default
            return None
        return super().to_internal_value(data)


class OptionalDateTimeField(serializers.DateTimeField):
    """DateTimeField that gracefully coerces empty form strings ('') to None."""
    def to_internal_value(self, data):
        if data == '' or data is None:
            return None
        return super().to_internal_value(data)


class PipelineRunCreateSerializer(serializers.Serializer):
    image = serializers.ImageField()
    wind_speed_mps = OptionalFloatField(default=5.0, required=False)
    wind_direction_deg = OptionalFloatField(default=180.0, required=False)
    current_speed_mps = OptionalFloatField(default=0.3, required=False)
    current_direction_deg = OptionalFloatField(default=90.0, required=False)
    drift_duration_hours = OptionalFloatField(default=24.0, required=False)
    detection_time = OptionalDateTimeField(required=False, allow_null=True)  # defaults to now

    # Layer 3 Georeference Manual Inputs (optional if GeoTIFF)
    bbox_min_lon = OptionalFloatField(required=False, allow_null=True)
    bbox_min_lat = OptionalFloatField(required=False, allow_null=True)
    bbox_max_lon = OptionalFloatField(required=False, allow_null=True)
    bbox_max_lat = OptionalFloatField(required=False, allow_null=True)


class PipelineRunSerializer(serializers.ModelSerializer):
    detection_job = DetectionJobSerializer(read_only=True)

    class Meta:
        model = PipelineRun
        fields = '__all__'
