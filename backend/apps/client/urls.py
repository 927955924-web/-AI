"""
URL configuration for client app.
"""
from django.urls import path
from .views import HeartbeatView, SyncMessageView, ClientSettingsView

urlpatterns = [
    path('heartbeat/', HeartbeatView.as_view(), name='client-heartbeat'),
    path('sync-message/', SyncMessageView.as_view(), name='client-sync-message'),
    path('settings/', ClientSettingsView.as_view(), name='client-settings'),
]
