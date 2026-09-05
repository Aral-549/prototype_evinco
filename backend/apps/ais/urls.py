from django.urls import path
from . import views

urlpatterns = [
    path('upload/', views.AISUploadView.as_view(), name='ais-upload'),
    path('vessels/', views.VesselListView.as_view(), name='vessel-list'),
    path('vessels/<str:mmsi>/track/', views.VesselTrackView.as_view(), name='vessel-track'),
    path('score/', views.VesselScoreView.as_view(), name='vessel-score'),
]
