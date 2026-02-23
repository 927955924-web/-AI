"""
Serializers for knowledge app.
"""
from rest_framework import serializers
from .models import KnowledgeBase


class KnowledgeSerializer(serializers.ModelSerializer):
    """Serializer for knowledge base details."""
    
    shop_name = serializers.CharField(source='shop.shop_name', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True, default='')
    
    class Meta:
        model = KnowledgeBase
        fields = [
            'id', 'question', 'answer', 'is_correct', 'shop', 'shop_name',
            'product', 'product_name',
            'category', 'keywords', 'usage_count', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'usage_count', 'created_at', 'updated_at']


class KnowledgeCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating knowledge base entry."""
    
    class Meta:
        model = KnowledgeBase
        fields = [
            'question', 'answer', 'is_correct', 'shop', 'category', 'keywords'
        ]
    
    def create(self, validated_data):
        validated_data['owner'] = self.context['request'].user
        return super().create(validated_data)


class KnowledgeSearchSerializer(serializers.Serializer):
    """Serializer for knowledge search request."""
    
    question = serializers.CharField(required=True)
    shop = serializers.CharField(required=False, allow_blank=True)
    threshold = serializers.FloatField(required=False, default=0.7, min_value=0, max_value=1)


class KnowledgeSearchResultSerializer(serializers.Serializer):
    """Serializer for knowledge search result."""
    
    id = serializers.IntegerField()
    question = serializers.CharField()
    answer = serializers.CharField()
    is_correct = serializers.BooleanField()
    similarity = serializers.FloatField()
    usage_count = serializers.IntegerField()
