"""
Serializers for quick_replies app.
"""
from rest_framework import serializers
from .models import QuickReply


class QuickReplySerializer(serializers.ModelSerializer):
    """Serializer for quick reply details."""
    
    category_display = serializers.CharField(
        source='get_category_display', 
        read_only=True
    )
    
    class Meta:
        model = QuickReply
        fields = [
            'id', 'title', 'content', 'shortcut', 'category', 
            'category_display', 'usage_count', 'sort_order', 'is_active',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'usage_count', 'created_at', 'updated_at']


class QuickReplyCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating quick reply."""
    
    class Meta:
        model = QuickReply
        fields = [
            'title', 'content', 'shortcut', 'category', 'sort_order', 'is_active'
        ]
    
    def validate_shortcut(self, value):
        if value and not value.startswith('/'):
            value = '/' + value
        return value
    
    def create(self, validated_data):
        validated_data['user'] = self.context['request'].user
        return super().create(validated_data)


class QuickReplyRenderSerializer(serializers.Serializer):
    """Serializer for rendering quick reply with context."""
    
    context = serializers.DictField(required=False, default=dict)
