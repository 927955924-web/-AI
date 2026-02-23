"""
Serializers for products app.
"""
from rest_framework import serializers
from .models import Product


class ProductSerializer(serializers.ModelSerializer):
    """Serializer for product details."""
    
    shop_name = serializers.CharField(source='shop.shop_name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = Product
        fields = [
            'product_id', 'shop', 'shop_name', 'platform_product_id',
            'sku', 'name', 'price',
            'stock', 'status', 'status_display', 'description', 'image_url',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['product_id', 'created_at', 'updated_at']


class ProductCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating a product."""
    
    class Meta:
        model = Product
        fields = [
            'shop', 'platform_product_id', 'sku', 'name', 'price', 'stock', 'status', 
            'description', 'image_url'
        ]
    
    def validate_shop(self, value):
        user = self.context['request'].user
        if user.role != 'admin' and value.owner != user:
            raise serializers.ValidationError('无权访问此店铺')
        return value


class ProductListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for product list."""
    
    qa_count = serializers.IntegerField(read_only=True, default=0)
    
    class Meta:
        model = Product
        fields = [
            'product_id', 'shop', 'platform_product_id',
            'sku', 'name', 'price', 
            'stock', 'status', 'image_url', 'learning_status',
            'qa_count', 'created_at'
        ]
