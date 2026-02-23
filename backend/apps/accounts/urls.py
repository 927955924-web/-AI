"""
URL configuration for accounts app.
"""
from django.urls import path
from .views import (
    RegisterView,
    LoginView,
    LogoutView,
    MeView,
    ChangePasswordView,
    VIPRenewView,
    CustomTokenRefreshView,
    ApiSettingsView,
)

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('refresh/', CustomTokenRefreshView.as_view(), name='token_refresh'),
    path('me/', MeView.as_view(), name='me'),
    path('change-password/', ChangePasswordView.as_view(), name='change_password'),
    path('renew-vip/', VIPRenewView.as_view(), name='renew_vip'),
    path('api-settings/', ApiSettingsView.as_view(), name='api_settings'),
]
