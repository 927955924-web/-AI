from django.contrib import admin
from .models import Shop


@admin.register(Shop)
class ShopAdmin(admin.ModelAdmin):
    list_display = ['name', 'platform', 'owner', 'is_active', 'created_at']
    list_filter = ['platform', 'is_active']
    search_fields = ['name', 'platform_shop_id']
    readonly_fields = ['created_at', 'updated_at']
