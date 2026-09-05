from rest_framework import serializers
from .models import Vessel, AISRecord, SuspectScore

class VesselSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vessel
        fields = '__all__'

class AISRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = AISRecord
        fields = '__all__'

class SuspectScoreSerializer(serializers.ModelSerializer):
    vessel = VesselSerializer(read_only=True)
    
    class Meta:
        model = SuspectScore
        fields = '__all__'

class AISUploadSerializer(serializers.Serializer):
    file = serializers.FileField()

class VesselScoreInputSerializer(serializers.Serializer):
    drift_result_id = serializers.IntegerField()
    search_radius_km = serializers.FloatField(default=50.0)
    time_window_hours = serializers.FloatField(default=48.0)
