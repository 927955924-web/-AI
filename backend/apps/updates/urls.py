"""
URL configuration for updates app.
"""
from django.urls import path
from .views import CheckUpdateView, LatestYmlView, VersionListView, VersionDetailView

urlpatterns = [
    path('check/', CheckUpdateView.as_view(), name='update-check'),
    path('latest.yml', LatestYmlView.as_view(), name='update-latest-yml'),
    path('versions/', VersionListView.as_view(), name='version-list'),
    path('versions/<int:pk>/', VersionDetailView.as_view(), name='version-detail'),
]
