from django.contrib import admin
from .models import Product


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['name', 'shop', 'platform_product_id', 'learning_status', 'created_at']
    list_filter = ['shop', 'learning_status']
    search_fields = ['name', 'platform_product_id']
    readonly_fields = ['created_at', 'updated_at']
