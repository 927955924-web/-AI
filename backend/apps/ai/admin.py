from django.contrib import admin
from .models import ConversationRecord, KeywordRule, SensitiveWordRule, ScenarioRule


@admin.register(ConversationRecord)
class ConversationRecordAdmin(admin.ModelAdmin):
    list_display = ['customer_name', 'shop', 'created_at']
    list_filter = ['shop']
    search_fields = ['customer_name', 'customer_message', 'ai_response']
    readonly_fields = ['created_at']


@admin.register(KeywordRule)
class KeywordRuleAdmin(admin.ModelAdmin):
    list_display = ['name', 'keyword', 'is_active', 'priority']
    list_filter = ['is_active']
    search_fields = ['name', 'keyword']


@admin.register(SensitiveWordRule)
class SensitiveWordRuleAdmin(admin.ModelAdmin):
    list_display = ['word', 'action', 'is_active']
    list_filter = ['action', 'is_active']
    search_fields = ['word']


@admin.register(ScenarioRule)
class ScenarioRuleAdmin(admin.ModelAdmin):
    list_display = ['name', 'scenario_type', 'is_active', 'priority']
    list_filter = ['scenario_type', 'is_active']
    search_fields = ['name']
