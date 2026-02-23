from django.contrib import admin
from .models import KnowledgeBase


@admin.register(KnowledgeBase)
class KnowledgeBaseAdmin(admin.ModelAdmin):
    list_display = ['question_short', 'shop', 'product', 'source', 'created_at']
    list_filter = ['shop', 'source']
    search_fields = ['question', 'answer']
    readonly_fields = ['created_at', 'updated_at']
    
    def question_short(self, obj):
        return obj.question[:50] + '...' if len(obj.question) > 50 else obj.question
    question_short.short_description = '问题'
