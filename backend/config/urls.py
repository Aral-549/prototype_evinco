from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from apps.pipeline.views import upload_page, results_page

urlpatterns = [
    path('admin/', admin.site.urls),

    # OpenAPI 3 Schema & Swagger UI
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),

    # Sub-system REST API endpoints
    path('api/v1/detection/', include('apps.detection.urls')),
    path('api/v1/drift/', include('apps.drift.urls')),
    path('api/v1/ais/', include('apps.ais.urls')),
    path('api/v1/pipeline/', include('apps.pipeline.urls')),

    # Template views (frontend)
    path('', upload_page, name='upload'),
    path('results/<uuid:run_id>/', results_page, name='results'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
