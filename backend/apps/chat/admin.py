from django.contrib import admin
from .models import ChatSession, Message


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ['customer_name', 'shop', 'platform', 'status', 'created_at']
    list_filter = ['shop', 'platform', 'status']
    search_fields = ['customer_name', 'customer_id']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ['content_short', 'session', 'sender_type', 'created_at']
    list_filter = ['sender_type']
    search_fields = ['content']
    readonly_fields = ['created_at']
    
    def content_short(self, obj):
        return obj.content[:50] + '...' if len(obj.content) > 50 else obj.content
    content_short.short_description = '内容'
