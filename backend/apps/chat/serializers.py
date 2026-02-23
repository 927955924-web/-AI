"""
Serializers for chat app.
"""
from rest_framework import serializers
from .models import ChatSession, Message


class MessageSerializer(serializers.ModelSerializer):
    """Serializer for message details."""
    
    class Meta:
        model = Message
        fields = [
            'message_id', 'session', 'sender_type', 'sender_id', 'sender_name',
            'content', 'message_type', 'status', 'metadata_json', 'ai_source',
            'timestamp'
        ]
        read_only_fields = ['message_id', 'timestamp']


class MessageCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating a message."""
    
    session_id = serializers.CharField(write_only=True)
    
    class Meta:
        model = Message
        fields = [
            'session_id', 'sender_type', 'sender_id', 'sender_name',
            'content', 'message_type', 'metadata_json'
        ]
    
    def validate_session_id(self, value):
        try:
            session = ChatSession.objects.get(session_id=value)
            return session
        except ChatSession.DoesNotExist:
            raise serializers.ValidationError('会话不存在')
    
    def create(self, validated_data):
        session = validated_data.pop('session_id')
        message = Message.objects.create(session=session, **validated_data)
        # Update session last message
        session.update_last_message(message.content)
        return message


class ChatSessionSerializer(serializers.ModelSerializer):
    """Serializer for chat session details."""
    
    shop_name = serializers.CharField(source='shop.shop_name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    recent_messages = serializers.SerializerMethodField()
    
    class Meta:
        model = ChatSession
        fields = [
            'session_id', 'shop', 'shop_name', 'customer_id', 'customer_name',
            'platform', 'status', 'status_display', 'last_message',
            'metadata_json', 'message_count', 'unread_count',
            'created_at', 'updated_at', 'recent_messages'
        ]
        read_only_fields = [
            'session_id', 'message_count', 'unread_count', 
            'created_at', 'updated_at'
        ]
    
    def get_recent_messages(self, obj):
        # Only include recent messages if requested
        request = self.context.get('request')
        if request and request.query_params.get('include_messages'):
            messages = obj.messages.all()[:10]
            return MessageSerializer(messages, many=True).data
        return None


class ChatSessionCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating a chat session."""
    
    class Meta:
        model = ChatSession
        fields = [
            'shop', 'customer_id', 'customer_name', 'platform', 'metadata_json'
        ]
    
    def validate_shop(self, value):
        user = self.context['request'].user
        if user.role != 'admin' and value.owner != user:
            raise serializers.ValidationError('无权访问此店铺')
        return value


class ChatSessionListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for session list."""
    
    shop_name = serializers.CharField(source='shop.shop_name', read_only=True)
    
    class Meta:
        model = ChatSession
        fields = [
            'session_id', 'shop', 'shop_name', 'customer_name',
            'platform', 'status', 'last_message', 'message_count',
            'unread_count', 'updated_at'
        ]
