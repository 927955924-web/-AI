"""
URL configuration for ecommerce_customer_service project.
"""
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    # API v1
    path('api/v1/auth/', include('apps.accounts.urls')),
    path('api/v1/shops/', include('apps.shops.urls')),
    path('api/v1/sessions/', include('apps.chat.urls')),
    path('api/v1/products/', include('apps.products.urls')),
    path('api/v1/knowledge/', include('apps.knowledge.urls')),
    path('api/v1/ai/', include('apps.ai.urls')),
    path('api/v1/quick-replies/', include('apps.quick_replies.urls')),
    path('api/v1/stats/', include('apps.statistics.urls')),
    path('api/v1/client/', include('apps.client.urls')),
    path('api/v1/learning/', include('apps.learning.urls')),
    path('api/v1/updates/', include('apps.updates.urls')),
]
