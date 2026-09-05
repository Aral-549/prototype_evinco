from django.urls import path
from . import views

urlpatterns = [
    path('compute/', views.DriftComputeView.as_view(), name='drift-compute'),
    path('<int:pk>/', views.DriftDetailView.as_view(), name='drift-detail'),
]
