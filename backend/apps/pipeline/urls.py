from django.urls import path
from . import views

urlpatterns = [
    path('run/', views.PipelineRunView.as_view(), name='pipeline-run'),
    path('<uuid:pk>/', views.PipelineRunDetailView.as_view(), name='pipeline-detail'),
]
