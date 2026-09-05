import time
import io
import traceback
from PIL import Image
from django.core.files.base import ContentFile
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.generics import RetrieveAPIView
from rest_framework.response import Response
from rest_framework import status

from .models import DetectionJob, SpillRegion
from .serializers import DetectionJobSerializer, DetectionJobCreateSerializer
from .preprocessing import load_image
from .inference import ModelManager
from .postprocessing import mask_to_polygons, pixels_to_geo


class DetectionUploadView(APIView):
    def post(self, request, *args, **kwargs):
        serializer = DetectionJobCreateSerializer(data=request.data)
        if serializer.is_valid():
            job = serializer.save()
            job.status = 'processing'
            job.save()

            start_time = time.time()
            try:
                # 1. Load Image
                image_path = job.uploaded_image.path
                image_array, metadata = load_image(image_path)
                
                job.image_width = metadata['width']
                job.image_height = metadata['height']
                job.save()

                # 2. Run Inference
                manager = ModelManager()
                mask_array = manager.predict(image_array)

                # 3. Save mask as PNG
                mask_img = Image.fromarray(mask_array, mode='L')
                mask_io = io.BytesIO()
                mask_img.save(mask_io, format='PNG')
                job.result_mask.save(f'mask_{job.id}.png', ContentFile(mask_io.getvalue()), save=False)

                # 4. Postprocessing (Extract Polygons)
                polygons_data = mask_to_polygons(mask_array)
                geo_data = pixels_to_geo(
                    polygons_data,
                    metadata['width'],
                    metadata['height'],
                    bbox=metadata.get('bbox'),
                )

                # 5. Create SpillRegion objects
                for region in geo_data:
                    SpillRegion.objects.create(
                        job=job,
                        polygon_geojson=region['polygon_geojson'],
                        centroid_lat=region['centroid_lat'],
                        centroid_lon=region['centroid_lon'],
                        area_sq_km=region.get('area_sq_km'),
                        confidence=region.get('confidence', 1.0),
                    )

                # 6. Finalize job
                job.status = 'completed'
                job.processing_time_ms = int((time.time() - start_time) * 1000)
                job.save()

                result_serializer = DetectionJobSerializer(job)
                return Response(result_serializer.data, status=status.HTTP_201_CREATED)

            except Exception as e:
                job.status = 'failed'
                job.error_message = str(e)
                job.processing_time_ms = int((time.time() - start_time) * 1000)
                job.save()
                http_status = (
                    status.HTTP_400_BAD_REQUEST
                    if isinstance(e, ValueError)
                    else status.HTTP_500_INTERNAL_SERVER_ERROR
                )
                return Response(DetectionJobSerializer(job).data, status=http_status)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class DetectionDetailView(RetrieveAPIView):
    queryset = DetectionJob.objects.all()
    serializer_class = DetectionJobSerializer
    lookup_field = 'id'
    lookup_url_kwarg = 'job_id'


class DetectionMaskView(APIView):
    def get(self, request, job_id, *args, **kwargs):
        job = get_object_or_404(DetectionJob, id=job_id)
        if not job.result_mask:
            raise Http404("Mask not generated yet or failed.")
        
        return FileResponse(job.result_mask.open(), content_type='image/png')
