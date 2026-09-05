import tempfile
import os
from rest_framework.views import APIView
from rest_framework.generics import ListAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework import status
from django.apps import apps
from django.shortcuts import get_object_or_404
from .models import Vessel, AISRecord, SuspectScore
from .serializers import (
    VesselSerializer,
    AISRecordSerializer,
    SuspectScoreSerializer,
    AISUploadSerializer,
    VesselScoreInputSerializer
)
from .ingest import ingest_ais_csv
from .scoring import score_vessels

class AISUploadView(APIView):
    def post(self, request):
        serializer = AISUploadSerializer(data=request.data)
        if serializer.is_valid():
            uploaded_file = serializer.validated_data['file']
            
            fd, temp_path = tempfile.mkstemp(suffix='.csv')
            with os.fdopen(fd, 'wb') as f:
                for chunk in uploaded_file.chunks():
                    f.write(chunk)
                    
            try:
                summary = ingest_ais_csv(temp_path)
                return Response(summary, status=status.HTTP_201_CREATED)
            finally:
                os.remove(temp_path)
                
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class _VesselPagination(PageNumberPagination):
    page_size = 50


class VesselListView(ListAPIView):
    queryset = Vessel.objects.all().order_by('id')
    serializer_class = VesselSerializer
    pagination_class = _VesselPagination

class VesselTrackView(APIView):
    def get(self, request, mmsi):
        vessel = get_object_or_404(Vessel, mmsi=mmsi)
        records = AISRecord.objects.filter(vessel=vessel).order_by('timestamp')
        
        start_time = request.query_params.get('start_time')
        end_time = request.query_params.get('end_time')
        
        if start_time:
            records = records.filter(timestamp__gte=start_time)
        if end_time:
            records = records.filter(timestamp__lte=end_time)
            
        serializer = AISRecordSerializer(records, many=True)
        return Response(serializer.data)

class VesselScoreView(APIView):
    def post(self, request):
        serializer = VesselScoreInputSerializer(data=request.data)
        if serializer.is_valid():
            drift_result_id = serializer.validated_data['drift_result_id']
            search_radius_km = serializer.validated_data['search_radius_km']
            time_window_hours = serializer.validated_data['time_window_hours']
            
            DriftResult = apps.get_model('drift', 'DriftResult')
            drift_result = get_object_or_404(DriftResult, id=drift_result_id)
            
            SuspectScore.objects.filter(drift_result=drift_result).delete()
            
            scores = score_vessels(
                drift_result=drift_result,
                search_radius_km=search_radius_km,
                time_window_hours=time_window_hours
            )
            
            SuspectScore.objects.bulk_create(scores)
            
            serializer = SuspectScoreSerializer(scores, many=True)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
            
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
