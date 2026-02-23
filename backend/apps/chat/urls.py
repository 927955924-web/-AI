"""
URL configuration for chat app.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ChatSessionViewSet, MessageListCreateView, MessageDetailView

router = DefaultRouter()
router.register('', ChatSessionViewSet, basename='session')

urlpatterns = [
    path('', include(router.urls)),
    path('messages/', MessageListCreateView.as_view(), name='message-list'),
    path('messages/<str:message_id>/', MessageDetailView.as_view(), name='message-detail'),
]
