from django.contrib import admin
from .models import ConversationRecord, KeywordRule, SensitiveWordRule, ScenarioRule


@admin.register(ConversationRecord)
class ConversationRecordAdmin(admin.ModelAdmin):
    list_display = ['buyer_name', 'shop', 'created_at']
    list_filter = ['shop']
    search_fields = ['buyer_name', 'buyer_message', 'customer_reply']
    readonly_fields = ['created_at']


@admin.register(KeywordRule)
class KeywordRuleAdmin(admin.ModelAdmin):
    list_display = ['name', 'keywords', 'is_active', 'priority']
    list_filter = ['is_active']
    search_fields = ['name', 'keywords']


@admin.register(SensitiveWordRule)
class SensitiveWordRuleAdmin(admin.ModelAdmin):
    list_display = ['name', 'sensitive_words', 'replacement', 'is_active']
    list_filter = ['is_active']
    search_fields = ['name', 'sensitive_words']


@admin.register(ScenarioRule)
class ScenarioRuleAdmin(admin.ModelAdmin):
    list_display = ['name', 'scenario_type', 'is_active', 'priority']
    list_filter = ['scenario_type', 'is_active']
    search_fields = ['name']
