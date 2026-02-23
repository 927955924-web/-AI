"""
URL configuration for quick_replies app.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import QuickReplyViewSet

router = DefaultRouter()
router.register('', QuickReplyViewSet, basename='quick-reply')

urlpatterns = [
    path('', include(router.urls)),
]
