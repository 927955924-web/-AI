from django.contrib import admin
from .models import LearningTask


@admin.register(LearningTask)
class LearningTaskAdmin(admin.ModelAdmin):
    list_display = ['shop', 'status', 'total_products', 'processed_products', 'created_at']
    list_filter = ['status', 'shop']
    readonly_fields = ['created_at', 'updated_at']
