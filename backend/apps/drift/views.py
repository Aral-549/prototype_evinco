from rest_framework.views import APIView
from rest_framework.generics import RetrieveAPIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.apps import apps
from .serializers import DriftInputSerializer, DriftResultSerializer
from .models import DriftResult
from .engines.base import DriftInput
from .engines.lagrangian import LagrangianDriftEngine
from .engines.opendrift_engine import OpenDriftEngine


class DriftComputeView(APIView):
    def post(self, request, *args, **kwargs):
        serializer = DriftInputSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            
        data = serializer.validated_data
        
        SpillRegion = apps.get_model('detection', 'SpillRegion')
        spill_region = get_object_or_404(SpillRegion, id=data['spill_region_id'])
        
        # Check if spill region is georeferenced
        start_lat = getattr(spill_region, 'centroid_lat', None)
        start_lon = getattr(spill_region, 'centroid_lon', None)

        if start_lat is None or start_lon is None:
            return Response(
                {
                    'error': 'Attribution Gated: This SpillRegion is not georeferenced. '
                             'Physical geographic coordinates are required for hydrodynamic drift modeling.'
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        drift_input = DriftInput(
            start_lat=start_lat,
            start_lon=start_lon,
            detection_time=data['detection_time'],
            wind_speed_mps=data['wind_speed_mps'],
            wind_direction_deg=data['wind_direction_deg'],
            current_speed_mps=data['current_speed_mps'],
            current_direction_deg=data['current_direction_deg'],
            duration_hours=data['duration_hours'],
        )
        
        engine_name = data['engine']
        if engine_name == 'lagrangian':
            engine = LagrangianDriftEngine()
        elif engine_name == 'opendrift':
            engine = OpenDriftEngine()
        else:
            return Response({'error': f'Unknown engine: {engine_name}'}, status=status.HTTP_400_BAD_REQUEST)
            
        output = engine.compute(drift_input)
        
        result = DriftResult.objects.create(
            spill_region=spill_region,
            engine_used=engine_name,
            origin_lat=output.origin_lat,
            origin_lon=output.origin_lon,
            origin_time=output.origin_time,
            origin_uncertainty_km=output.origin_uncertainty_km,
            hindcast_trajectory=output.hindcast_trajectory,
            forecast_trajectory=output.forecast_trajectory,
            wind_speed_mps=drift_input.wind_speed_mps,
            wind_direction_deg=drift_input.wind_direction_deg,
            current_speed_mps=drift_input.current_speed_mps,
            current_direction_deg=drift_input.current_direction_deg,
            duration_hours=drift_input.duration_hours,
        )
        
        result_serializer = DriftResultSerializer(result)
        return Response(result_serializer.data, status=status.HTTP_201_CREATED)


class DriftDetailView(RetrieveAPIView):
    queryset = DriftResult.objects.all()
    serializer_class = DriftResultSerializer
