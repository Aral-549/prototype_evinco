from rest_framework import serializers
from .models import DetectionJob, SpillRegion

class SpillRegionSerializer(serializers.ModelSerializer):
    class Meta:
        model = SpillRegion
        fields = '__all__'
        read_only_fields = ('job',)

class DetectionJobSerializer(serializers.ModelSerializer):
    spill_regions = SpillRegionSerializer(many=True, read_only=True)

    class Meta:
        model = DetectionJob
        fields = '__all__'

class DetectionJobCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = DetectionJob
        fields = ('uploaded_image',)
