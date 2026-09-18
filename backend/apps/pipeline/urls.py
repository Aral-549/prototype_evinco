from django.urls import path

from . import views
from .dossier import (
    PipelineDossierView, PipelineStatusView, PipelineRunListView,
    PipelineReportPDFView,
)

urlpatterns = [
    path('run/', views.PipelineRunView.as_view(), name='pipeline-run'),
    path('runs/', PipelineRunListView.as_view(), name='pipeline-list'),
    # Registered before the bare <uuid:pk>/ route so the suffixed paths match first.
    path('<uuid:pk>/status/', PipelineStatusView.as_view(), name='pipeline-status'),
    path('<uuid:pk>/dossier/', PipelineDossierView.as_view(), name='pipeline-dossier'),
    path('<uuid:pk>/report.pdf', PipelineReportPDFView.as_view(), name='pipeline-report'),
    path('<uuid:pk>/', views.PipelineRunDetailView.as_view(), name='pipeline-detail'),
]
