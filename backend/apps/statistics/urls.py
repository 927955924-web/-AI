"""
URL configuration for statistics app.
"""
from django.urls import path
from .views import OverviewView, AIUsageView, TopQuestionsView, ShopStatsView
from .monitor_views import MonitorView

urlpatterns = [
    path('overview/', OverviewView.as_view(), name='stats-overview'),
    path('ai-usage/', AIUsageView.as_view(), name='stats-ai-usage'),
    path('top-questions/', TopQuestionsView.as_view(), name='stats-top-questions'),
    path('shops/<str:shop_id>/', ShopStatsView.as_view(), name='stats-shop'),
    path('monitor/', MonitorView.as_view(), name='stats-monitor'),
]
