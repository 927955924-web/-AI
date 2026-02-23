# -*- coding: utf-8 -*-
"""
Serializers for learning API.
"""
from rest_framework import serializers
from .models import LearningTask


class StartLearningSerializer(serializers.Serializer):
    """Serializer for starting a learning task."""
    shop_id = serializers.CharField(required=True, help_text='店铺ID')
    platform = serializers.ChoiceField(
        choices=['pdd', 'taobao', 'douyin'],
        required=True,
        help_text='平台类型'
    )


class LearningTaskSerializer(serializers.ModelSerializer):
    """Serializer for LearningTask model."""
    shop_name = serializers.CharField(source='shop.shop_name', read_only=True)
    progress_percent = serializers.SerializerMethodField()
    
    class Meta:
        model = LearningTask
        fields = [
            'task_id', 'shop_id', 'shop_name', 'platform', 'status',
            'total_products', 'processed_count', 'success_count', 
            'fail_count', 'qa_generated', 'progress_percent',
            'logs', 'started_at', 'completed_at'
        ]
        read_only_fields = fields
    
    def get_progress_percent(self, obj):
        if obj.total_products == 0:
            return 0
        return round(obj.processed_count / obj.total_products * 100, 1)


class ProductDataSerializer(serializers.Serializer):
    """Serializer for receiving product data from Electron client."""
    task_id = serializers.CharField(required=True)
    platform_product_id = serializers.CharField(required=True, help_text='平台商品ID')
    name = serializers.CharField(required=True, help_text='商品名称')
    price = serializers.DecimalField(
        max_digits=10, decimal_places=2, 
        required=False, default=0,
        help_text='价格'
    )
    original_price = serializers.DecimalField(
        max_digits=10, decimal_places=2,
        required=False, allow_null=True,
        help_text='原价'
    )
    stock = serializers.IntegerField(required=False, default=0, help_text='库存')
    sku = serializers.CharField(required=False, allow_blank=True, default='')
    description = serializers.CharField(required=False, allow_blank=True, default='')
    specs = serializers.JSONField(required=False, default=dict, help_text='规格参数')
    image_url = serializers.URLField(required=False, allow_blank=True, default='')
    detail_url = serializers.URLField(required=False, allow_blank=True, default='')


class ProductDataResponseSerializer(serializers.Serializer):
    """Response serializer for product processing."""
    success = serializers.BooleanField()
    product_id = serializers.CharField(required=False)
    qa_count = serializers.IntegerField(required=False)
    message = serializers.CharField(required=False)
