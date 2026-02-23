"""
Views for client app - Desktop client APIs.
"""
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone

from apps.chat.models import ChatSession, Message
from apps.shops.models import Shop


class HeartbeatView(APIView):
    """Client heartbeat endpoint."""
    
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        client_id = request.data.get('client_id', '')
        
        # Update user's last activity
        request.user.last_login = timezone.now()
        request.user.save(update_fields=['last_login'])
        
        return Response({
            'success': True,
            'data': {
                'server_time': timezone.now().isoformat(),
                'client_id': client_id
            }
        })


class SyncMessageView(APIView):
    """Sync messages from desktop client to server."""
    
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        platform_id = request.data.get('platform_id')
        customer_id = request.data.get('customer_id')
        customer_name = request.data.get('customer_name', 'Customer')
        message_text = request.data.get('message')
        reply_text = request.data.get('reply')
        reply_source = request.data.get('source', 'manual')
        shop_id = request.data.get('shop_id')
        
        if not message_text:
            return Response({
                'success': False,
                'error': {'message': 'Message is required'}
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Find or create shop
        shop = None
        if shop_id:
            try:
                shop = Shop.objects.get(shop_id=shop_id, owner=request.user)
            except Shop.DoesNotExist:
                pass
        
        # Find or create session
        session, created = ChatSession.objects.get_or_create(
            customer_id=customer_id,
            shop=shop,
            defaults={
                'customer_name': customer_name,
                'platform': platform_id or 'unknown',
                'owner': request.user,
                'status': 'active'
            }
        )
        
        if not created:
            session.customer_name = customer_name
            session.save(update_fields=['customer_name', 'updated_at'])
        
        # Create customer message
        customer_msg = Message.objects.create(
            session=session,
            sender_type='customer',
            content=message_text
        )
        
        # Create reply message if provided
        if reply_text:
            reply_msg = Message.objects.create(
                session=session,
                sender_type='ai' if reply_source != 'manual' else 'agent',
                content=reply_text,
                metadata={'source': reply_source}
            )
        
        # Update session counts
        session.message_count = session.messages.count()
        session.save(update_fields=['message_count', 'updated_at'])
        
        return Response({
            'success': True,
            'data': {
                'session_id': session.session_id,
                'message_id': customer_msg.message_id
            }
        })


class ClientSettingsView(APIView):
    """Get/update client settings."""
    
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        user = request.user
        
        # Get user's shops
        shops = Shop.objects.filter(owner=user, is_active=True).values(
            'shop_id', 'shop_name', 'platform_type', 'status'
        )
        
        return Response({
            'success': True,
            'data': {
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'vip_status': user.vip_status
                },
                'shops': list(shops),
                'settings': {
                    'auto_reply': True,
                    'reply_delay': 0,
                    'welcome_message': ''
                }
            }
        })
    
    def put(self, request):
        # Save client settings
        # In a real app, you'd save these to a ClientSettings model
        return Response({
            'success': True,
            'message': 'Settings updated'
        })
