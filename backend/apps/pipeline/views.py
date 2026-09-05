import json
import os

from django.conf import settings
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework.views import APIView
from rest_framework.generics import RetrieveAPIView
from rest_framework.response import Response
from rest_framework import status

from .models import PipelineRun
from .serializers import PipelineRunCreateSerializer, PipelineRunSerializer
from .orchestrator import run_pipeline


@method_decorator(csrf_exempt, name='dispatch')
class PipelineRunView(APIView):
    """POST: Run the full pipeline with an uploaded SAR image."""

    def post(self, request):
        serializer = PipelineRunCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        image_file = data['image']

        pipeline_run = PipelineRun.objects.create(
            wind_speed_mps=data.get('wind_speed_mps', 5.0),
            wind_direction_deg=data.get('wind_direction_deg', 180.0),
            current_speed_mps=data.get('current_speed_mps', 0.3),
            current_direction_deg=data.get('current_direction_deg', 90.0),
            drift_duration_hours=data.get('drift_duration_hours', 24.0),
            bbox_min_lon=data.get('bbox_min_lon'),
            bbox_min_lat=data.get('bbox_min_lat'),
            bbox_max_lon=data.get('bbox_max_lon'),
            bbox_max_lat=data.get('bbox_max_lat'),
        )

        # Save uploaded image
        upload_dir = os.path.join(settings.MEDIA_ROOT, 'uploads')
        os.makedirs(upload_dir, exist_ok=True)
        image_path = os.path.join(
            upload_dir, f'{pipeline_run.id}_{image_file.name}'
        )
        with open(image_path, 'wb') as f:
            for chunk in image_file.chunks():
                f.write(chunk)

        # Store image path on model for idempotent task execution
        pipeline_run.image_path = image_path
        pipeline_run.save(update_fields=['image_path'])

        detection_time = data.get('detection_time') or timezone.now()

        user_bbox = None
        if all(k in data and data[k] is not None for k in ('bbox_min_lon', 'bbox_min_lat', 'bbox_max_lon', 'bbox_max_lat')):
            user_bbox = (data['bbox_min_lon'], data['bbox_min_lat'], data['bbox_max_lon'], data['bbox_max_lat'])

        # Check if synchronous execution explicitly requested or needed as fallback
        is_sync = request.query_params.get('sync', 'false').lower() == 'true'

        if not is_sync:
            try:
                from config.celery import app as celery_app
                # Check for active workers with a quick 200ms ping
                pings = celery_app.control.ping(timeout=0.25)
                if pings:
                    from .tasks import launch_pipeline_chain
                    launch_pipeline_chain(str(pipeline_run.id))
                    return Response(
                        PipelineRunSerializer(pipeline_run).data,
                        status=status.HTTP_202_ACCEPTED
                    )
            except Exception:
                # Redis unreachable or no workers available -> fall through to synchronous mode
                pass

        # Synchronous execution (either explicitly requested, or as reliable fallback when Celery worker is offline)
        try:
            run_pipeline(pipeline_run, image_path, detection_time=detection_time, user_bbox=user_bbox)
        except Exception as e:
            import traceback
            traceback.print_exc()

        pipeline_run.refresh_from_db()
        http_status = (
            status.HTTP_201_CREATED
            if pipeline_run.status == 'completed'
            else status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        return Response(PipelineRunSerializer(pipeline_run).data, status=http_status)


class PipelineRunDetailView(RetrieveAPIView):
    """GET: Retrieve pipeline run results."""
    queryset = PipelineRun.objects.all()
    serializer_class = PipelineRunSerializer
    lookup_field = 'pk'


# ── Template views ───────────────────────────────────────────────

def upload_page(request):
    """Render the upload form page."""
    recent_runs = PipelineRun.objects.all()[:10]
    return render(request, 'upload.html', {'recent_runs': recent_runs})


def results_page(request, run_id):
    """Render the results page with Leaflet map."""
    pipeline_run = get_object_or_404(PipelineRun, pk=run_id)

    from apps.detection.inference import ModelManager
    model_info = ModelManager().get_model_info()

    context = {
        'run': pipeline_run,
        'model_info': model_info,
        'spill_regions': [],
        'drift_results': [],
        'suspects': [],
        'spill_regions_json': '[]',
        'drift_results_json': '[]',
        'suspects_json': '[]',
    }

    if pipeline_run.detection_job:
        spill_regions = pipeline_run.detection_job.spill_regions.all()

        spills = [
            {
                'id': s.id,
                'polygon_geojson': s.polygon_geojson,
                'centroid_lat': s.centroid_lat,
                'centroid_lon': s.centroid_lon,
                'area_sq_km': s.area_sq_km,
                'confidence': s.confidence,
            }
            for s in spill_regions
        ]
        context['spill_regions'] = spills
        context['spill_regions_data'] = spills

        from apps.drift.models import DriftResult
        drift_qs = DriftResult.objects.filter(spill_region__in=spill_regions)

        drifts = [
            {
                'id': d.id,
                'origin_lat': d.origin_lat,
                'origin_lon': d.origin_lon,
                'origin_time': d.origin_time.isoformat() if d.origin_time else None,
                'origin_uncertainty_km': d.origin_uncertainty_km,
                'hindcast_trajectory': d.hindcast_trajectory,
                'forecast_trajectory': d.forecast_trajectory,
            }
            for d in drift_qs
        ]
        context['drift_results'] = drifts
        context['drift_results_data'] = drifts

        from apps.ais.models import SuspectScore
        suspects = SuspectScore.objects.filter(
            drift_result__in=drift_qs
        ).select_related('vessel').order_by('rank')

        suspect_list = [
            {
                'rank': s.rank,
                'mmsi': s.vessel.mmsi,
                'vessel_name': s.vessel.name,
                'vessel_type': s.vessel.vessel_type,
                'composite_score': round(s.composite_score, 4),
                'proximity_score': round(s.proximity_score, 4),
                'temporal_score': round(s.temporal_score, 4),
                'behavioral_score': round(s.behavioral_score, 4),
                'min_distance_km': round(s.min_distance_km, 2),
                'anomalies': s.anomalies_detected,
            }
            for s in suspects
        ]
        context['suspects'] = suspect_list
        context['suspects_data'] = suspect_list

    return render(request, 'results.html', context)
