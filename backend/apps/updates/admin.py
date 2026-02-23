from django.contrib import admin
from .models import ClientVersion


@admin.register(ClientVersion)
class ClientVersionAdmin(admin.ModelAdmin):
    list_display = ['version', 'platform', 'file_name', 'file_size', 'is_latest', 'download_count', 'created_at']
    list_filter = ['platform', 'is_latest']
    search_fields = ['version', 'release_notes']
    ordering = ['-created_at']
