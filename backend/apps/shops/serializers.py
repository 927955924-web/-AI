"""
Serializers for shops app.
"""
from rest_framework import serializers
from .models import Shop


class ShopSerializer(serializers.ModelSerializer):
    """Serializer for shop details."""
    
    platform_display = serializers.CharField(
        source='get_platform_type_display', 
        read_only=True
    )
    status_display = serializers.CharField(
        source='get_status_display', 
        read_only=True
    )
    owner_username = serializers.CharField(
        source='owner.username', 
        read_only=True
    )
    
    class Meta:
        model = Shop
        fields = [
            'shop_id', 'shop_name', 'account', 'login_url', 
            'platform_type', 'platform_display', 'status', 'status_display',
            'config_json', 'notes', 'is_active', 'owner_username',
            'last_login', 'created_at', 'updated_at'
        ]
        read_only_fields = ['shop_id', 'last_login', 'created_at', 'updated_at']


class ShopCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating a shop."""
    
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    
    class Meta:
        model = Shop
        fields = [
            'shop_name', 'account', 'password', 'login_url', 
            'platform_type', 'config_json', 'notes'
        ]
    
    def create(self, validated_data):
        # Get owner from request context
        validated_data['owner'] = self.context['request'].user
        return super().create(validated_data)


class ShopUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating a shop."""
    
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    
    class Meta:
        model = Shop
        fields = [
            'shop_name', 'account', 'password', 'login_url', 
            'platform_type', 'config_json', 'notes', 'is_active'
        ]
    
    def update(self, instance, validated_data):
        # Only update password if provided and not empty
        password = validated_data.get('password', '')
        if not password:
            validated_data.pop('password', None)
        return super().update(instance, validated_data)


class ShopListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for shop list."""
    
    platform_display = serializers.CharField(
        source='get_platform_type_display', 
        read_only=True
    )
    status_display = serializers.CharField(
        source='get_status_display', 
        read_only=True
    )
    session_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Shop
        fields = [
            'shop_id', 'shop_name', 'platform_type', 'platform_display',
            'status', 'status_display', 'is_active', 'session_count',
            'last_login', 'created_at', 'config_json', 'account', 'login_url'
        ]
    
    def get_session_count(self, obj):
        return obj.sessions.filter(status='active').count()
