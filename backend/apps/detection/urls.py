from django.urls import path
from . import views

urlpatterns = [
    path('upload/', views.DetectionUploadView.as_view(), name='detection-upload'),
    path('<uuid:job_id>/', views.DetectionDetailView.as_view(), name='detection-detail'),
    path('<uuid:job_id>/mask/', views.DetectionMaskView.as_view(), name='detection-mask'),
]
