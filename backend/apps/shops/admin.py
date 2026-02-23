from django.contrib import admin
from .models import Shop


@admin.register(Shop)
class ShopAdmin(admin.ModelAdmin):
    list_display = ['shop_name', 'platform_type', 'owner', 'is_active', 'created_at']
    list_filter = ['platform_type', 'is_active']
    search_fields = ['shop_name', 'account']
    readonly_fields = ['created_at', 'updated_at']
